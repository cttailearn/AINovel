"""KG RAG 排序: 对知识图谱中的人物 / 事件 / 地点按相关度排序, 取 top-K.

设计目标:
- 长篇后期 KG 越来越大 (上百个实体), 全量塞给 LLM 浪费 token 且稀释注意力.
- 对每条实体计算一个 0-100 的相关度, 取 top-K=30.
- 计算只用纯 Python, 不调 LLM.
- 优先级: 本章 direction 提到 > 上一章 confirmed 出现 > 与 outline 关键词重合 > 上一章 foreshadowing 提到 > 其它.
- Importance 加权: 主角/主角身边的人/重要反派始终靠前, 路人/小配角靠后.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple


# 容量上限 (Writer/Critic/Planner 的 KG 上下文最多给 K 个实体)
DEFAULT_TOP_K = 30
# Importance >= 4 的实体 (主角/重要配角/主要反派) 永远保留, 不被截断
PROTECTED_IMPORTANCE = 4
# 每类型最多给的实体数 (防止某一类型霸榜)
PER_TYPE_QUOTA = {
    "character": 12,
    "event": 10,
    "location": 8,
}


def _norm_name(name: str) -> str:
    return (name or "").strip()


def _keyword_set(text: str) -> Set[str]:
    """粗粒度中文分词: 切 2-gram + 单字, 用于模糊匹配."""
    text = re.sub(r"[\s,。!?;:\-\(\)（）【】\"'\u201c\u201d\u2018\u2019]", "", text or "")
    if not text:
        return set()
    grams = set()
    for ch in text:
        grams.add(ch)
    for i in range(len(text) - 1):
        grams.add(text[i : i + 2])
    return grams


def _overlap_score(a: Set[str], b: Set[str]) -> int:
    if not a or not b:
        return 0
    return len(a & b)


def rank_kg(
    kg: Dict[str, List[Dict[str, Any]]],
    *,
    planner_directions: Optional[List[Dict[str, Any]]] = None,
    last_chapter_content: str = "",
    outline: str = "",
    last_directions: Optional[List[Dict[str, Any]]] = None,
    top_k: int = DEFAULT_TOP_K,
) -> Dict[str, List[Dict[str, Any]]]:
    """给 KG 中的人物/事件/地点打分, 返回排序后 + 截断的 KG dict.

    入参:
      - kg:               来自 db.get_ai_knowledge_graph, 包含 characters/events/character_relations/.../ locations 可选.
      - planner_directions: 本章 Planner 给的 3 个方向, 每方向含 key_entities, foreshadowing 等.
      - last_chapter_content: 上一章 confirmed 正文 (用 2000 字截断).
      - outline:           项目大纲 (用户最初设定).
      - last_directions:   上一章的 3 个方向 (用其 foreshadowing).
      - top_k:             每种类型的最大实体数.
    """
    direction_entities: Set[str] = set()
    direction_foreshadowing: Set[str] = set()
    if planner_directions:
        for d in planner_directions:
            for e in d.get("key_entities") or []:
                direction_entities.add(_norm_name(e))
            for f in d.get("foreshadowing") or []:
                direction_foreshadowing.add(_norm_name(f))
            for t in d.get("themes") or []:
                direction_foreshadowing.add(_norm_name(t))

    last_chapter_kg = _keyword_set(last_chapter_content[:2000])
    outline_kg = _keyword_set(outline)

    last_foreshadowing_kg: Set[str] = set()
    if last_directions:
        for d in last_directions:
            for f in d.get("foreshadowing") or []:
                last_foreshadowing_kg.add(_norm_name(f))

    ranked: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {
        "character": [],
        "event": [],
        "location": [],
    }
    out: Dict[str, List[Dict[str, Any]]] = {
        "characters": [],
        "events": [],
        "locations": [],
    }

    for ch in kg.get("characters") or []:
        score = _score_entity(
            ch,
            kind="character",
            direction_entities=direction_entities,
            direction_foreshadowing=direction_foreshadowing,
            last_chapter_kg=last_chapter_kg,
            outline_kg=outline_kg,
            last_foreshadowing_kg=last_foreshadowing_kg,
        )
        ranked["character"].append((score, ch))

    for ev in kg.get("events") or []:
        score = _score_entity(
            ev,
            kind="event",
            direction_entities=direction_entities,
            direction_foreshadowing=direction_foreshadowing,
            last_chapter_kg=last_chapter_kg,
            outline_kg=outline_kg,
            last_foreshadowing_kg=last_foreshadowing_kg,
        )
        ranked["event"].append((score, ev))

    for loc in kg.get("locations") or []:
        score = _score_entity(
            loc,
            kind="location",
            direction_entities=direction_entities,
            direction_foreshadowing=direction_foreshadowing,
            last_chapter_kg=last_chapter_kg,
            outline_kg=outline_kg,
            last_foreshadowing_kg=last_foreshadowing_kg,
        )
        ranked["location"].append((score, loc))

    for kind, items in ranked.items():
        items.sort(key=lambda x: -x[0])
        quota = PER_TYPE_QUOTA.get(kind, top_k)
        for score, ent in items:
            if score <= 0 and len(out_for(out, kind)) >= quota:
                break
            importance = _importance_of(ent, kind)
            # importance >= 4 永远保留
            if len(out_for(out, kind)) >= quota and importance < PROTECTED_IMPORTANCE:
                continue
            if importance >= PROTECTED_IMPORTANCE and len(out_for(out, kind)) >= quota * 2:
                continue
            out_for(out, kind).append(ent)
            if len(out_for(out, kind)) >= quota * 2 and importance < PROTECTED_IMPORTANCE:
                break

    # 关系 (character_relations / event_relations / character_event_relations) 跟着人物/事件走
    allowed_chars = {e.get("entity_id") for e in out["characters"]}
    allowed_events = {e.get("entity_id") for e in out["events"]}
    allowed_locs = {e.get("entity_id") for e in out["locations"]}

    for kind, allowed in (
        ("character_relations", allowed_chars),
        ("event_relations", allowed_events),
        ("character_event_relations", None),  # 不限, 端点会在下面剪
    ):
        rels = []
        for r in kg.get(kind) or []:
            s = r.get("source_entity_id")
            t = r.get("target_entity_id")
            if kind == "character_relations":
                if s in allowed or t in allowed:
                    rels.append(r)
            elif kind == "event_relations":
                if s in allowed or t in allowed:
                    rels.append(r)
            else:  # character_event_relations
                if s in allowed_chars or t in allowed_events:
                    rels.append(r)
        out[kind] = rels

    # 旧别名: 兼容 kg.characters / kg.events
    out.setdefault("characters", out.get("characters", []))
    out.setdefault("events", out.get("events", []))
    return out


def out_for(out: Dict[str, Any], kind: str) -> List[Dict[str, Any]]:
    """Helper: 取出对应类型的列表. 'character' 找 'characters' (out 总是用复数键)."""
    if kind + "s" in out:
        return out[kind + "s"]
    if kind + "es" in out:
        return out[kind + "es"]
    if kind in out:
        return out[kind]
    return []


def _score_entity(
    entity: Dict[str, Any],
    *,
    kind: str,
    direction_entities: Set[str],
    direction_foreshadowing: Set[str],
    last_chapter_kg: Set[str],
    outline_kg: Set[str],
    last_foreshadowing_kg: Set[str],
) -> float:
    """单个实体的相关度分数 0-200+."""
    name = _norm_name(entity.get("name") or "")
    if not name:
        return 0.0
    score = 0.0
    # 角色身份加权 (主角永远靠前)
    importance = _importance_of(entity, kind)
    score += importance * 8  # importance 1..5 → 8..40

    # 直接在 direction key_entities 中
    if name in direction_entities:
        score += 100
    # 在 direction foreshadowing / themes 中
    if name in direction_foreshadowing:
        score += 80
    # 在上章正文中出现
    score += _overlap_score(_keyword_set(name), last_chapter_kg) * 4
    # 与项目 outline 关键词重合
    score += _overlap_score(_keyword_set(name), outline_kg) * 3
    # 与上章 direction 的 foreshadowing 关键词重合
    score += _overlap_score(_keyword_set(name), last_foreshadowing_kg) * 2
    return score


def _importance_of(entity: Dict[str, Any], kind: str) -> int:
    imp = entity.get("importance")
    if isinstance(imp, (int, float)) and 0 < imp <= 5:
        return int(imp)
    if kind == "character":
        role = (entity.get("role") or "").strip()
        if role in ("主角", "main"):
            return 5
        if role in ("配角", "重要配角"):
            return 3
        if role in ("反派", "重要反派"):
            return 4
        if role in ("路人", "minor"):
            return 1
    if kind == "event":
        # 事件名包含"主" "核心" 视为高
        name = entity.get("name") or ""
        if "主" in name or "核心" in name or "终" in name or "开" in name:
            return 4
    return 2


def _kg_warnings_for_prompt(kg: Dict[str, Any]) -> str:
    """从 KG 中提取已知冲突/未解决伏笔, 给 LLM 一个明确提醒."""
    warnings: List[str] = []
    for ev in kg.get("events") or []:
        attrs = ev.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs) if attrs.strip() else {}
            except (TypeError, ValueError):
                attrs = {}
        for c in attrs.get("conflicts_observed") or []:
            if not c.get("resolved"):
                ch_no = c.get("chapter_no", "?")
                quote = (c.get("quote") or "").strip()[:60]
                warnings.append(
                    f"⚠ 事件『{ev.get('name', '?')}』在第{ch_no}章存在未解决冲突: {quote}"
                )
    for ch in kg.get("characters") or []:
        attrs = ch.get("attributes") or {}
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs) if attrs.strip() else {}
            except (TypeError, ValueError):
                attrs = {}
        for c in attrs.get("conflicts_observed") or []:
            if not c.get("resolved"):
                ch_no = c.get("chapter_no", "?")
                quote = (c.get("quote") or "").strip()[:60]
                warnings.append(
                    f"⚠ 人物『{ch.get('name', '?')}』在第{ch_no}章存在未解决冲突: {quote}"
                )
    return "\n".join(warnings) or "(无)"
