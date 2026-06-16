"""Routes for the AI novel creation (AI 小说创作) module.

Mounted at ``/api/creation``. The chapter generation endpoint
(``POST /projects/{id}/chapters/generate``) is a Server-Sent Events stream;
the client uses ``api.creation.generate`` in the frontend.

任务持久�?
----------
�?enrichment 一�? 章节生成任务�?``TaskRegistry`` 中以应用作用域的形式
�? SSE 客户端断开不再取消任务, 用户刷新后通过 ``task_id`` 重新订阅即可.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncIterator, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

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
    AiKgCharacterCreate,
    AiKgCharacterEventRelationCreate,
    AiKgCharacterUpdate,
    AiKgEventCreate,
    AiKgEventUpdate,
    AiKgLocationCreate,
    AiKgLocationUpdate,
    AiPlotThreadCreate,
    AiPlotThreadUpdate,
    AiProjectCreate,
    AiProjectDetailResponse,
    AiProjectListResponse,
    AiProjectUpdate,
)
from services import creation_intake_service, creation_service
from services.task_registry import KIND_CREATION, registry
import database as db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/creation", tags=["AICreation"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse_format(event: str, data: Any) -> bytes:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _sse_error_response(status_code: int, message: str) -> StreamingResponse:
    """修复 #14: 把业务校验失败包装成 SSE 响应, 让前端能在 toast 里看到
    真实错误原因, 而不是 "请求失败 (404)".

    通过返回 200 + 单条 error SSE 事件 + 立即关闭流, 让 EventSource / XHR
    走正常成功路径解析 body.
    """
    async def gen() -> AsyncIterator[bytes]:
        yield _sse_format("error", {"message": message, "status": status_code})
        yield _sse_format("__end__", {"final_state": "error"})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
        result = await creation_service.create_project(payload.model_dump())
    except Exception as exc:  # noqa: BLE001
        raise _map_creation_error(exc) from exc
    return result


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
    result = await creation_service.update_project(project_id, data)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail="项目不存在或未变更")
    return result


@router.delete("/projects/{project_id}")
async def delete_project(project_id: int):
    ok = await creation_service.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"ok": True}


@router.post("/projects/{project_id}/duplicate")
async def duplicate_project(project_id: int):
    """UX-#15: 复制项目 (只复制设�?+ KG, 不复制章节正�?."""
    try:
        new_id = await creation_service.duplicate_project(project_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": new_id}


# ---------------------------------------------------------------------------
# 新建项目引导式问�?(Intake wizard)
# ---------------------------------------------------------------------------


@router.post(
    "/intake/synthesize",
    response_model=AiIntakeSynthesizeResponse,
)
async def intake_synthesize(payload: AiIntakeSynthesizeRequest):
    """把引导式问答结果交给 LLM, 综合为可一键建项的项目草稿.

    LLM 不可�?/ 输出非法 JSON �? 仍会走本地兜底返回一份可用的草稿,
    因此该接口在系统配置基本正确的前提下不应�?5xx.
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
    """根据已完成的问答历史, �?LLM 动态生成下一道题 (4~8 个差异化选项).

    不可恢复错误只发生在 ``items`` 字段类型错乱�? LLM 不可�?/ 输出非法 JSON
    / 模型无响应时, 会走本地兜底题库, 接口仍能正常返回下一题或 done 信号.
    """
    try:
        return await creation_intake_service.generate_next_question(payload)
    except creation_intake_service.IntakeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("intake next crashed: %s", exc)
        raise HTTPException(
            status_code=500, detail=f"生成下一题失�? {exc}"
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
# KG 节点 / 关系 CRUD (前端手动编辑)
# ---------------------------------------------------------------------------


def _normalize_entity_id(entity_id: Optional[str], prefix: str) -> str:
    """entity_id 空时自动生成 'prefix_<随机>'."""
    if entity_id and entity_id.strip():
        return entity_id.strip()[:64]
    import uuid as _uuid
    return f"{prefix}_{_uuid.uuid4().hex[:10]}"


def _map_creation_value_error(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.post("/projects/{project_id}/kg/characters")
async def create_kg_character(project_id: int, payload: AiKgCharacterCreate):
    try:
        # 确认项目存在
        await creation_service.assert_project_exists(project_id)
        entity_id = _normalize_entity_id(payload.entity_id, "char")
        new_id = await db.insert_ai_kg_character(
            project_id,
            entity_id=entity_id,
            name=payload.name,
            attributes=payload.attributes,
            role=payload.role,
            faction=payload.faction,
            status=payload.status,
            importance=payload.importance,
        )
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise _map_creation_value_error(exc) from exc
    return {"id": new_id, "entity_id": entity_id}


@router.put("/projects/{project_id}/kg/characters/{entity_id}")
async def update_kg_character(
    project_id: int, entity_id: str, payload: AiKgCharacterUpdate
):
    data = payload.model_dump(exclude_unset=True)
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.update_ai_kg_character(project_id, entity_id, **data)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"人物 {entity_id} 不存在")
    return {"ok": True, "entity_id": entity_id}


@router.delete("/projects/{project_id}/kg/characters/{entity_id}")
async def delete_kg_character(project_id: int, entity_id: str):
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.delete_ai_kg_character(project_id, entity_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"人物 {entity_id} 不存在")
    return {"ok": True}


@router.post("/projects/{project_id}/kg/events")
async def create_kg_event(project_id: int, payload: AiKgEventCreate):
    try:
        await creation_service.assert_project_exists(project_id)
        entity_id = _normalize_entity_id(payload.entity_id, "evt")
        new_id = await db.insert_ai_kg_event(
            project_id,
            entity_id=entity_id,
            name=payload.name,
            attributes=payload.attributes,
            importance=payload.importance,
            in_story_time=payload.in_story_time,
        )
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise _map_creation_value_error(exc) from exc
    return {"id": new_id, "entity_id": entity_id}


@router.put("/projects/{project_id}/kg/events/{entity_id}")
async def update_kg_event(
    project_id: int, entity_id: str, payload: AiKgEventUpdate
):
    data = payload.model_dump(exclude_unset=True)
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.update_ai_kg_event(project_id, entity_id, **data)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"事件 {entity_id} 不存在")
    return {"ok": True, "entity_id": entity_id}


@router.delete("/projects/{project_id}/kg/events/{entity_id}")
async def delete_kg_event(project_id: int, entity_id: str):
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.delete_ai_kg_event(project_id, entity_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"事件 {entity_id} 不存在")
    return {"ok": True}


@router.post("/projects/{project_id}/kg/locations")
async def create_kg_location(project_id: int, payload: AiKgLocationCreate):
    try:
        await creation_service.assert_project_exists(project_id)
        entity_id = _normalize_entity_id(payload.entity_id, "loc")
        new_id = await db.insert_ai_kg_location(
            project_id,
            entity_id=entity_id,
            name=payload.name,
            location_type=payload.location_type,
            attributes=payload.attributes,
        )
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise _map_creation_value_error(exc) from exc
    return {"id": new_id, "entity_id": entity_id}


@router.put("/projects/{project_id}/kg/locations/{entity_id}")
async def update_kg_location(
    project_id: int, entity_id: str, payload: AiKgLocationUpdate
):
    data = payload.model_dump(exclude_unset=True)
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.update_ai_kg_location(project_id, entity_id, **data)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"地点 {entity_id} 不存在")
    return {"ok": True, "entity_id": entity_id}


@router.delete("/projects/{project_id}/kg/locations/{entity_id}")
async def delete_kg_location(project_id: int, entity_id: str):
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.delete_ai_kg_location(project_id, entity_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"地点 {entity_id} 不存不存在")
    return {"ok": True}


@router.post("/projects/{project_id}/kg/character-event-relations")
async def create_kg_ce_relation(
    project_id: int, payload: AiKgCharacterEventRelationCreate
):
    try:
        await creation_service.assert_project_exists(project_id)
        new_id = await db.insert_ai_kg_character_event_relation(
            project_id,
            source_entity_id=payload.source_entity_id,
            target_entity_id=payload.target_entity_id,
            relation=payload.relation,
            role=payload.role,
            action=payload.action,
            properties=payload.properties,
        )
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"id": new_id}


# P1-#6: PlotThread CRUD 端点 (前端手动管理伏笔/线索)
@router.get("/projects/{project_id}/plot-threads")
async def list_plot_threads(project_id: int, status: Optional[str] = None):
    try:
        await creation_service.assert_project_exists(project_id)
        threads = await db.list_ai_kg_plot_threads(project_id, status=status)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"threads": threads}


@router.post("/projects/{project_id}/plot-threads")
async def create_plot_thread(project_id: int, payload: AiPlotThreadCreate):
    try:
        await creation_service.assert_project_exists(project_id)
        thread_id = payload.thread_id or f"thr_{uuid.uuid4().hex[:10]}"
        new_id = await db.insert_ai_kg_plot_thread(
            project_id,
            thread_id=thread_id,
            title=payload.title,
            thread_type=payload.thread_type,
            status=payload.status,
            priority=payload.priority,
            related_entity_ids=payload.related_entity_ids,
            notes=payload.notes,
        )
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": new_id, "thread_id": thread_id}


@router.put("/projects/{project_id}/plot-threads/{thread_id}")
async def update_plot_thread(
    project_id: int, thread_id: str, payload: AiPlotThreadUpdate
):
    data = payload.model_dump(exclude_unset=True)
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.update_ai_kg_plot_thread(project_id, thread_id, **data)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"线索 {thread_id} 不存不存在")
    return {"ok": True, "thread_id": thread_id}


@router.delete("/projects/{project_id}/plot-threads/{thread_id}")
async def delete_plot_thread(project_id: int, thread_id: str):
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.delete_ai_kg_plot_thread(project_id, thread_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"线索 {thread_id} 不存不存在")
    return {"ok": True}


@router.delete("/projects/{project_id}/kg/relations/{rel_kind}/{rel_id}")
async def delete_kg_relation(project_id: int, rel_kind: str, rel_id: int):
    try:
        await creation_service.assert_project_exists(project_id)
        ok = await db.delete_ai_kg_relation(project_id, rel_kind, rel_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise _map_creation_value_error(exc) from exc
    if not ok:
        raise HTTPException(status_code=404, detail=f"关系 {rel_kind}/{rel_id} 不存不存在")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chapters
# ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/chapters", response_model=AiChapterListResponse)
async def list_chapters(project_id: int):
    chapters = await creation_service.list_chapters(project_id)
    return {"chapters": chapters}


# P1-#6 兼容, 也供 UX-#6 拖拽重排使用
class ReorderRequest(BaseModel):
    orders: List[Dict[str, int]] = Field(..., min_length=1)


@router.post("/projects/{project_id}/chapters/reorder")
async def reorder_chapters(project_id: int, payload: ReorderRequest):
    """UX-#6: 拖拽重排. 接受 [{id, chapter_no}, ...], 临时偏移避免唯一约束冲突."""
    try:
        n = await creation_service.reorder_chapters(project_id, payload.orders)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "updated": n}


