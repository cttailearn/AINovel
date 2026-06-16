"""``services.task_registry`` 单元测试.

覆盖:
* 同 (kind, subject_id) 唯一性约束
* 多订阅者广播
* 客户端断开不影响任务
* 跨"连接"取消标志位
* 任务结束后的最终状态可在 ``snapshot`` 里看到
"""
from __future__ import annotations

import asyncio

import pytest

from services.task_registry import (
    KIND_CREATION,
    KIND_ENRICHMENT,
    TaskRecord,
    TaskRegistry,
)


@pytest.fixture
def fresh_registry():
    """每个测试拿一个干净的注册中心."""
    return TaskRegistry()


@pytest.mark.asyncio
async def test_register_and_lookup(fresh_registry):
    rec = await fresh_registry.register(
        kind=KIND_ENRICHMENT, subject_id=1, title="测试小说"
    )
    assert rec.task_id
    assert fresh_registry.get(rec.task_id) is rec
    assert fresh_registry.get_active(kind=KIND_ENRICHMENT, subject_id=1) == [rec]


@pytest.mark.asyncio
async def test_duplicate_subject_blocked(fresh_registry):
    await fresh_registry.register(
        kind=KIND_ENRICHMENT, subject_id=1, title="T1"
    )
    with pytest.raises(RuntimeError):
        await fresh_registry.register(
            kind=KIND_ENRICHMENT, subject_id=1, title="T1 again"
        )


@pytest.mark.asyncio
async def test_different_subjects_coexist(fresh_registry):
    r1 = await fresh_registry.register(
        kind=KIND_ENRICHMENT, subject_id=1, title="A"
    )
    r2 = await fresh_registry.register(
        kind=KIND_ENRICHMENT, subject_id=2, title="B"
    )
    assert r1.task_id != r2.task_id
    assert len(fresh_registry.get_active()) == 2


@pytest.mark.asyncio
async def test_broadcast_to_multiple_subscribers(fresh_registry):
    rec = await fresh_registry.register(
        kind=KIND_CREATION, subject_id=10, title="X"
    )

    received_a = []
    received_b = []

    async def consume(name, sink):
        async for ev in rec.subscribe():
            sink.append(ev.get("event"))
            if ev.get("event") == "__end__":
                break

    s1 = asyncio.create_task(consume("A", received_a))
    s2 = asyncio.create_task(consume("B", received_b))
    await asyncio.sleep(0.05)  # 等两个订阅者挂上

    for i in range(3):
        await rec.publish({"event": "tick", "n": i})
    await rec.finish("complete")
    await asyncio.gather(s1, s2)

    # 注意: ``__end__`` 是内部哨兵, 不会 yield 给外部消费方;
    # 但 ``finish`` 同步将 done=True, 拿到 done 之后再次订阅会立刻返回.
    # 3 个 tick 事件两个订阅方都收到.
    assert received_a == ["tick", "tick", "tick"]
    assert received_b == ["tick", "tick", "tick"]
    assert rec.done is True
    assert rec.final_state == "complete"


@pytest.mark.asyncio
async def test_subscriber_disconnect_does_not_kill_task(fresh_registry):
    """订阅协程被取消时, 任务本身不能挂掉."""
    rec = await fresh_registry.register(
        kind=KIND_ENRICHMENT, subject_id=99, title="长任务"
    )

    # 拉起一个订阅 generator, 但立刻取消
    gen = rec.subscribe()

    async def consume_one():
        try:
            await gen.__anext__()
        except asyncio.CancelledError:
            # subscribe 协程被取消, 应当清理订阅者
            raise
        except StopAsyncIteration:
            return

    t = asyncio.create_task(consume_one())
    await asyncio.sleep(0.02)  # 让它把自己加进 _subscribers
    assert len(rec._subscribers) == 1

    t.cancel()
    try:
        await t
    except (asyncio.CancelledError, Exception):
        pass

    # 任务本身应该还在, 可以继续 publish
    assert fresh_registry.get(rec.task_id) is not None
    assert not rec.done
    assert len(rec._subscribers) == 0  # 订阅者被清理


@pytest.mark.asyncio
async def test_cancel_flag_via_registry(fresh_registry):
    rec = await fresh_registry.register(
        kind=KIND_CREATION, subject_id=7, title="可取消"
    )
    assert not rec.should_cancel()
    ok = await fresh_registry.request_cancel(rec.task_id)
    assert ok is True
    assert rec.should_cancel() is True
    # 已取消的任务再 cancel 返回 False
    await rec.finish("cancelled")
    ok = await fresh_registry.request_cancel(rec.task_id)
    assert ok is False


