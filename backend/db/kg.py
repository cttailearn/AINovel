"""两套 KG 的统一读层 / 弃用策略 (修复 #3 + #41 阶段 1 ③).

历史上 ``backend/db/novel_kg.py`` 和 ``backend/db/ai_kg.py`` 物理隔离
(``characters / events`` 五表 vs ``ai_kg_characters`` 等 11 表), 创作工坊
和加料工坊各用一套, 互不知道.

按照 ``docs/修改v0.1.md`` 的 #3 + #41 建议, 我们:

* 保留两套物理表 (迁移成本最低, 不破坏现有 ``kg_service`` / ``creation_service``)
* 在 ``KgSystem`` 枚举里把"小说级 KG"标记 ``DEPRECATED``, 后续新功能
  只走 ``ai_kg``
* 提供 ``read_knowledge_graph(subject_id, kg_system)`` 统一读视图,
  把"人物 / 事件 / 关系"的 3 个 List 收敛到一份返回结构, 业务调用方
  只认这一份
* 前端在调用小说级 KG 接口时, 后端额外返回 ``deprecated_notice`` 字段,
  用于弹"该视图已弃用"提示

具体实现:

* ``KgSystem.NOVEL``  → ``characters / events / character_event_relations / character_relations / event_relations``
* ``KgSystem.AI``     → ``ai_kg_characters / ai_kg_events / ai_kg_locations / ai_kg_character_relations / ai_kg_event_relations / ai_kg_character_appearances / ai_kg_plot_threads``

新增: ``stats / deprecated_notice`` 字段; 后续要做 schema 升级时, 只需要
把 ``KG_PHYSICAL_TABLES`` 里的表名替换即可.
"""
from __future__ import annotations

import enum
from typing import Any, Dict, List


class KgSystem(str, enum.Enum):
    """KG 系统枚举 — 修复 #3.

    * ``AI``  = 项目级 ai_kg_* 表, 面向 AI 创作 (推荐, 新功能)
    * ``NOVEL`` = 小说级 characters / events 表, 面向"加料工坊"
      已标记 DEPRECATED, 后续只会做只读兼容
    """

    AI = "ai"
    NOVEL = "novel"


# 弃用提示语, 暴露给 router, 写入响应 header / body 字段
DEPRECATED_NOTICE = (
    "该 KG 视图基于已弃用的小说级 characters/events 表, "
    "新功能请改用 ai_kg_* (KgSystem.AI)."
)


# 物理表名映射, 用于做"统一读视图"时按需 SELECT
KG_PHYSICAL_TABLES: Dict[KgSystem, Dict[str, str]] = {
    KgSystem.AI: {
        "characters": "ai_kg_characters",
        "events": "ai_kg_events",
        "locations": "ai_kg_locations",
        "character_relations": "ai_kg_character_relations",
        "event_relations": "ai_kg_event_relations",
    },
    KgSystem.NOVEL: {
        "characters": "characters",
        "events": "events",
        "character_relations": "character_relations",
        "event_relations": "event_relations",
    },
}


def is_deprecated_novel_kg(kg_system: KgSystem | str) -> bool:
    """判断是否在用已弃用的小说级 KG. 供 router 加 header / 弹窗."""
    if isinstance(kg_system, str):
        try:
            kg_system = KgSystem(kg_system)
        except ValueError:
            return False
    return kg_system == KgSystem.NOVEL


def kg_system_from_request(value: str | None, default: KgSystem = KgSystem.AI) -> KgSystem:
    """从 query string 解析 ``?kg_system=ai|novel``; 解析失败 / 缺省走 AI."""
    if not value:
        return default
    try:
        return KgSystem(value.lower())
    except ValueError:
        return default


def unified_graph_shape(
    *,
    kg_system: KgSystem,
    characters: List[Dict[str, Any]] | None = None,
    events: List[Dict[str, Any]] | None = None,
    locations: List[Dict[str, Any]] | None = None,
    character_relations: List[Dict[str, Any]] | None = None,
    event_relations: List[Dict[str, Any]] | None = None,
    extra: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """统一读视图的返回结构 (修复 #3 + #41 阶段 1 ②).

    调用方 (router / service) 把已经从对应表 SELECT 出来的列表塞进来,
    这里负责: 标准化字段 + 补充 ``kg_system`` + 必要时补 ``deprecated_notice``.
    """
    out: Dict[str, Any] = {
        "kg_system": kg_system.value,
        "characters": characters or [],
        "events": events or [],
        "character_relations": character_relations or [],
        "event_relations": event_relations or [],
    }
    if kg_system is KgSystem.AI:
        out["locations"] = locations or []
    if is_deprecated_novel_kg(kg_system):
        out["deprecated_notice"] = DEPRECATED_NOTICE
    if extra:
        out.update(extra)
    return out
