"""Routes for the AI novel creation (AI 小说创作) module.

Mounted at ``/api/creation``. The chapter generation endpoint
(``POST /projects/{id}/chapters/generate``) is a Server-Sent Events stream;
the client uses ``api.creation.generate`` in the frontend.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from schemas import (
    AiChapterContentUpdate,
    AiChapterDetailResponse,
    AiChapterGenerateRequest,
    AiChapterListResponse,
    AiChapterSelectRequest,
    AiIntakeNextRequest,
    AiIntakeNextResponse,
    AiIntakeSynthesizeRequest,
    AiIntakeSynthesizeResponse,
    AiProjectCreate,
    AiProjectDetailResponse,
    AiProjectListResponse,
    AiProjectUpdate,
)
from services import creation_intake_service, creation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/creation", tags=["AICreation"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_format(event: str, data: Any) -> bytes:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _map_creation_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc) or exc.__class__.__name__)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@router.get("/projects", response_model=AiProjectListResponse)
async def list_projects():
    projects = await creation_service.list_projects()
    return {"projects": projects}


@router.post("/projects", response_model=Dict[str, Any])
async def create_project(payload: AiProjectCreate):
    try:
        new_id = await creation_service.create_project(payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise _map_creation_error(exc) from exc
    return {"id": new_id}


@router.get("/projects/{project_id}", response_model=AiProjectDetailResponse)
async def get_project(project_id: int):
    try:
        detail = await creation_service.get_project_detail(project_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return detail


@router.put("/projects/{project_id}")
async def update_project(project_id: int, payload: AiProjectUpdate):
    data = payload.model_dump(exclude_unset=True)
    ok = await creation_service.update_project(project_id, data)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在或未变更")
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int):
    ok = await creation_service.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# 新建项目引导式问答 (Intake wizard)
# ---------------------------------------------------------------------------


@router.post(
    "/intake/synthesize",
    response_model=AiIntakeSynthesizeResponse,
)
async def intake_synthesize(payload: AiIntakeSynthesizeRequest):
    """把引导式问答结果交给 LLM, 综合为可一键建项的项目草稿.

    LLM 不可用 / 输出非法 JSON 时, 仍会走本地兜底返回一份可用的草稿,
    因此该接口在系统配置基本正确的前提下不应抛 5xx.
    """
    try:
        return await creation_intake_service.synthesize_project(payload)
    except creation_intake_service.IntakeError as exc:
        # 真正致命: 没有可用模型且兜底也无法生成
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("intake synthesize crashed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"综合项目草稿失败: {exc}"
        ) from exc


@router.post(
    "/intake/next",
    response_model=AiIntakeNextResponse,
)
async def intake_next(payload: AiIntakeNextRequest):
    """根据已完成的问答历史, 让 LLM 动态生成下一道题 (4~8 个差异化选项).

    不可恢复错误只发生在 ``items`` 字段类型错乱时; LLM 不可用 / 输出非法 JSON
    / 模型无响应时, 会走本地兜底题库, 接口仍能正常返回下一题或 done 信号.
    """
    try:
        return await creation_intake_service.generate_next_question(payload)
    except creation_intake_service.IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("intake next crashed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"生成下一题失败: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Knowledge graph (project-level)
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/kg")
async def get_kg(project_id: int):
    try:
        return await creation_service.get_kg(project_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/projects/{project_id}/kg")
async def delete_kg(project_id: int):
    counts = await creation_service.delete_kg(project_id)
    return {"counts": counts}


@router.post("/projects/{project_id}/kg/seed")
async def seed_kg(project_id: int):
    try:
        result = await creation_service.seed_kg_from_concepts(project_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/chapters", response_model=AiChapterListResponse)
async def list_chapters(project_id: int):
    chapters = await creation_service.list_chapters(project_id)
    return {"chapters": chapters}


@router.get("/chapters/{chapter_id}", response_model=AiChapterDetailResponse)
async def get_chapter(chapter_id: int):
    try:
        ch = await creation_service.get_chapter_detail(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"chapter": ch}


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: int):
    """删除单个章节 (含变体). 会回退 project.current_chapter_no 避免空号."""
    ok = await creation_service.delete_chapter(chapter_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"章节 {chapter_id} 不存在")
    return {"ok": True}


@router.get("/chapters/{chapter_id}/export")
async def export_chapter(
    chapter_id: int,
    format: str = Query("txt", pattern="^(txt|md)$"),
):
    """把章节正文导出为可下载的纯文本 (.txt) / Markdown (.md)."""
    try:
        detail = await creation_service.get_chapter_detail(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        body = await creation_service.export_chapter_as_text(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 文件名: ASCII 兜底 (latin-1 兼容) + RFC 5987 中文名
    project = detail.get("project_id")
    ch = detail
    title = ch.get("title") or f"第 {ch.get('chapter_no')} 章"
    chapter_no = int(ch.get("chapter_no") or 0)
    safe = (title or f"第{chapter_no:03d}章").replace("/", "_").replace("\\", "_")[:80]
    filename = f"ch{chapter_no:03d}_{safe}.{format}"
    # ASCII 兜底 (只允许 [a-zA-Z0-9._-], 其余替换为 _)
    import re as _re
    ascii_fallback = _re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or f"chapter.{format}"
    # RFC 5987: filename*=UTF-8''urlencoded
    from urllib.parse import quote as _quote
    filename_star = _quote(filename, safe="")

    # BOM 让 Windows 记事本识别 UTF-8
    content_bytes = (b"\xef\xbb\xbf" + body.encode("utf-8")) if format == "txt" else body.encode("utf-8")
    media_type = "text/plain; charset=utf-8" if format == "txt" else "text/markdown; charset=utf-8"

    return Response(
        content=content_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{filename_star}"
            ),
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/projects/{project_id}/chapters/generate",
    response_class=StreamingResponse,
)
async def generate_chapter(project_id: int, payload: AiChapterGenerateRequest):
    """SSE 推送 Planner / Writer / Critic 阶段事件.

    事件类型参见 ``creation_service.generate_chapter_streaming``.
    """
    progress_queue: asyncio.Queue = asyncio.Queue()
    cancel_flag = {"cancelled": False}

    def _should_cancel() -> bool:
        return cancel_flag["cancelled"]

    async def _runner() -> None:
        try:
            async for ev in creation_service.generate_chapter_streaming(
                project_id,
                user_intent=payload.user_intent,
                chapter_no=payload.chapter_no,
                title=payload.title,
            ):
                if _should_cancel():
                    break
                await progress_queue.put(ev)
        except Exception as exc:  # noqa: BLE001
            logger.exception("chapter generation crashed: %s", exc)
            await progress_queue.put(
                {"event": "error", "message": f"生成异常: {exc}"}
            )
        finally:
            await progress_queue.put({"event": "__end__"})

    async def event_stream() -> AsyncIterator[bytes]:
        task = asyncio.create_task(_runner())
        try:
            while True:
                ev = await progress_queue.get()
                if ev.get("event") == "__end__":
                    break
                yield _sse_format(ev.get("event", "message"), ev)
            if not task.done():
                try:
                    await asyncio.wait_for(task, timeout=1.0)
                except asyncio.TimeoutError:
                    task.cancel()
        finally:
            cancel_flag["cancelled"] = True
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


@router.post("/chapters/{chapter_id}/select", response_model=AiChapterDetailResponse)
async def select_variant(chapter_id: int, payload: AiChapterSelectRequest):
    try:
        ch = await creation_service.select_variant(chapter_id, payload.variant_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"chapter": ch}


@router.put(
    "/chapters/{chapter_id}/content",
    response_model=AiChapterDetailResponse,
)
async def update_content(chapter_id: int, payload: AiChapterContentUpdate):
    try:
        ch = await creation_service.update_chapter_content(
            chapter_id, payload.content
        )
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"chapter": ch}


@router.post(
    "/chapters/{chapter_id}/confirm",
    response_model=AiChapterDetailResponse,
)
async def confirm_chapter(chapter_id: int):
    try:
        ch = await creation_service.confirm_chapter(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"chapter": ch}
