"""``_generate_chapter_streaming_single`` 单元测试.

不依赖 LLM, 用 monkeypatch 替换 Planner / Writer / Critic 三个 Agent
的 ``run`` 方法, 验证:
  1. 流水线跑通一遍并写出 1 个 variant
  2. Critic 不达标时会回到 Planner + Writer 重做, 直到通过或达到 max_revise
  3. 终态 event ``done`` 携带 attempts / final_score / accepted
  4. 章节状态从 ``generating`` 变为 ``selected`` (不是 ``generated``)

注意: conftest 会在每个 test 临时切换 DATABASE_PATH, 所以测试要自己
``create_ai_project`` 一个项目.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, AsyncIterator, Dict, List

import pytest


# ---------------------------------------------------------------------------
# Stub dataclass 替身 (PlannerDirection / PlannerOutput / WriterOutput / CriticOutput)
# ---------------------------------------------------------------------------


class _StubDirection:
    def __init__(self, **kw: Any) -> None:
        self.index = kw.get("index", 0)
        self.title = kw.get("title", "方向0")
        self.synopsis = kw.get("synopsis", "概述")
        self.focus = kw.get("focus", "动作")
        self.key_entities = kw.get("key_entities", [])
        self.foreshadowing = kw.get("foreshadowing", [])
        self.tone = kw.get("tone", "紧张")
        self.hard_constraints = kw.get("hard_constraints", [])
        self.key_event = kw.get("key_event", "关键事件")
        self.themes = kw.get("themes", [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "synopsis": self.synopsis,
            "focus": self.focus,
            "key_entities": self.key_entities,
            "foreshadowing": self.foreshadowing,
            "tone": self.tone,
            "hard_constraints": self.hard_constraints,
            "key_event": self.key_event,
            "themes": self.themes,
        }


class _StubWriterOutput:
    def __init__(self, content: str) -> None:
        self.content = content
        self.focus_summary = "summary"
        self.raw = content


class _StubCriticOutput:
    def __init__(self, overall: float, **kw: Any) -> None:
        self.scores = kw.get("scores", {"logic": overall, "vivid": overall})
        self.overall = overall
        self.strengths = kw.get("strengths", [])
        self.issues = kw.get("issues", [])
        self.modifications = kw.get("modifications", [])
        self.kg_conflicts = kw.get("kg_conflicts", [])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "overall": self.overall,
            "strengths": self.strengths,
            "issues": self.issues,
            "modifications": self.modifications,
            "kg_conflicts": self.kg_conflicts,
        }


async def _make_test_project(database) -> int:
    """在 conftest 临时库里新建一个项目 + 一份可用的 chat 模型配置."""
    # 1. 一份启用的 chat 模型配置, _resolve_model_cfg 才能拿到
    await database.save_config(
        name="test-chat",
        provider="test",
        model_url="http://test",
        api_key="test",
        model_name="test-model",
        enabled=1,
        capability="chat",
    )
    # 2. 项目指向该模型
    return await database.create_ai_project(
        title="测试项目",
        genre="测试",
        worldview="(测试用)",
        outline="(测试用)",
        initial_concepts=[{"name": "主角", "attributes": {"性格": "测试"}}],
        style_pref={"视角": "第一人称"},
        model_id=None,
    )


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_format_critic_feedback_contains_issues_and_score():
    from services.creation_service import _format_critic_feedback

    co = _StubCriticOutput(
        5.5,
        issues=["主角 OOC", "情节与世界观冲突"],
        modifications=["开头再紧凑些"],
        kg_conflicts=["未提及承诺的次要角色"],
    )
    text = _format_critic_feedback(co)
    assert "5.5/10" in text
    assert "主角 OOC" in text
    assert "开头再紧凑些" in text
    assert "次要角色" in text


@pytest.mark.asyncio
async def test_single_mode_first_pass(monkeypatch):
    """一次就通过 (Critic overall >= threshold) — 只跑 1 轮, 1 个 variant."""
    import database
    from services import creation_agents, creation_service

    project_id = await _make_test_project(database)

    call_counts = {"planner": 0, "writer": 0, "critic": 0}

    async def fake_planner_run(self, **kwargs):
        call_counts["planner"] += 1
        out = type("PlannerOutput", (), {})()
        out.directions = [_StubDirection(title="方向0")]
        out.raw = "{}"
        return out

    async def fake_writer_run(self, **kwargs):
        call_counts["writer"] += 1
        return _StubWriterOutput(f"内容{'-' * 30}")

    async def fake_critic_run(self, **kwargs):
        call_counts["critic"] += 1
        return _StubCriticOutput(8.5)

    monkeypatch.setattr(creation_agents.PlannerAgent, "run", fake_planner_run)
    monkeypatch.setattr(creation_agents.WriterAgent, "run", fake_writer_run)
    monkeypatch.setattr(creation_agents.CriticAgent, "run", fake_critic_run)

    events: List[Dict[str, Any]] = []
    async for ev in creation_service._generate_chapter_streaming_single(
        project_id, user_intent="测试", chapter_no=None, title="单测章",
        max_revise=2, score_threshold=7.0,
    ):
        events.append(ev)
        if ev.get("event") == "error":
            pytest.fail(f"收到 error 事件: {ev}")

    done_events = [e for e in events if e.get("event") == "done"]
    assert done_events, f"没有收到 done 事件, 实际事件: {[e.get('event') for e in events]}"
    done = done_events[-1]
    assert done["accepted"] is True
    assert done["final_score"] == 8.5
    assert done["attempts"] == 1
    assert done["variant_id"]

    assert call_counts == {"planner": 1, "writer": 1, "critic": 1}
    assert not any(e.get("event") == "critic_rejected" for e in events)
    assert not any(e.get("event") == "revision_start" for e in events)


@pytest.mark.asyncio
async def test_single_mode_revise_loop(monkeypatch):
    """Critic 首轮 4.0 < 7.0, 触发重试, 第二轮 8.5 通过 — 共 2 轮."""
    import database
    from services import creation_agents, creation_service

    project_id = await _make_test_project(database)

    scores = iter([4.0, 8.5])
    call_counts = {"planner": 0, "writer": 0, "critic": 0}

    async def fake_planner_run(self, **kwargs):
        call_counts["planner"] += 1
        out = type("PlannerOutput", (), {})()
        out.directions = [_StubDirection(title=f"方向0-{call_counts['planner']}")]
        out.raw = "{}"
        return out

    async def fake_writer_run(self, **kwargs):
        call_counts["writer"] += 1
        return _StubWriterOutput(f"内容{'-' * 30}")

    async def fake_critic_run(self, **kwargs):
        call_counts["critic"] += 1
        score = next(scores)
        return _StubCriticOutput(
            score,
            issues=["首轮问题点"] if score < 7.0 else [],
            modifications=["首轮改进"] if score < 7.0 else [],
        )

    monkeypatch.setattr(creation_agents.PlannerAgent, "run", fake_planner_run)
    monkeypatch.setattr(creation_agents.WriterAgent, "run", fake_writer_run)
    monkeypatch.setattr(creation_agents.CriticAgent, "run", fake_critic_run)

    events: List[Dict[str, Any]] = []
    async for ev in creation_service._generate_chapter_streaming_single(
        project_id, user_intent="测试", chapter_no=None, title="重试章",
        max_revise=2, score_threshold=7.0,
    ):
        events.append(ev)
        if ev.get("event") == "error":
            pytest.fail(f"收到 error 事件: {ev}")

    done = [e for e in events if e.get("event") == "done"][-1]
    assert done["accepted"] is True
    assert done["final_score"] == 8.5
    assert done["attempts"] == 2

    assert any(e.get("event") == "critic_rejected" for e in events)
    assert any(e.get("event") == "revision_start" for e in events)
    assert call_counts == {"planner": 2, "writer": 2, "critic": 2}


@pytest.mark.asyncio
async def test_single_mode_max_revise_exhausted(monkeypatch):
    """max_revise=1, Critic 一直 4.0, 应当跑 2 轮后收尾 (accepted=False)."""
    import database
    from services import creation_agents, creation_service

    project_id = await _make_test_project(database)

    async def fake_planner_run(self, **kwargs):
        out = type("PlannerOutput", (), {})()
        out.directions = [_StubDirection(title="方向0")]
        out.raw = "{}"
        return out

    async def fake_writer_run(self, **kwargs):
        return _StubWriterOutput("内容" * 20)

    async def fake_critic_run(self, **kwargs):
        return _StubCriticOutput(4.0, issues=["问题"])

    monkeypatch.setattr(creation_agents.PlannerAgent, "run", fake_planner_run)
    monkeypatch.setattr(creation_agents.WriterAgent, "run", fake_writer_run)
    monkeypatch.setattr(creation_agents.CriticAgent, "run", fake_critic_run)

    events: List[Dict[str, Any]] = []
    async for ev in creation_service._generate_chapter_streaming_single(
        project_id, user_intent="测试", chapter_no=None, title="强重试章",
        max_revise=1, score_threshold=7.0,
    ):
        events.append(ev)
        if ev.get("event") == "error":
            pytest.fail(f"收到 error 事件: {ev}")

    done = [e for e in events if e.get("event") == "done"][-1]
    assert done["accepted"] is False
    assert done["final_score"] == 4.0
    assert done["attempts"] == 2  # 1 首次 + 1 重试
    # 第二轮 (最后一轮) 不会再发 critic_rejected, 因为没有下一轮要重做
    rejected = [e for e in events if e.get("event") == "critic_rejected"]
    assert len(rejected) == 1


@pytest.mark.asyncio
async def test_single_mode_writes_chapter_with_selected_status(monkeypatch):
    """收尾后, 数据库中章节 status='selected', selected_variant_id 已设, 1 个 variant."""
    import database
    from services import creation_agents, creation_service

    project_id = await _make_test_project(database)

    async def fake_planner_run(self, **kwargs):
        out = type("PlannerOutput", (), {})()
        out.directions = [_StubDirection(title="方向0")]
        out.raw = "{}"
        return out

    async def fake_writer_run(self, **kwargs):
        return _StubWriterOutput("正文内容" * 10)

    async def fake_critic_run(self, **kwargs):
        return _StubCriticOutput(9.0)

    monkeypatch.setattr(creation_agents.PlannerAgent, "run", fake_planner_run)
    monkeypatch.setattr(creation_agents.WriterAgent, "run", fake_writer_run)
    monkeypatch.setattr(creation_agents.CriticAgent, "run", fake_critic_run)

    done = None
    async for ev in creation_service._generate_chapter_streaming_single(
        project_id, user_intent="测试", chapter_no=None, title="DB验证章",
        max_revise=1, score_threshold=7.0,
    ):
        if ev.get("event") == "done":
            done = ev
        elif ev.get("event") == "error":
            pytest.fail(f"收到 error 事件: {ev}")

    assert done
    chapter_id = done["chapter_id"]
    chapter = await database.get_ai_chapter(chapter_id)
    assert chapter["status"] == "selected"
    assert chapter["selected_variant_id"] is not None
    assert chapter["final_content"]
    variants = await database.list_ai_variants(chapter_id)
    assert len(variants) == 1
    assert variants[0]["id"] == chapter["selected_variant_id"]
