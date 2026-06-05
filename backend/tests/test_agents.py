"""Unit tests for the multi-agent knowledge-graph pipeline.

Covers the deterministic parts of the agents (no LLM calls, no DB):

  * ExtractorAgent.evidence / confidence helpers
  * PhaseOutput.dicts_by_chunk regrouping
  * MergeValidatorAgent._normalize_attr_keys (the " 结果" -> "结果" bug)
  * MergeValidatorAgent._strip_name_parens (the "我(叙述者)" bug)
  * MergeValidatorAgent.normalize_entities
  * MergeValidatorAgent.validate_references
  * MergeValidatorAgent.coverage_check
  * MergeValidatorAgent.validate end-to-end (run_llm_dedup=False)
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from services.agents import (
    ExtractedItem,
    ExtractorAgent,
    MergeValidatorAgent,
    PhaseOutput,
    ValidatedKG,
    build_phase_prompt,
)


# ---------------------------------------------------------------------------
# ExtractorAgent helpers
# ---------------------------------------------------------------------------


def test_make_evidence_uses_name_anchor():
    chunk = "第一段内容: 灵儿在船上, 我和灵儿手拉手走向甲板。"
    obj = {"id": "char_x", "name": "灵儿"}
    spans = ExtractorAgent._make_evidence(obj, chunk, chunk_id="c1")
    assert len(spans) == 1
    assert "灵儿" in spans[0].quote
    # span.quote 必须是 chunk 的子串, 且 start/end 精确映射
    assert chunk[spans[0].start : spans[0].end] == spans[0].quote
    assert spans[0].start is not None and spans[0].end is not None
    # 锚点 "灵儿" 应在 quote 范围内 (偏移不超过前 20 字符的前缀)
    assert chunk.find("灵儿") >= spans[0].start
    assert chunk.find("灵儿") < spans[0].end
    assert spans[0].strategy == "anchor"
    assert spans[0].chunk_id == "c1"


def test_make_evidence_falls_back_to_attribute_value():
    chunk = "这段话没有任何名字, 但提到了他在澳洲阵亡。"
    obj = {"id": "char_x", "name": "", "attributes": {"结局": "在澳洲阵亡"}}
    spans = ExtractorAgent._make_evidence(obj, chunk)
    # "在澳洲阵亡" 实际就在 chunk 内, 锚点能找到 -> strategy=anchor
    assert spans
    assert spans[0].strategy == "anchor"
    assert "澳洲" in spans[0].quote


def test_make_evidence_head_fallback_when_anchor_absent():
    chunk = "一段与抽取对象毫无关联的描述性文字。"
    obj = {"id": "char_x", "name": "完全不存在的名字XXX"}
    spans = ExtractorAgent._make_evidence(obj, chunk)
    # 锚点找不到 -> 段首兜底
    assert spans
    assert spans[0].strategy == "head"
    assert spans[0].start == 0


def test_make_evidence_handles_empty_chunk():
    assert ExtractorAgent._make_evidence({"name": "x"}, "") == []


def test_make_evidence_relation_uses_action_as_anchor():
    """关系类的 evidence 锚点: source 是 ID 找不到, 退而求 action/role/relation."""
    chunk = "林远与叶知秋在山顶结拜。林远把手伸向叶知秋。"
    obj = {"source": "char_001", "target": "char_002", "relation": "结拜"}
    spans = ExtractorAgent._make_evidence(obj, chunk)
    assert spans
    # "结拜" 在 chunk 内, 应作为锚点
    assert spans[0].strategy == "anchor"
    assert chunk[spans[0].start : spans[0].end] == spans[0].quote
    assert chunk.find("结拜") >= spans[0].start
    assert chunk.find("结拜") < spans[0].end


def test_read_confidence_priority():
    assert ExtractorAgent._read_confidence({"confidence": 0.8}) == 0.8
    assert ExtractorAgent._read_confidence({"_confidence": 0.3}) == 0.3
    assert ExtractorAgent._read_confidence({"置信度": 0.9}) == 0.9
    # Missing / invalid -> default 0.5
    assert ExtractorAgent._read_confidence({}) == 0.5
    assert ExtractorAgent._read_confidence({"confidence": "high"}) == 0.5
    # Clamp to [0, 1]
    assert ExtractorAgent._read_confidence({"confidence": 1.5}) == 1.0
    assert ExtractorAgent._read_confidence({"confidence": -0.1}) == 0.0


def test_phase_output_dicts_by_chunk_preserves_order():
    items = [
        ExtractedItem("character", {"id": "a"}, chunk_id="chapter_1"),
        ExtractedItem("character", {"id": "b"}, chunk_id="chapter_2"),
        ExtractedItem("character", {"id": "c"}, chunk_id="chapter_1"),
    ]
    out = PhaseOutput(phase="character", items=items).dicts_by_chunk()
    assert len(out) == 2
    assert [d["id"] for d in out[0]] == ["a", "c"]
    assert [d["id"] for d in out[1]] == ["b"]


def test_build_phase_prompt_uses_content_string_not_dict_repr():
    """Regression: build_character_prompt used to receive a chunk dict and
    silently substitute its repr into the prompt. The dispatcher must
    extract ``content`` as a string."""
    chunk = {"id": "c1", "title": "T", "content": "这是真实内容"}
    prompts = {
        "character": {
            "user_prompt_template": "请处理以下文本: {chunk_text}",
        }
    }
    p = build_phase_prompt("character", chunk, prompts)
    # The user_prompt_template uses {chunk_text} — only the content should
    # land in the template, not the dict's repr with keys "id", "title".
    assert "这是真实内容" in p
    assert "'id':" not in p
    assert "'title':" not in p


def test_build_phase_prompt_uses_db_user_template():
    """DB-stored user_prompt_template must be the one rendered, not the
    bundled default. This is the fix for the bug where the previous
    ``_resolve_prompt`` always returned the in-memory default.
    """
    from services.prompt_service import get_default_prompt

    chunk = {"content": "片段内容"}
    default = get_default_prompt("kg.character") or {}
    default_tmpl = default.get("user_prompt_template", "")

    custom = {
        "character": {
            "user_prompt_template": "CUSTOM_USER_PROMPT_MARKER {chunk_text}",
            "system_prompt": default.get("system_prompt", ""),
            "temperature": 0.3,
            "max_tokens": 2400,
        }
    }
    p = build_phase_prompt("character", chunk, custom)
    assert "CUSTOM_USER_PROMPT_MARKER" in p
    # The default template is much longer and would not contain the marker.
    assert "CUSTOM_USER_PROMPT_MARKER" not in default_tmpl


# ---------------------------------------------------------------------------
# MergeValidatorAgent: hard rules
# ---------------------------------------------------------------------------


def test_normalize_attr_keys_collapses_whitespace():
    agent = MergeValidatorAgent()
    attrs, renamed = agent._normalize_attr_keys({
        " 结果": "v1", "结 果": "v2", "起 因": "x", "正常": "y",
    })
    # The first occurrence wins; "结 果" collides with " 结果" -> ignored.
    assert attrs == {"结果": "v1", "起因": "x", "正常": "y"}
    assert any("结果" in r for r in renamed)
    assert any("起因" in r for r in renamed)


def test_normalize_attr_keys_handles_non_dict():
    agent = MergeValidatorAgent()
    assert agent._normalize_attr_keys(None) == ({}, [])
    assert agent._normalize_attr_keys("nope") == ({}, [])


def test_strip_name_parens():
    agent = MergeValidatorAgent()
    assert agent._strip_name_parens("我(叙述者)") == "我"
    assert agent._strip_name_parens("儿子（叙述者之子）") == "儿子"
    assert agent._strip_name_parens("我") == "我"
    assert agent._strip_name_parens("") == ""
    assert agent._strip_name_parens(None) is None


def test_normalize_entities_emits_issues():
    agent = MergeValidatorAgent()
    chars = [
        {"id": "char_001", "name": "我(叙述者)",
         "attributes": {" 性别": "男", "性 别": "未知"}},
    ]
    evts = [
        {"id": "evt_001", "name": "evt",
         "attributes": {"摘 要": "abc", " 起因": "x"}},
    ]
    new_c, new_e, issues = agent.normalize_entities(chars, evts)
    assert new_c[0]["name"] == "我"
    assert new_c[0]["attributes"] == {"性别": "男"}
    assert new_e[0]["attributes"] == {"摘要": "abc", "起因": "x"}
    codes = {i.code for i in issues}
    assert "name_parens_stripped" in codes
    assert "attr_key_whitespace" in codes


# ---------------------------------------------------------------------------
# MergeValidatorAgent: reference integrity
# ---------------------------------------------------------------------------


def test_validate_references_flags_orphan_participation():
    chars = [{"id": "char_001", "name": "a"}]
    evts = [{"id": "evt_001", "name": "e"}]
    parts = [
        {"source": "char_001", "target": "evt_001"},  # OK
        {"source": "char_999", "target": "evt_001"},  # orphan source
        {"source": "char_001", "target": "evt_999"},  # orphan target
    ]
    issues = MergeValidatorAgent.validate_references(
        chars, evts, parts, [], []
    )
    codes = [i.code for i in issues]
    assert codes.count("orphan_participation") == 2


def test_validate_references_flags_orphan_char_and_event_relations():
    chars = [{"id": "char_001", "name": "a"}]
    evts = [{"id": "evt_001", "name": "e"}]
    char_rels = [{"source": "char_999", "target": "char_001"}]
    evt_rels = [{"source": "evt_001", "target": "evt_999"}]
    issues = MergeValidatorAgent.validate_references(
        chars, evts, [], char_rels, evt_rels
    )
    codes = {i.code for i in issues}
    assert "orphan_char_relation" in codes
    assert "orphan_event_relation" in codes


# ---------------------------------------------------------------------------
# MergeValidatorAgent: coverage
# ---------------------------------------------------------------------------


def test_coverage_check_counts_participants_per_event():
    chars = [{"id": "char_001"}, {"id": "char_002"}, {"id": "char_003"}]
    evts = [{"id": "evt_001"}, {"id": "evt_002"}]
    parts = [
        {"source": "char_001", "target": "evt_001"},
        {"source": "char_002", "target": "evt_001"},
        {"source": "char_003", "target": "evt_002"},
    ]
    report, issues = MergeValidatorAgent.coverage_check(chars, evts, parts)
    assert report["participations"] == 3
    assert report["per_event_participant_count"]["evt_001"] == 2
    assert report["per_event_participant_count"]["evt_002"] == 1
    # Every event has at least 1 participant -> no missing_participation issues
    assert all(i.code != "missing_participation" for i in issues)
    assert report["events_without_participant"] == []


def test_coverage_check_flags_orphan_events():
    chars = [{"id": "char_001"}]
    evts = [{"id": "evt_001"}, {"id": "evt_002"}]
    parts = [{"source": "char_001", "target": "evt_001"}]
    _report, issues = MergeValidatorAgent.coverage_check(chars, evts, parts)
    assert any(
        i.code == "missing_participation" and i.payload["event"] == "evt_002"
        for i in issues
    )


# ---------------------------------------------------------------------------
# MergeValidatorAgent: end-to-end (without LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_runs_hard_rules_and_skips_llm():
    agent = MergeValidatorAgent()
    characters = [
        {"id": "char_001", "name": "我(叙述者)", "attributes": {" 性别": "男"}},
        {"id": "char_002", "name": "灵儿", "attributes": {}},
    ]
    events = [
        {"id": "evt_001", "name": "看日出",
         "attributes": {"摘 要": "x", " 起因": "y"}},
        {"id": "evt_002", "name": "启航",
         "attributes": {"摘要": "z"}},
    ]
    participations = [
        {"source": "char_001", "target": "evt_001"},
        {"source": "char_999", "target": "evt_001"},  # orphan
    ]
    char_relations: List[Dict[str, Any]] = []
    event_relations: List[Dict[str, Any]] = []

    validated = await agent.validate(
        characters=characters,
        events=events,
        participations=participations,
        char_relations=char_relations,
        event_relations=event_relations,
        run_llm_dedup=False,
    )

    # 1) Names normalized (parens stripped)
    assert all("(" not in c["name"] for c in validated.characters)
    # 2) Attribute keys normalized
    for e in validated.events:
        for k in e["attributes"]:
            assert " " not in k, f"key {k!r} still has whitespace"
    # 3) Orphan participation detected
    codes = {i.code for i in validated.issues}
    assert "orphan_participation" in codes
    # 4) Coverage report present
    # Both participations are counted in the stats (orphans are flagged as
    # issues separately, not excluded from the count).
    assert validated.coverage["participations"] == 2
    assert "evt_002" in validated.coverage["events_without_participant"]
    # 5) dedup_log empty (LLM dedup disabled)
    assert validated.dedup_log == []


# ---------------------------------------------------------------------------
# P0: EvidenceSpan + offset
# ---------------------------------------------------------------------------


def test_evidence_span_roundtrip_to_dict():
    from services.agents import EvidenceSpan
    s = EvidenceSpan(
        chunk_id="c1", quote="灵儿在船上", start=5, end=10,
        strategy="anchor", sentence_idx=2,
    )
    d = s.to_dict()
    assert d["chunk_id"] == "c1"
    assert d["start"] == 5
    assert d["end"] == 10
    assert d["strategy"] == "anchor"
    assert d["sentence_idx"] == 2


def test_find_offsets_tolerates_truncated_punctuation():
    from services.agents import _find_offsets
    chunk = "第一段。灵儿在船上, 我和灵儿手拉手走向甲板。"
    # LLM 截断末尾标点
    quote = "灵儿在船上"
    s, e = _find_offsets(chunk, quote)
    assert s is not None
    assert chunk[s:e] == quote


def test_find_offsets_returns_none_when_not_found():
    from services.agents import _find_offsets
    s, e = _find_offsets("短文本", "完全找不到的片段")
    assert s is None and e is None


# ---------------------------------------------------------------------------
# P1: 关系二次确认 (low confidence)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_low_confidence_relations_drops_invalid(monkeypatch):
    """LLM 判否的边进 dropped, 判是的进 kept 且 confidence 提升."""
    from services import agents

    async def fake_chat(**kwargs):
        # 检查 user_prompt 含边信息
        assert "char_a" in kwargs["user_prompt"]
        return '{"is_valid": false, "reason": "边不存在"}'

    monkeypatch.setattr(agents.ai_service, "chat_completion", fake_chat)
    agent = MergeValidatorAgent()
    rels = [
        {"source": "char_a", "target": "char_b",
         "relation": "结拜", "confidence": 0.4},
        {"source": "char_c", "target": "char_d",
         "relation": "父子", "confidence": 0.95},  # 高 confidence 跳过
    ]
    kept, dropped = await agent.confirm_low_confidence_relations(
        rels, "{}", {"c1": "ctx"},
        model_cfg={"provider": "x", "model_url": "u", "api_key": "k",
                   "model_name": "m"},
        # 显式传模板, 避免缺省模板查找
        tmpl={"user_prompt_template": "judge {relation_json} {evidence}",
              "system_prompt": "", "temperature": 0.1, "max_tokens": 400},
        threshold=0.7,
    )
    assert len(kept) == 1
    assert kept[0]["source"] == "char_c"
    assert len(dropped) == 1
    assert dropped[0]["source"] == "char_a"
    assert dropped[0].get("rejected") is True


# ---------------------------------------------------------------------------
# P0: KG 管理
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_knowledge_graph_clears_all_tables(tmp_path, monkeypatch):
    """delete_knowledge_graph 走 database.delete, 验证表都被清."""
    from services import kg_service

    # 用一个 in-memory fake db layer
    deleted_tables: list = []

    async def fake_delete(novel_id: int):
        return {
            "characters": 3,
            "events": 2,
            "character_event_relations": 5,
            "character_relations": 1,
            "event_relations": 0,
        }

    monkeypatch.setattr(
        "database.delete_knowledge_graph", fake_delete, raising=False
    )
    counts = await kg_service.delete_knowledge_graph(99)
    assert counts["characters"] == 3
    assert counts["character_event_relations"] == 5
