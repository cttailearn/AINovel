"""Routes for the novel enrichment (小说加料) module.

All endpoints live under ``/api/enrichment``. The batch endpoint
(``POST /novels/{id}/batch``) is a Server-Sent Events stream; the
client can call ``GET /novels/{id}/progress`` to poll a snapshot of
per-chapter status (used by the right-side stats panel).

任务持久化
----------
v0.3.x 起, 跑批任务在 ``TaskRegistry`` 中以 *应用作用域* 的形式登记, 与
SSE 连接解耦:

* 启动:  在 registry 中注册一个 task, 把 registry 的 ``cancel_flag`` 传
  给业务 ``should_cancel``;
* 进度:  业务 ``on_event`` 直接 ``registry.publish``, 所有 SSE 订阅者都收
  得到; 也支持多个浏览器 tab 同时订阅同一任务;
* 断连:  客户端断开只关掉订阅协程, *不* 取消任务;
* 跨连接取消:  任意新连接 ``POST /api/tasks/{task_id}/cancel``;
* 跨连接重订阅:  任意新连接 ``GET /api/tasks/{task_id}/events``.

也就是说, 用户刷新/关 tab 之后再回来, 任务还在跑, 进度能续上.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

from config import ENRICHMENT_DEFAULT_CONCURRENCY
from database import get_novel_by_id, list_failed_chapter_ids
from schemas import (
    ENRICHMENT_STEPS,
    ApplyRequest,
    ApplyResponse,
    DiffResponse,
    EnrichmentBatchRequest,
    EnrichmentDetailResponse,
    EnrichmentProgressResponse,
    EnrichmentResetResponse,
    EnrichmentRunRequest,
    EnrichmentRunResponse,
    EnrichmentUpdateRequest,
    HistoryResponse,
    RevertRequest,
    RevertResponse,
)
from services import enrichment_service
from services import enrichment_suggestion_service
from services.task_registry import KIND_ENRICHMENT, registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/enrichment", tags=["Enrichment"])


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------


def _sse_format(event: str, data: Any) -> bytes:
    """Encode one Server-Sent Event payload.

    与 novels.py 的 _sse_format 一致: 单条 ``data:`` + JSON 字符串, 空行分隔.
    """
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _safe_filename(raw: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\r\n]", "_", str(raw or "")).strip()
    return name or "novel"


# ---------------------------------------------------------------------------
# 列表 / 详情
# ---------------------------------------------------------------------------


@router.get(
    "/novels/{novel_id}/progress",
    response_model=EnrichmentProgressResponse,
)
async def list_progress(novel_id: int):
    """返回该书每章的三态进度 + 整体统计."""
    try:
        data = await enrichment_service.list_progress(novel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return data


@router.get(
    "/chapters/{chapter_id}",
    response_model=EnrichmentDetailResponse,
)
async def get_detail(chapter_id: int):
    detail = await enrichment_service.get_detail(chapter_id)
    if not detail:
        raise HTTPException(status_code=404, detail="章节不存在")
    # v0.2 增量: 注入已应用 suggestion 信息
    try:
        applied = await enrichment_suggestion_service.get_current_applied_info(
            chapter_id
        )
        detail.update(applied)
    except Exception:  # noqa: BLE001
        # 即便读不到 applied 信息, 详情接口也不应失败
        logger.warning("get_current_applied_info failed for %s", chapter_id, exc_info=True)
    return detail


@router.put(
    "/chapters/{chapter_id}",
    response_model=EnrichmentDetailResponse,
)
async def update_chapter(
    chapter_id: int, payload: EnrichmentUpdateRequest
):
    """手动编辑 summary / recognition / rewrite_text / scene_tag / intent."""
    updated = await enrichment_service.update_manual(
        chapter_id,
        summary=payload.summary,
        rewrite_text=payload.rewrite_text,
        scene_tag=payload.scene_tag,
        recognition=payload.recognition,
        enrichment_intent=payload.enrichment_intent,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="章节不存在或未发生变更")
    detail = await enrichment_service.get_detail(chapter_id)
    if not detail:
        raise HTTPException(status_code=404, detail="章节不存在")
    try:
        applied = await enrichment_suggestion_service.get_current_applied_info(
            chapter_id
        )
        detail.update(applied)
    except Exception:  # noqa: BLE001
        pass
    return detail


# ---------------------------------------------------------------------------
# v0.2: diff / apply / revert / history
# ---------------------------------------------------------------------------


@router.get(
    "/chapters/{chapter_id}/diff",
    response_model=DiffResponse,
)
async def get_diff(chapter_id: int):
    """对比当前 chapters.content 与 chapter_enrichments.rewrite_text."""
    try:
        data = await enrichment_suggestion_service.diff_chapter(chapter_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return data


@router.post(
    "/chapters/{chapter_id}/apply",
    response_model=ApplyResponse,
)
async def apply_rewrite(chapter_id: int, payload: ApplyRequest):
    """把 rewrite_text 落库到 chapters.content, 并写一条 applied 记录."""
    try:
        result = await enrichment_suggestion_service.apply_chapter(
            chapter_id,
            rewrite_text=payload.rewrite_text,
            enrichment_intent=payload.enrichment_intent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post(
    "/chapters/{chapter_id}/revert",
    response_model=RevertResponse,
)
async def revert_rewrite(chapter_id: int, payload: RevertRequest):
    """回滚到指定 suggestion 或最近一次 superseded 版本."""
    try:
        result = await enrichment_suggestion_service.revert_chapter(
            chapter_id, target_suggestion_id=payload.target_suggestion_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get(
    "/chapters/{chapter_id}/history",
    response_model=HistoryResponse,
)
async def get_history(chapter_id: int):
    try:
        return await enrichment_suggestion_service.list_history(chapter_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# 单章单步
# ---------------------------------------------------------------------------


@router.post(
    "/chapters/{chapter_id}/summary",
    response_model=EnrichmentRunResponse,
)
async def run_summary(chapter_id: int, payload: EnrichmentRunRequest):
    try:
        return await enrichment_service.run_step(
            chapter_id, "summary",
            model_config_id=payload.model_config_id,
            prompt_key=payload.prompt_key,
            override_prompt=payload.override_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/chapters/{chapter_id}/recognition",
    response_model=EnrichmentRunResponse,
)
async def run_recognition(chapter_id: int, payload: EnrichmentRunRequest):
    try:
        return await enrichment_service.run_step(
            chapter_id, "recognition",
            model_config_id=payload.model_config_id,
            prompt_key=payload.prompt_key,
            override_prompt=payload.override_prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/chapters/{chapter_id}/rewrite",
    response_model=EnrichmentRunResponse,
)
async def run_rewrite(chapter_id: int, payload: EnrichmentRunRequest):
    try:
        return await enrichment_service.run_step(
            chapter_id, "rewrite",
            model_config_id=payload.model_config_id,
            prompt_key=payload.prompt_key,
            override_prompt=payload.override_prompt,
            general_rule=payload.general_rule,
            scene_rule=payload.scene_rule,
            enrichment_intent=payload.enrichment_intent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# 批量 (SSE 进度流)
# ---------------------------------------------------------------------------


@router.post("/novels/{novel_id}/batch")
async def run_batch(novel_id: int, payload: EnrichmentBatchRequest):
    """整本跑指定步骤, 通过 SSE 推送实时进度.

    SSE 事件类型 (event 字段):
        - ``start``        整批开始, 包含 step 列表 + total
        - ``step_start``   某个步骤开始
        - ``chapter_start`` 某个章节开始处理
        - ``chapter_done``  某个章节处理完 (含 success 标记)
        - ``skip``          skip_existing 命中, 跳过
        - ``cancelled``     用户取消
        - ``step_done``     某个步骤整体完成
        - ``complete``      整批完成
        - ``error``         异常 (整批级)
        - ``task_id``       首个 ``start`` 事件里携带, 前端持久化用来重连

    任务以应用作用域的 ``TaskRecord`` 形式跑在 ``TaskRegistry`` 中. SSE
    客户端断开不再取消任务; 想要取消, 调用
    ``POST /api/tasks/{task_id}/cancel``.
    """
    steps = [s for s in (payload.steps or []) if s in ENRICHMENT_STEPS]
    if not steps:
        raise HTTPException(status_code=400, detail="steps 至少需要包含 1 个有效步骤")

    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")

    # 同 (kind, subject_id) 同时只允许 1 个, 否则在 registry 层 raise.
    try:
        record = await registry.register(
            kind=KIND_ENRICHMENT,
            subject_id=novel_id,
            title=str(novel.get("title") or f"小说 {novel_id}"),
            meta={
                "model_config_id": payload.model_config_id,
                "steps": list(steps),
                "chapter_ids": list(payload.chapter_ids or []),
                "skip_existing": bool(payload.skip_existing),
                "concurrency": payload.concurrency or ENRICHMENT_DEFAULT_CONCURRENCY,
            },
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    async def _emit(payload_obj: Dict[str, Any]) -> None:
        # 业务事件直接 publish 到 registry, 所有 SSE 订阅者都收得到.
        try:
            await record.publish(payload_obj)
        except Exception:  # noqa: BLE001
            logger.warning("publish event failed", exc_info=True)

    async def _runner() -> None:
        final_state = "complete"
        try:
            await enrichment_service.run_batch(
                novel_id,
                model_config_id=payload.model_config_id,
                steps=steps,
                chapter_ids=payload.chapter_ids,
                concurrency=payload.concurrency or ENRICHMENT_DEFAULT_CONCURRENCY,
                skip_existing=payload.skip_existing,
                general_rule=payload.general_rule,
                scene_rule=payload.scene_rule,
                on_event=_emit,
                should_cancel=record.should_cancel,
            )
            if record.should_cancel():
                final_state = "cancelled"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Enrichment batch failed: %s", exc)
            await record.publish(
                {"event": "error", "message": str(exc)[:500]}
            )
            final_state = "error"
        finally:
            # 业务侧未必显式发 cancelled, 这里补一条, 便于前端明确知道结局.
            if final_state == "complete" and record.should_cancel():
                final_state = "cancelled"
            if final_state == "cancelled":
                await record.publish(
                    {
                        "event": "cancelled",
                        "novel_id": novel_id,
                        "step_progress": {},
                    }
                )
            await registry.finish(record.task_id, final_state)

    # 启动后台任务 — 注意: 这个 task 的生命周期属于应用作用域,
    # 不再绑定到任何 SSE 连接. 客户端断开只会关掉订阅, 不会取消 _runner.
    asyncio.create_task(_runner())

    # 立刻在 start 事件里补一个 task_id, 让前端能持久化用于重连.
    await record.publish(
        {
            "event": "registered",
            "task_id": record.task_id,
            "novel_id": novel_id,
        }
    )

    # 返回一个新的 SSE 流: 订阅 registry 中该任务的广播.
    return StreamingResponse(
        _enrichment_subscribe_stream(record.task_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _enrichment_subscribe_stream(task_id: str) -> AsyncIterator[bytes]:
    """将 registry 的事件广播转成 SSE 字节流.

    注意: 客户端断开时, 这个生成器会被取消, 但 registry 中的任务 *不* 受
    影响. 这正是"刷新页面 / 切换 tab 后任务不丢"的关键.
    """
    rec = registry.get(task_id)
    if not rec:
        yield _sse_format("error", {"message": "任务不存在或已清理"})
        return
    try:
        async for ev in rec.subscribe():
            event_name = ev.get("event") or "message"
            yield _sse_format(event_name, ev)
    except asyncio.CancelledError:
        # 客户端断开 — 记录日志, 重新抛出让 StreamingResponse 清理资源
        logger.info("enrichment subscribe: client disconnected from %s", task_id)
        raise


@router.post(
    "/novels/{novel_id}/retry-failed",
    response_model=EnrichmentProgressResponse,
)
async def retry_failed(novel_id: int):
    """列出所有失败章节, 标记为 pending, 前端可基于此列表触发 batch.

    接口只负责"找出来 + 重置状态", 不直接调 LLM, 避免与 SSE 重复触发.
    """
    from database import get_enrichment_by_chapter, upsert_enrichment

    try:
        # 确认小说存在
        await enrichment_service.list_progress(novel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    failed_ids = await list_failed_chapter_ids(novel_id)
    for cid in failed_ids:
        # 把所有失败步骤的 status 改回 pending, 清掉错误信息
        e = await get_enrichment_by_chapter(cid)
        if not e:
            continue
        kwargs: Dict[str, Any] = {}
        if e.get("summary_status") == "failed":
            kwargs["summary_status"] = "pending"
            kwargs["summary_error"] = None
        if e.get("recognition_status") == "failed":
            kwargs["recognition_status"] = "pending"
            kwargs["recognition_error"] = None
        if e.get("rewrite_status") == "failed":
            kwargs["rewrite_status"] = "pending"
            kwargs["rewrite_error"] = None
        if kwargs:
            await upsert_enrichment(
                novel_id=novel_id, chapter_id=cid, **kwargs
            )
    # 返回最新进度快照
    return await enrichment_service.list_progress(novel_id)


# ---------------------------------------------------------------------------
# 重置 / 导出
# ---------------------------------------------------------------------------


@router.post(
    "/novels/{novel_id}/reset",
    response_model=EnrichmentResetResponse,
)
async def reset(novel_id: int):
    try:
        info = await enrichment_service.reset_novel(novel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    deleted = int(info.get("deleted_enrichments") or 0)
    restored = int(info.get("restored_chapters") or 0)
    return EnrichmentResetResponse(
        novel_id=novel_id,
        deleted=deleted,
        message=f"已清空, 共还原 {restored} 章原始正文"
        if restored
        else "已清空加料结果",
    )


@router.get("/novels/{novel_id}/export")
async def export(novel_id: int):
    """把已加料的章节按 chapter_number 拼成 TXT 直接下载.

    文件名使用纯 ASCII (novel_{id}.enriched.txt), 标题在文件正文头部保留.
    这样 Content-Disposition 不需要走 RFC 5987, 老浏览器也能直接保存.
    """
    try:
        _filename, content = await enrichment_service.export_enriched_txt(novel_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    safe_ascii = f"novel_{novel_id}.enriched.txt"
    quoted = safe_ascii.replace("\\", "\\\\").replace('"', '\\"')
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{quoted}"',
        },
    )