"""测试 #3 / #41 阶段 1 ② — KG 统一读层 (db.kg)."""
from __future__ import annotations

from db.kg import (
    DEPRECATED_NOTICE,
    KG_PHYSICAL_TABLES,
    KgSystem,
    is_deprecated_novel_kg,
    kg_system_from_request,
    unified_graph_shape,
)


def test_kg_system_enum_values():
    assert KgSystem.AI.value == "ai"
    assert KgSystem.NOVEL.value == "novel"


def test_is_deprecated_novel_kg():
    assert is_deprecated_novel_kg(KgSystem.NOVEL) is True
    assert is_deprecated_novel_kg(KgSystem.AI) is False
    # 字符串入参
    assert is_deprecated_novel_kg("novel") is True
    assert is_deprecated_novel_kg("ai") is False
    # 非法值兜底
    assert is_deprecated_novel_kg("unknown") is False
    assert is_deprecated_novel_kg(None) is False


def test_kg_system_from_request_fallback():
    assert kg_system_from_request(None) is KgSystem.AI
    assert kg_system_from_request("") is KgSystem.AI
    assert kg_system_from_request("novel") is KgSystem.NOVEL
    assert kg_system_from_request("AI") is KgSystem.AI
    assert kg_system_from_request("invalid") is KgSystem.AI


def test_kg_physical_tables_mapping():
    ai = KG_PHYSICAL_TABLES[KgSystem.AI]
    assert ai["characters"] == "ai_kg_characters"
    assert ai["events"] == "ai_kg_events"
    assert "locations" in ai  # 项目级才有

    novel = KG_PHYSICAL_TABLES[KgSystem.NOVEL]
    assert novel["characters"] == "characters"
    assert "locations" not in novel  # 小说级没有 locations


def test_unified_graph_shape_minimal():
    out = unified_graph_shape(kg_system=KgSystem.AI)
    assert out["kg_system"] == "ai"
    assert out["characters"] == []
    assert out["events"] == []
    assert out["character_relations"] == []
    assert out["event_relations"] == []
    assert out["locations"] == []
    assert "deprecated_notice" not in out


def test_unified_graph_shape_novel_deprecation():
    out = unified_graph_shape(
        kg_system=KgSystem.NOVEL,
        characters=[{"entity_id": "c1", "name": "测试人物"}],
        events=[{"entity_id": "e1", "name": "测试事件"}],
    )
    assert out["kg_system"] == "novel"
    assert out["deprecated_notice"] == DEPRECATED_NOTICE
    assert len(out["characters"]) == 1
    # 小说级不应出现 locations
    assert "locations" not in out


def test_unified_graph_shape_extra_passthrough():
    out = unified_graph_shape(
        kg_system=KgSystem.AI,
        extra={"stats": {"character_count": 3}},
    )
    assert out["stats"] == {"character_count": 3}