@router.get("/chapters/{chapter_id}", response_model=AiChapterDetailResponse)
async def get_chapter(chapter_id: int):
    try:
        ch = await creation_service.get_chapter_detail(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"chapter": ch}


@router.delete("/chapters/{chapter_id}")
async def delete_chapter(chapter_id: int):
    """删除单个章节 (含变�?. 会回退 project.current_chapter_no 避免空号."""
    ok = await creation_service.delete_chapter(chapter_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"章节 {chapter_id} 不存不存在")
    return {"ok": True}


@router.get("/chapters/{chapter_id}/variants/history")
async def get_chapter_variants_history(chapter_id: int):
    """P0-#3: 获取章节全部变体 (含历史轮�?, �?round/idx 排序.
    用于"查看历史版本"UI, 让用户能回退到之前任意一�?
    """
    try:
        history = await creation_service.get_chapter_variants_history(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"history": history}


@router.get("/chapters/{chapter_id}/export")
async def export_chapter(
    chapter_id: int,
    format: str = Query("txt", pattern="^(txt|md)$"),
):
    """把章节正文导出为可下载的纯文�?(.txt) / Markdown (.md)."""
    try:
        detail = await creation_service.get_chapter_detail(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        body = await creation_service.export_chapter_as_text(chapter_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 文件�? ASCII 兜底 (latin-1 兼容) + RFC 5987 中文�?
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

    # BOM �?Windows 记事本识�?UTF-8
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


@router.get("/projects/{project_id}/export")
async def export_project(
    project_id: int,
    format: str = Query("txt", pattern="^(txt|md)$"),
):
    """UX-#16: 全本导出. 把整个项目所有已确认章节合并为一个可下载文件 (.txt / .md).

    章节�?``chapter_no`` 升序拼接, 章节之间空一�? 文件头写入项目标题与
    生成时间. 跟单章导出一样支�?ASCII 兜底文件�?+ RFC 5987 中文�?
    """
    try:
        detail = await creation_service.get_project_detail(project_id)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        body = await creation_service.export_project_as_text(project_id, format=format)
    except creation_service.CreationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    project = detail.get("project") if isinstance(detail, dict) else None
    title = (project or {}).get("title") if isinstance(project, dict) else None
    safe = (title or f"项目{project_id}").replace("/", "_").replace("\\", "_")[:80]
    filename = f"project_{project_id}_{safe}.{format}"
    import re as _re
    ascii_fallback = _re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or f"project.{format}"
    from urllib.parse import quote as _quote
    filename_star = _quote(filename, safe="")

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

    任务以应用作用域的 ``TaskRecord`` 形式跑在 ``TaskRegistry`` 中, 同一
    项目同时只允许 1 个生成任务. SSE 客户端断开不再取消任务.

    修复 #14: 之前的 HTTPException (404 / 409) 在 SSE 模式下会直接断开流,
    前端拿不到 detail 文案, toast 显示 "请求失败 (404)". 改为: 业务校验
    失败时返回一个 fallback record, 通过 record.publish({event: "error",
    message: ...}) 把消息推给客户端. 仅当 registry.register 因「同 scope
    已有任务」冲突时, 才保持 409 — 这种情况下客户端需要立刻重定向到
    banner 重连.
    """
    # 校验项目存在, 顺便拿到 title 用于 banner 文案
    try:
        project = await creation_service.get_project_detail(project_id)
    except creation_service.CreationError as exc:
        # 用一个临时 record 推 error 事件后结束
        return await _sse_error_response(
            404, f"项目 {project_id} 不存在: {exc}"
        )

    try:
        record = await registry.register(
            kind=KIND_CREATION,
            subject_id=project_id,
            title=str(project.get("project", {}).get("title") or f"项目 {project_id}"),
            meta={
                # 修复 #19: 跨章节互斥 — 同一个项目同时只允许跑 1 个生成任务
                "scope": f"project:{project_id}",
                "chapter_no": payload.chapter_no,
                "user_intent": payload.user_intent or "",
                "title_hint": payload.title or "",
                "force": payload.force,
                "max_revise": payload.max_revise,
                "score_threshold": payload.score_threshold,
            },
        )
    except RuntimeError as exc:
        # 同 scope 已有任务 — 保留 HTTP 409, 让前端能区分"重连已有任务"
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def _runner() -> None:
        final_state = "complete"
        try:
            async for ev in creation_service.generate_chapter_streaming(
                project_id,
                user_intent=payload.user_intent,
                chapter_no=payload.chapter_no,
                title=payload.title,
                force=payload.force,
                max_revise=payload.max_revise,
                score_threshold=payload.score_threshold,
            ):
                if record.should_cancel():
                    final_state = "cancelled"
                    await record.publish(
                        {"event": "cancelled", "chapter_no": payload.chapter_no}
                    )
                    break
                await record.publish(ev)
            if record.should_cancel():
                final_state = "cancelled"
        except Exception as exc:  # noqa: BLE001
            logger.exception("chapter generation crashed: %s", exc)
            await record.publish(
                {"event": "error", "message": f"生成异常: {creation_service.sanitize_error(exc)}"}
            )
            final_state = "error"
        finally:
            await registry.finish(record.task_id, final_state)

    # 启动应用作用域的后台任务
    asyncio.create_task(_runner())

    # 第一个事件携�?task_id, 方便前端持久�?
    await record.publish(
        {
            "event": "registered",
            "task_id": record.task_id,
            "project_id": project_id,
            "chapter_no": payload.chapter_no,
        }
    )

    async def event_stream() -> AsyncIterator[bytes]:
        rec = registry.get(record.task_id)
        if not rec:
            yield _sse_format("error", {"message": "任务不存在或已清理"})
            return
        try:
            async for ev in rec.subscribe():
                event_name = ev.get("event") or "message"
                yield _sse_format(event_name, ev)
        except asyncio.CancelledError:
            logger.info(
                "creation subscribe: client disconnected from %s", record.task_id
            )
            raise

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

