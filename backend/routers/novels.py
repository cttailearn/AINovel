import asyncio
import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from config import (
    ALLOWED_NOVEL_EXT,
    DEFAULT_CHUNK_SIZE,
    MAX_UPLOAD_SIZE,
    NOVELS_DIR,
)
from schemas import (
    ChapterDetail,
    ChapterUpdate,
    KnowledgeGraphRequest,
    KnowledgeGraphResponse,
    KnowledgeGraphValidation,
    NovelDetail,
    NovelListResponse,
    NovelUpdate,
    NovelUploadResponse,
    ParseFixedRequest,
    ParsePreviewResponse,
    ParseResponse,
    ParseRuleRequest,
)
from services import (
    ParseError,
    delete_knowledge_graph,
    delete_novel,
    extract_knowledge_graph,
    extract_knowledge_graph_streaming,
    extract_knowledge_graph_v2,
    get_chapter,
    get_novel_detail,
    get_raw_content,
    list_all_novels,
    list_knowledge_graph,
    parse_chapters_by_rule,
    parse_chapters_fixed_size,
    preview_chapters_by_rule,
    re_extract_knowledge_graph,
    update_chapter_info,
    update_novel_info,
    upload_novel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novels", tags=["Novels"])


@router.get("", response_model=NovelListResponse)
async def get_novels():
    return {"novels": await list_all_novels()}


@router.post(
    "/upload",
    response_model=NovelUploadResponse,
    status_code=201,
)
async def upload_novel_endpoint(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_NOVEL_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持以下文件格式: {', '.join(sorted(ALLOWED_NOVEL_EXT))}",
        )

    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_UPLOAD_SIZE} 字节限制",
        )
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        return await upload_novel(
            original_filename=safe_name, content=content
        )
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Upload failed: %s", exc)
        raise HTTPException(status_code=500, detail="上传失败，请稍后再试")


@router.get("/{novel_id}", response_model=NovelDetail)
async def get_novel(novel_id: int):
    novel = await get_novel_detail(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return novel


@router.put("/{novel_id}")
async def update_novel(novel_id: int, payload: NovelUpdate):
    ok = await update_novel_info(novel_id, payload.title, payload.author)
    if not ok:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "小说信息已更新"}


@router.delete("/{novel_id}")
async def delete_novel_endpoint(novel_id: int):
    ok = await delete_novel(novel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "小说已删除"}


