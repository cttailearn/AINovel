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

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from schemas import (
    AiChapterContentUpdate,
    AiChapterDetailResponse,
    AiChapterGenerateRequest,
    AiChapterListResponse,
    AiChapterSelectRequest,
    AiProjectCreate,
    AiProjectDetailResponse,
    AiProjectListResponse,
    AiProjectUpdate,
)
from services import creation_service

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
