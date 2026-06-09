"""Tasks router — 长任务管理 (活跃查询 / 跨连接取消 / 重新订阅 SSE).

这个路由独立于 enrichment / creation 业务路由, 专门负责"任务注册中心"
(``services.task_registry.registry``) 的 HTTP 接口.

设计要点
--------

* **同 (kind, subject_id) 唯一**:  避免前端误启动并发任务导致资源争用.
* **多个订阅者可同时存在**: 多个浏览器 tab/窗口同时连进来都能收到事件.
* **订阅不影响任务生命周期**:  SSE 断开 = 取消订阅, 任务继续跑.
* **跨连接取消**:  从任何新连接 (例如刷新后) 都能 ``POST /tasks/{id}/cancel``,
   后端通过 ``cancel_flag`` 让业务层 ``should_cancel()`` 读到 True.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from services.task_registry import (
    KIND_CREATION,
    KIND_ENRICHMENT,
    SENTINEL_END,
    registry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


def _sse_format(event: str, data: Any) -> bytes:
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


# ---------------------------------------------------------------------------
# 查询活跃任务
# ---------------------------------------------------------------------------


@router.get("/active")
async def list_active_tasks(
    kind: Optional[str] = Query(None, description="enrichment / creation"),
    subject_id: Optional[int] = Query(None),
    include_recent: bool = Query(
        False, description="为 true 时同时返回最近结束的 (用于恢复 banner 终态)"
    ),
):
    """列出当前活跃的任务, 可按 kind / subject_id 过滤.

    前端刷新后调用此端点, 若返回的列表里有 enrichment/creation 任务,
    就可以重新挂 SSE 订阅 — 不需要用户再次手动触发.
    """
    active = registry.get_active(kind=kind, subject_id=subject_id)
    payload: Dict[str, Any] = {
        "active": [r.snapshot() for r in active],
    }
    if include_recent:
        recent = registry.get_recent(
            kind=kind, subject_id=subject_id, include_done=True
        )
        payload["recent"] = [r.snapshot() for r in recent]
    return payload


@router.get("/{task_id}")
async def get_task(task_id: str):
    """获取单个任务的元信息 (主要用于重连前的存在性检查)."""
    rec = registry.get(task_id)
    if not rec:
        raise HTTPException(status_code=404, detail="任务不存在或已清理")
    return rec.snapshot()


# ---------------------------------------------------------------------------
# 取消 (跨连接)
# ---------------------------------------------------------------------------


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    """请求取消一个正在运行的任务. 业务层会读 cancel_flag 自然结束.

    注意: 此端点 *不* 强制杀掉协程, 只是设置标志位. enrichment_service /
    creation_service 在合适的检查点 (每个 chapter / step 之间) 会停下并
    publish 一条 ``cancelled`` 事件, 然后 ``task_registry.finish`` 标记完成.
    这样可以保证数据库的 enrichment 状态被正确回写, 不会出现"半截废"状态.
    """
    rec = registry.get(task_id)
    if not rec:
        raise HTTPException(status_code=404, detail="任务不存在或已清理")
    if rec.done:
        return {"ok": True, "already_done": True, "final_state": rec.final_state}
    await registry.request_cancel(task_id)
    return {"ok": True, "task_id": task_id}


# ---------------------------------------------------------------------------
# 订阅 (SSE 重连)
# ---------------------------------------------------------------------------


@router.get("/{task_id}/events")
async def subscribe_task(
    task_id: str,
    replay: bool = Query(
        True,
        description="若任务已结束, 是否重放终态事件, 让前端拿到最终结果",
    ),
):
    """订阅一个任务的实时事件流 (SSE).

    业务方在刷新页面后用此端点重连, 不需要重新跑业务逻辑. 若任务已结束,
    视 ``replay`` 参数决定是否下发一条终态事件.
    """
    rec = registry.get(task_id)
    if not rec:
        raise HTTPException(status_code=404, detail="任务不存在或已清理")

    if rec.done:
        # 已经结束: 直接以一次性响应返回终态
        if replay and rec.final_state:
            payload = json.dumps(
                {
                    "event": rec.final_state,
                    "data": {"task_id": rec.task_id, "replayed": True},
                },
                ensure_ascii=False,
            )
            return StreamingResponse(
                iter([f"data: {payload}\n\n".encode("utf-8")]),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        raise HTTPException(status_code=410, detail="任务已结束")

    async def event_stream() -> AsyncIterator[bytes]:
        # 派发一个 "subscribe" 事件, 让前端知道连接建立成功
        yield _sse_format(
            "subscribed",
            {
                "task_id": rec.task_id,
                "kind": rec.kind,
                "subject_id": rec.subject_id,
                "title": rec.title,
                "meta": rec.meta,
            },
        )
        try:
            async for ev in rec.subscribe():
                # ev 形如 {"event": "start", "data": {...}, "step_progress": ...}
                # 业务事件里 event 是字符串, 我们把它原样转 SSE
                event_name = ev.get("event") or "message"
                # 业务事件整体作为 data, 不拆开
                yield _sse_format(event_name, ev)
        except asyncio.CancelledError:
            # 客户端断开 — 订阅协程被取消, 但任务本体不受影响
            logger.info("subscribe_task: client disconnected from %s", task_id)
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