@pytest.mark.asyncio
async def test_finish_persists_final_state(fresh_registry):
    rec = await fresh_registry.register(
        kind=KIND_ENRICHMENT, subject_id=42, title="结束态"
    )
    await rec.finish("error")
    snap = rec.snapshot()
    assert snap["done"] is True
    assert snap["final_state"] == "error"

    # 已结束的任务重新订阅会立刻拿到 final_state 事件 (replay).
    replayed = []
    async for ev in rec.subscribe():
        replayed.append(ev)
    assert len(replayed) == 1
    assert replayed[0]["event"] == "error"


@pytest.mark.asyncio
async def test_publish_drops_slow_subscriber(fresh_registry):
    """满队列的慢消费者会被断开, 不影响后续 publish 阻塞其他订阅者.

    直接构造一个 _Subscriber, 把它的 queue 塞满, 模拟"慢消费者" ——
    不通过 async generator 接口, 避免悬挂.
    """
    from services.task_registry import _Subscriber

    rec = await fresh_registry.register(
        kind=KIND_CREATION, subject_id=5, title="混合"
    )

    slow = _Subscriber()
    rec._subscribers.append(slow)
    # 把慢消费者队列塞满
    for i in range(slow.queue.maxsize):
        await slow.queue.put({"event": "stale", "n": i})

    # 后续 publish 应该跳过这个满队列的订阅者, 不抛 QueueFull
    for i in range(5):
        await rec.publish({"event": "live", "n": i})

    # 慢消费者应被断开 (closed=True) 并从列表移除
    assert slow.closed is True
    assert slow not in rec._subscribers


@pytest.mark.asyncio
async def test_finish_marks_done_even_without_subscribers(fresh_registry):
    """没人在订阅时, finish 也不应抛错."""
    rec = await fresh_registry.register(
        kind=KIND_CREATION, subject_id=11, title="无人"
    )
    await rec.finish("complete")
    snap = rec.snapshot()
    assert snap["done"] is True
    assert snap["final_state"] == "complete"


# 修复 #19: scope 维度互斥
@pytest.mark.asyncio
async def test_scope_blocks_same_scope_concurrent_tasks(fresh_registry):
    """同一 scope 同时只允许 1 个任务, 即使 subject_id 不同."""
    rec_a = await fresh_registry.register(
        kind=KIND_CREATION,
        subject_id=1,
        title="第 1 章生成",
        meta={"scope": "project:42"},
    )
    with pytest.raises(RuntimeError) as exc:
        await fresh_registry.register(
            kind=KIND_CREATION,
            subject_id=2,  # 不同 subject_id 也阻挡
            title="第 2 章生成",
            meta={"scope": "project:42"},
        )
    assert "scope=project:42" in str(exc.value)
    # 让第一个结束, 第二个就能注册
    await rec_a.finish("complete")
    rec_b = await fresh_registry.register(
        kind=KIND_CREATION,
        subject_id=2,
        title="第 2 章生成",
        meta={"scope": "project:42"},
    )
    assert rec_b.task_id != rec_a.task_id


@pytest.mark.asyncio
async def test_scope_different_scope_coexists(fresh_registry):
    """不同 scope 可以同时跑 (一个加料, 一个生成)."""
    r1 = await fresh_registry.register(
        kind=KIND_ENRICHMENT,
        subject_id=1,
        title="加料",
        meta={"scope": "novel:1"},
    )
    r2 = await fresh_registry.register(
        kind=KIND_CREATION,
        subject_id=2,
        title="生成",
        meta={"scope": "project:2"},
    )
    assert r1.task_id != r2.task_id
    assert len(fresh_registry.get_active()) == 2


@pytest.mark.asyncio
async def test_scope_legacy_subject_id_dimension_still_works(fresh_registry):
    """不带 scope 时, 退化到 (kind, subject_id) 旧行为."""
    rec_a = await fresh_registry.register(
        kind=KIND_CREATION, subject_id=5, title="A"
    )
    with pytest.raises(RuntimeError):
        await fresh_registry.register(
            kind=KIND_CREATION, subject_id=5, title="A again"
        )
    # 不同 subject_id 不阻挡
    rec_b = await fresh_registry.register(
        kind=KIND_CREATION, subject_id=6, title="B"
    )
    assert rec_b.task_id != rec_a.task_id