@router.put("/{novel_id}/parse-rule")
async def set_parse_rule(novel_id: int, payload: ParseRuleRequest):
    novel = await get_novel_detail(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    from database import update_novel_parse_rule

    await update_novel_parse_rule(novel_id, payload.rule)
    return {"message": "规则已更新", "rule": payload.rule}


@router.post("/{novel_id}/parse", response_model=ParseResponse)
async def parse_chapters(novel_id: int, payload: ParseRuleRequest):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await parse_chapters_by_rule(novel_id, payload.rule)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/{novel_id}/parse-preview", response_model=ParsePreviewResponse
)
async def parse_preview(novel_id: int, payload: ParseRuleRequest):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await preview_chapters_by_rule(novel_id, payload.rule)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/{novel_id}/parse-fixed", response_model=ParseResponse
)
async def parse_fixed(novel_id: int, payload: ParseFixedRequest):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await parse_chapters_fixed_size(novel_id, payload.chunk_size)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetail
)
async def get_chapter_endpoint(novel_id: int, chapter_id: int):
    chapter = await get_chapter(novel_id, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.put("/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetail)
async def update_chapter_endpoint(
    novel_id: int, chapter_id: int, payload: ChapterUpdate
):
    """更新章节标题或正文(供阅读器内编辑/替换保存使用)."""
    if payload.title is None and payload.content is None:
        raise HTTPException(
            status_code=400, detail="至少需要提供 title 或 content 之一"
        )
    ok = await update_chapter_info(
        novel_id,
        chapter_id,
        title=payload.title,
        content=payload.content,
    )
    if not ok:
        raise HTTPException(
            status_code=404, detail="章节不存在或未发生变更"
        )
    chapter = await get_chapter(novel_id, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.get("/{novel_id}/raw")
async def get_raw_content_endpoint(
    novel_id: int,
    chunk_size: int = Query(
        DEFAULT_CHUNK_SIZE, gt=0, le=100_000
    ),
):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await get_raw_content(novel_id, chunk_size)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{novel_id}/knowledge-graph")
async def get_knowledge_graph_endpoint(
    novel_id: int,
    kg_system: Optional[str] = Query(
        default=None,
        description="KG 系统: novel (默认, 兼容旧接口) | ai (项目级, 推荐).",
    ),
):
    """返回指定小说的知识图谱.

    修复 #3: 即使当前只走物理 novels 级 KG, 响应里也额外返回
    ``kg_system`` 与 (若为 ``novel``) ``deprecated_notice``, 方便前端识别
    老接口、渐进迁移到 ``ai_kg_*``.
    """
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    from db.kg import (
        DEPRECATED_NOTICE,
        KgSystem,
        is_deprecated_novel_kg,
        kg_system_from_request,
    )

    chosen = kg_system_from_request(kg_system, default=KgSystem.NOVEL)
    payload = await list_knowledge_graph(novel_id)
    payload["kg_system"] = chosen.value
    if is_deprecated_novel_kg(chosen):
        payload["deprecated_notice"] = DEPRECATED_NOTICE
    return payload


@router.delete("/{novel_id}/knowledge-graph")
async def delete_knowledge_graph_endpoint(novel_id: int):
    """清空指定小说的全部知识图谱(人物/事件/3 类关系).

    与"重新提取"不同, 这是纯删除操作, 不会触发 LLM 抽取.
    用于: 抽取结果有严重错误, 想从零重抽, 或测试场景.
    """
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        counts = await delete_knowledge_graph(novel_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("delete knowledge graph failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="删除知识图谱失败，请稍后重试"
        )
    return {
        "success": True,
        "novel_id": novel_id,
        "deleted": {
            "characters": counts.get("characters", 0),
            "events": counts.get("events", 0),
            "participations": counts.get("character_event_relations", 0),
            "character_relations": counts.get("character_relations", 0),
            "event_relations": counts.get("event_relations", 0),
        },
    }


@router.post(
    "/{novel_id}/knowledge-graph/re-extract",
    response_model=KnowledgeGraphResponse,
)
async def re_extract_knowledge_graph_endpoint(
    novel_id: int, payload: KnowledgeGraphRequest
):
    """删除后重新抽取知识图谱(走 v2 流水线).

    语义上等价于: DELETE /knowledge-graph + POST /knowledge-graph/v2,
    但写在一个事务内, 避免"先删后抽"中间状态被前端看到.
    """
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        result = await re_extract_knowledge_graph(
            novel_id,
            model_config_id=payload.model_config_id,
            chunk_size=payload.chunk_size,
            max_concurrency=payload.max_concurrency,
            run_validator=payload.run_validator,
            run_llm_dedup=payload.run_llm_dedup,
            run_llm_completeness=payload.run_llm_completeness,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("KG re-extract failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="知识图谱重新提取失败，请稍后重试"
        )

    stats = result["stats"]
    summary = (
        f"重新抽取完成：{stats['characters']} 位人物、{stats['events']} 个事件、"
        f"{stats['participations']} 条参与、{stats['character_relations']} 条人物关系、"
        f"{stats['event_relations']} 条事件关系"
    )
    validation = result.get("validation")
    return KnowledgeGraphResponse(
        success=True,
        message=summary,
        model=result.get("model"),
        chunks_processed=result.get("chunks_processed", 0),
        characters=result["characters"],
        events=result["events"],
        character_event_relations=result["character_event_relations"],
        character_relations=result["character_relations"],
        event_relations=result["event_relations"],
        stats=stats,
        validation=(
            KnowledgeGraphValidation(**validation) if validation else None
        ),
    )


@router.get("/{novel_id}/kg-stats")
async def get_kg_stats_endpoint(novel_id: int):
    from database import get_kg_stats
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    return await get_kg_stats(novel_id)


@router.post(
    "/{novel_id}/knowledge-graph",
    response_model=KnowledgeGraphResponse,
)
async def extract_knowledge_graph_endpoint(
    novel_id: int, payload: KnowledgeGraphRequest
):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        result = await extract_knowledge_graph(
            novel_id,
            model_config_id=payload.model_config_id,
            chunk_size=payload.chunk_size,
            max_concurrency=payload.max_concurrency,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Knowledge graph extraction failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="知识图谱构建失败，请稍后重试"
        )
    stats = result["stats"]
    summary = (
        f"抽取完成：{stats['characters']} 位人物、{stats['events']} 个事件、"
        f"{stats['participations']} 条参与、{stats['character_relations']} 条人物关系、"
        f"{stats['event_relations']} 条事件关系"
    )
    return KnowledgeGraphResponse(
        success=True,
        message=summary,
        model=result.get("model"),
        chunks_processed=result.get("chunks_processed", 0),
        characters=result["characters"],
        events=result["events"],
        character_event_relations=result["character_event_relations"],
        character_relations=result["character_relations"],
        event_relations=result["event_relations"],
        stats=stats,
    )


def _sse_format(event: str, data: Any) -> bytes:
    """Encode a single Server-Sent Event payload."""
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


@router.post("/{novel_id}/knowledge-graph/stream")
async def extract_knowledge_graph_stream_endpoint(
    novel_id: int, payload: KnowledgeGraphRequest
):
    """Stream knowledge-graph extraction progress + partial results via SSE."""
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")

    progress_queue: asyncio.Queue = asyncio.Queue()
    partial_state: Dict[str, List[Dict[str, Any]]] = {}

    def _emit_progress(p: Dict[str, Any]) -> None:
        progress_queue.put_nowait(("progress", p))

    def _emit_partial(key: str, items: List[Dict[str, Any]]) -> None:
        partial_state[key] = items
        # Emit the cumulative state snapshot to keep client simple.
        progress_queue.put_nowait(("partial", {key: items}))

    async def _run_extraction() -> None:
        try:
            result = await extract_knowledge_graph_streaming(
                novel_id,
                model_config_id=payload.model_config_id,
                chunk_size=payload.chunk_size,
                max_concurrency=payload.max_concurrency,
                on_progress=_emit_progress,
                on_partial=_emit_partial,
            )
            progress_queue.put_nowait(("done", result))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Streaming extraction failed: %s", exc)
            progress_queue.put_nowait(("error", str(exc)))
        finally:
            progress_queue.put_nowait(("__end__", None))

    async def event_stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(_run_extraction())
        try:
            while True:
                kind, payload_obj = await progress_queue.get()
                if kind == "__end__":
                    break
                yield _sse_format(kind, payload_obj)
            # Drain a final cancellation check.
            if not task.done():
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.TimeoutError:
                    task.cancel()
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# Multi-agent v2 endpoints (ExtractorAgent + MergeValidatorAgent)
# ---------------------------------------------------------------------------


@router.post(
    "/{novel_id}/knowledge-graph/v2",
    response_model=KnowledgeGraphResponse,
)
async def extract_knowledge_graph_v2_endpoint(
    novel_id: int, payload: KnowledgeGraphRequest
):
    """Run the multi-agent pipeline (ExtractorAgent + MergeValidatorAgent).

    Equivalent to ``/knowledge-graph`` but goes through the new agent
    abstraction and returns a ``validation`` block (issues, dedup log,
    coverage report).
    """
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        result = await extract_knowledge_graph_v2(
            novel_id,
            model_config_id=payload.model_config_id,
            chunk_size=payload.chunk_size,
            max_concurrency=payload.max_concurrency,
            run_validator=payload.run_validator,
            run_llm_dedup=payload.run_llm_dedup,
            run_llm_completeness=payload.run_llm_completeness,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("KG v2 extraction failed: %s", exc)
        raise HTTPException(
            status_code=500, detail="知识图谱 v2 构建失败，请稍后重试"
        )

    stats = result["stats"]
    summary = (
        f"v2 抽取完成：{stats['characters']} 位人物、{stats['events']} 个事件、"
        f"{stats['participations']} 条参与、{stats['character_relations']} 条人物关系、"
        f"{stats['event_relations']} 条事件关系"
    )
    validation = result.get("validation")
    return KnowledgeGraphResponse(
        success=True,
        message=summary,
        model=result.get("model"),
        chunks_processed=result.get("chunks_processed", 0),
        characters=result["characters"],
        events=result["events"],
        character_event_relations=result["character_event_relations"],
        character_relations=result["character_relations"],
        event_relations=result["event_relations"],
        stats=stats,
        validation=(
            KnowledgeGraphValidation(**validation) if validation else None
        ),
    )


@router.post("/{novel_id}/knowledge-graph/v2/stream")
async def extract_knowledge_graph_v2_stream_endpoint(
    novel_id: int, payload: KnowledgeGraphRequest
):
    """SSE streaming version of the v2 pipeline.

    Emits the same event types as the legacy stream endpoint, plus a
    final ``validation`` event carrying the validator's report.
    """
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")

    progress_queue: asyncio.Queue = asyncio.Queue()

    def _emit_progress(p: Dict[str, Any]) -> None:
        progress_queue.put_nowait(("progress", p))

    def _emit_partial(key: str, items: List[Dict[str, Any]]) -> None:
        progress_queue.put_nowait(("partial", {key: items}))

    async def _run_extraction() -> None:
        try:
            result = await extract_knowledge_graph_v2(
                novel_id,
                model_config_id=payload.model_config_id,
                chunk_size=payload.chunk_size,
                max_concurrency=payload.max_concurrency,
                run_validator=payload.run_validator,
                run_llm_dedup=payload.run_llm_dedup,
                run_llm_completeness=payload.run_llm_completeness,
                on_progress=_emit_progress,
                on_partial=_emit_partial,
            )
            progress_queue.put_nowait(("done", result))
            # Send the validation report as a separate event so the
            # client can render the issue panel even after ``done``.
            if result.get("validation"):
                progress_queue.put_nowait(("validation", result["validation"]))
        except Exception as exc:  # noqa: BLE001
            logger.exception("KG v2 streaming failed: %s", exc)
            progress_queue.put_nowait(("error", str(exc)))
        finally:
            progress_queue.put_nowait(("__end__", None))

    async def event_stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(_run_extraction())
        try:
            while True:
                kind, payload_obj = await progress_queue.get()
                if kind == "__end__":
                    break
                yield _sse_format(kind, payload_obj)
            if not task.done():
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.TimeoutError:
                    task.cancel()
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
