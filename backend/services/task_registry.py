"""应用作用域的长任务注册中心.

背景
----
原先加料 / 创作模块的 SSE 实现, 把执行协程 (asyncio task) 放在 *请求作用域*,
SSE 连接断开 (前端刷新、关闭 tab、网络波动) 时 ``finally`` 会立刻把任务取消.
结果是: 哪怕数据库里 ``chapter_enrichments.summary_status='running'`` 还在,
后端已经不再推任何事件. 用户刷新后看到的 "进度" 永远停在断开那一瞬间.

本模块把任务的生命周期从 SSE 连接解耦:

* 任务在 *应用作用域* 中跑, 通过 ``TaskRegistry.register`` 登记;
* 多个 SSE 客户端可以同时订阅同一个任务 (broadcast);
* 客户端断开只断开订阅, 不会取消任务;
* 提供 ``cancel`` 端点, 允许从另一个 HTTP 连接发起取消;
* 提供 ``active`` 端点, 允许前端重新挂载时询问 "现在还有哪些任务在跑".

广播机制
--------
每个任务内部维护一个订阅者列表 (每个订阅者持有一个自己的
``asyncio.Queue``). 发布事件时向 *每个* 订阅者队列各投递一份, 任意一个
订阅者断开 (队列被取消) 都不会影响其他订阅者与任务本身.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, List, Optional

from services.metrics_service import record_task_finished

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 任务模型
# ---------------------------------------------------------------------------


# 任务种类 (用于 /tasks/active?kind=... 查询)
KIND_ENRICHMENT = "enrichment"
KIND_CREATION = "creation"

# 终止事件哨兵 — 订阅者见到它就关闭流, 不会再有新事件
SENTINEL_END = "__end__"


class _Subscriber:
    """一个 SSE 客户端的订阅句柄.

    内部是一个 ``asyncio.Queue``, 业务事件由 ``TaskRecord.publish`` 投递;
    断开时把 ``closed`` 置 True, ``publish`` 会跳过该订阅者.
    """

    __slots__ = ("queue", "closed")

    def __init__(self) -> None:
        # 队列设大一些, 防止发布方阻塞; 满了说明订阅方消费太慢
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
        self.closed: bool = False


@dataclass
class TaskRecord:
    """一个长任务的全部运行时信息.

    字段
    ----
    task_id:  唯一 ID, 前端持久化到 localStorage 用来重连
    kind:     enrichment / creation
    subject_id:  对应 novel_id / project_id
    title:    人类可读的标题 (用于前端展示, 比如 "《xxx》加料中")
    meta:     任意附加元数据 (例如模型 ID, 步骤列表), 前端在重连时拿到能
              重建 banner
    cancel_flag: 业务层 ``should_cancel`` 闭包读这个标志
    created_at: 用于 UI 显示已运行时长
    done:     任务自然结束后置 True, 之后只允许查状态不允许再 publish
    """

    task_id: str
    kind: str
    subject_id: int
    title: str
    cancel_flag: Dict[str, bool] = field(default_factory=lambda: {"cancelled": False})
    meta: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    done: bool = False
    final_state: Optional[str] = None
    # 私有: 订阅者列表 (在 __post_init__ 之后初始化)
    _subscribers: List[_Subscriber] = field(default_factory=list)
    _sub_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def should_cancel(self) -> bool:
        return bool(self.cancel_flag["cancelled"])

    def request_cancel(self) -> None:
        self.cancel_flag["cancelled"] = True

    async def publish(self, event: Dict[str, Any]) -> None:
        """向所有 *当前* 订阅者投递一条事件.

        已关闭的订阅者会被静默跳过 (移除). 慢消费者暂时用 ``put_nowait`` 避免
        一个订阅方拖垮整个广播.
        """
        if self.done:
            return
        async with self._sub_lock:
            alive: List[_Subscriber] = []
            for sub in self._subscribers:
                if sub.closed:
                    continue
                try:
                    sub.queue.put_nowait(event)
                except asyncio.QueueFull:
                    # 慢消费者: 断开它, 避免阻塞整个广播
                    logger.warning(
                        "TaskRegistry: slow subscriber on %s, closing", self.task_id
                    )
                    sub.closed = True
                    continue
                alive.append(sub)
            self._subscribers = alive

    async def finish(self, final_state: str) -> None:
        """标记任务自然结束并广播终止哨兵.

        调用之后 ``publish`` 静默丢弃, 不会抛错. 已存在的订阅者会读到
        ``SENTINEL_END`` 关闭流.
        """
        if self.done:
            return
        self.done = True
        self.final_state = final_state
        # 直接 push 给当前所有订阅者 — 不通过 publish (避免 done 短路)
        async with self._sub_lock:
            for sub in self._subscribers:
                if sub.closed:
                    continue
                try:
                    sub.queue.put_nowait(
                        {"event": SENTINEL_END, "final_state": final_state}
                    )
                except asyncio.QueueFull:
                    sub.closed = True

    async def subscribe(self) -> AsyncIterator[Dict[str, Any]]:
        """订阅任务事件. 每个调用方获得一个独立队列, 互不影响.

        若任务已结束, 视 ``__aenter__`` 时机的 final_state 决定是否补发一条
        终态事件; 这里保持简单 — 一次性返回终态或空.
        """
        if self.done:
            if self.final_state:
                yield {
                    "event": self.final_state,
                    "data": {
                        "task_id": self.task_id,
                        "replayed": True,
                    },
                }
            return

        sub = _Subscriber()
        async with self._sub_lock:
            self._subscribers.append(sub)

        try:
            while True:
                ev = await sub.queue.get()
                if ev.get("event") == SENTINEL_END:
                    break
                yield ev
        except asyncio.CancelledError:
            # 客户端断开 — 把订阅标记为关闭, 后续 publish 会跳过它
            sub.closed = True
            async with self._sub_lock:
                if sub in self._subscribers:
                    self._subscribers.remove(sub)
            raise
        finally:
            sub.closed = True
            async with self._sub_lock:
                if sub in self._subscribers:
                    self._subscribers.remove(sub)

    def snapshot(self) -> Dict[str, Any]:
        """用于 ``/tasks/active`` 端点返回的 JSON 摘要."""
        return {
            "task_id": self.task_id,
            "kind": self.kind,
            "subject_id": self.subject_id,
            "title": self.title,
            "meta": self.meta,
            "created_at": self.created_at,
            "done": self.done,
            "final_state": self.final_state,
        }


# ---------------------------------------------------------------------------
# 注册中心 (单例, 模块级)
# ---------------------------------------------------------------------------


class TaskRegistry:
    """全局任务注册表. 模块级单例, 简单 dict 实现."""

    def __init__(self) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = asyncio.Lock()

    # ----- 任务生命周期 -----

    async def register(
        self,
        *,
        kind: str,
        subject_id: int,
        title: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> TaskRecord:
        """注册一条新任务. 同 (kind, subject_id) 同时只允许一个, 否则报错.

        修复 #19: 额外支持 ``meta["scope"]`` 字段. 当 meta 含 scope 时, 互斥
        维度从 (kind, subject_id) 变为 (kind, scope). 例如 kind=creation
        scope=project:<id> 表示"同一个项目下同时只能跑一个生成任务, 不管
        是第几章". 这避免了用户连点多个章节的「生成」按钮导致并发跑 10
        个 LLM 任务把 token 打爆.

        之所以唯一: banner 一次只显示一条, 多条会冲突. 业务层在启动前应
        调用 ``get_active`` 检查是否已有活跃任务, 让用户先取消/结束.
        """
        scope = (meta or {}).get("scope") or f"{kind}:{subject_id}"
        async with self._lock:
            for existing in self._tasks.values():
                if existing.done:
                    continue
                existing_scope = (existing.meta or {}).get("scope") or (
                    f"{existing.kind}:{existing.subject_id}"
                )
                if existing_scope == scope:
                    raise RuntimeError(
                        f"scope={scope} 已有运行中的任务 "
                        f"({existing.task_id}); 请先取消或等待其完成."
                    )
            record = TaskRecord(
                task_id=uuid.uuid4().hex,
                kind=kind,
                subject_id=subject_id,
                title=title,
                meta=dict(meta or {}),
            )
            self._tasks[record.task_id] = record
            logger.info(
                "TaskRegistry: registered %s task_id=%s subject_id=%s scope=%s title=%s",
                kind, record.task_id, subject_id, scope, title,
            )
            return record

    async def finish(self, task_id: str, final_state: str) -> None:
        rec = self._tasks.get(task_id)
        if not rec:
            return
        await rec.finish(final_state)
        record_task_finished(rec.kind, final_state)
        # 保留 record 一段时间便于前端查询终态; 用一个轻量延迟任务清理.
        asyncio.create_task(self._gc_later(task_id, delay=300.0))

    async def _gc_later(self, task_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        self._tasks.pop(task_id, None)

    # ----- 查询 -----

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self._tasks.get(task_id)

    def get_active(
        self, *, kind: Optional[str] = None, subject_id: Optional[int] = None
    ) -> List[TaskRecord]:
        out: List[TaskRecord] = []
        for rec in self._tasks.values():
            if rec.done:
                continue
            if kind and rec.kind != kind:
                continue
            if subject_id is not None and rec.subject_id != subject_id:
                continue
            out.append(rec)
        return out

    def get_recent(
        self,
        *,
        kind: Optional[str] = None,
        subject_id: Optional[int] = None,
        include_done: bool = True,
        limit: int = 20,
    ) -> List[TaskRecord]:
        """返回最近的任务 (含已结束), 用于前端恢复 banner 终态."""
        out: List[TaskRecord] = []
        for rec in self._tasks.values():
            if kind and rec.kind != kind:
                continue
            if subject_id is not None and rec.subject_id != subject_id:
                continue
            if not include_done and rec.done:
                continue
            out.append(rec)
        out.sort(key=lambda r: r.created_at, reverse=True)
        return out[:limit]

    def all_active_snapshot(self) -> List[Dict[str, Any]]:
        return [r.snapshot() for r in self.get_active()]

    # ----- 取消 -----

    async def request_cancel(self, task_id: str) -> bool:
        rec = self._tasks.get(task_id)
        if not rec or rec.done:
            return False
        rec.request_cancel()
        logger.info(
            "TaskRegistry: cancel requested for %s (task_id=%s)", rec.kind, task_id,
        )
        return True


# 单例
registry = TaskRegistry()
