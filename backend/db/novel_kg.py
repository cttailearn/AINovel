from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from db.connection import get_db
from db.common import (
    _build_entity_extras,
    _build_relation_extras,
    _decode_attributes,
    _decode_extras,
    _encode_attributes,
    _encode_extras,
)

# ---------------------------------------------------------------------------
# Knowledge graph CRUD
# ---------------------------------------------------------------------------


async def delete_knowledge_graph(novel_id: int) -> Dict[str, int]:
    """原子清空指定小说的全部知识图谱.

    返回每张表的删除行数, 便于前端展示"已删除 X 人物 / Y 事件 / Z 关系".
    """
    counts: Dict[str, int] = {}
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for table in (
            "character_event_relations",
            "character_relations",
            "event_relations",
            "events",
            "characters",
        ):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE novel_id = ?", (novel_id,)
            )
            counts[table] = cur.rowcount or 0
        await db.commit()
    return counts


# ---------------------------------------------------------------------------
# Knowledge graph CRUD
# ---------------------------------------------------------------------------


async def replace_knowledge_graph(
    novel_id: int,
    *,
    characters: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    character_event_relations: List[Dict[str, Any]],
    character_relations: List[Dict[str, Any]],
    event_relations: List[Dict[str, Any]],
    model_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Atomically replace the full knowledge graph for a novel."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM character_event_relations WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM character_relations WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM event_relations WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM events WHERE novel_id = ?", (novel_id,))
        await db.execute("DELETE FROM characters WHERE novel_id = ?", (novel_id,))

        stored_chars: List[Dict[str, Any]] = []
        for c in characters:
            extras = c.get("extras") or _build_entity_extras(c)
            cur = await db.execute(
                """
                INSERT INTO characters
                    (novel_id, entity_id, name, attributes, model_id, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(c.get("entity_id") or c.get("id") or "").strip(),
                    str(c.get("name", "")).strip()[:200] or "未命名",
                    _encode_attributes(c.get("attributes") or {}),
                    model_id,
                    _encode_extras(extras),
                ),
            )
            stored_chars.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "entity_id": str(c.get("entity_id") or c.get("id") or "").strip(),
                    "name": str(c.get("name", "")).strip(),
                    "attributes": c.get("attributes") or {},
                    "model_id": model_id,
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_events: List[Dict[str, Any]] = []
        for e in events:
            extras = e.get("extras") or _build_entity_extras(e)
            cur = await db.execute(
                """
                INSERT INTO events
                    (novel_id, entity_id, name, attributes, model_id, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(e.get("entity_id") or e.get("id") or "").strip(),
                    str(e.get("name", "")).strip()[:200] or "未命名事件",
                    _encode_attributes(e.get("attributes") or {}),
                    model_id,
                    _encode_extras(extras),
                ),
            )
            stored_events.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "entity_id": str(e.get("entity_id") or e.get("id") or "").strip(),
                    "name": str(e.get("name", "")).strip(),
                    "attributes": e.get("attributes") or {},
                    "model_id": model_id,
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_ce: List[Dict[str, Any]] = []
        for r in character_event_relations:
            properties = r.get("properties") if isinstance(r.get("properties"), dict) else {}
            extras = r.get("extras") or _build_relation_extras(r)
            cur = await db.execute(
                """
                INSERT INTO character_event_relations
                    (novel_id, source_entity_id, target_entity_id,
                     relation, role, action, properties, extras)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(r.get("source") or r.get("source_entity_id") or "").strip(),
                    str(r.get("target") or r.get("target_entity_id") or "").strip(),
                    str(r.get("relation") or "PARTICIPATES_IN").strip() or "PARTICIPATES_IN",
                    (r.get("role") or None),
                    (r.get("action") or None),
                    _encode_attributes(properties),
                    _encode_extras(extras),
                ),
            )
            stored_ce.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "source_entity_id": str(r.get("source") or "").strip(),
                    "target_entity_id": str(r.get("target") or "").strip(),
                    "relation": str(r.get("relation") or "PARTICIPATES_IN").strip(),
                    "role": r.get("role") or None,
                    "action": r.get("action") or None,
                    "properties": properties,
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_cc: List[Dict[str, Any]] = []
        for r in character_relations:
            extras = r.get("extras") or _build_relation_extras(r)
            cur = await db.execute(
                """
                INSERT INTO character_relations
                    (novel_id, source_entity_id, target_entity_id,
                     relation, properties, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(r.get("source") or r.get("source_entity_id") or "").strip(),
                    str(r.get("target") or r.get("target_entity_id") or "").strip(),
                    str(r.get("relation") or "").strip() or "关联",
                    _encode_attributes(r.get("properties") or {}),
                    _encode_extras(extras),
                ),
            )
            stored_cc.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "source_entity_id": str(r.get("source") or "").strip(),
                    "target_entity_id": str(r.get("target") or "").strip(),
                    "relation": str(r.get("relation") or "").strip() or "关联",
                    "properties": r.get("properties") or {},
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        stored_ee: List[Dict[str, Any]] = []
        for r in event_relations:
            extras = r.get("extras") or _build_relation_extras(r)
            cur = await db.execute(
                """
                INSERT INTO event_relations
                    (novel_id, source_entity_id, target_entity_id,
                     relation, properties, extras)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    str(r.get("source") or r.get("source_entity_id") or "").strip(),
                    str(r.get("target") or r.get("target_entity_id") or "").strip(),
                    str(r.get("relation") or "").strip() or "关联",
                    _encode_attributes(r.get("properties") or {}),
                    _encode_extras(extras),
                ),
            )
            stored_ee.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "source_entity_id": str(r.get("source") or "").strip(),
                    "target_entity_id": str(r.get("target") or "").strip(),
                    "relation": str(r.get("relation") or "").strip() or "关联",
                    "properties": r.get("properties") or {},
                    "extras": extras if isinstance(extras, dict) else {},
                }
            )

        await db.commit()
        return {
            "characters": stored_chars,
            "events": stored_events,
            "character_event_relations": stored_ce,
            "character_relations": stored_cc,
            "event_relations": stored_ee,
        }


async def get_knowledge_graph(novel_id: int) -> Dict[str, List[Dict[str, Any]]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, novel_id, entity_id, name, attributes,
                   model_id, extras, created_at, updated_at
            FROM characters WHERE novel_id = ? ORDER BY entity_id
            """,
            (novel_id,),
        )
        characters: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            characters.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, entity_id, name, attributes,
                   model_id, extras, created_at, updated_at
            FROM events WHERE novel_id = ? ORDER BY entity_id
            """,
            (novel_id,),
        )
        events: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            events.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, source_entity_id, target_entity_id,
                   relation, role, action, properties, extras
            FROM character_event_relations WHERE novel_id = ?
            """,
            (novel_id,),
        )
        ce_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ce_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, source_entity_id, target_entity_id,
                   relation, properties, extras
            FROM character_relations WHERE novel_id = ?
            """,
            (novel_id,),
        )
        cc_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            cc_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, novel_id, source_entity_id, target_entity_id,
                   relation, properties, extras
            FROM event_relations WHERE novel_id = ?
            """,
            (novel_id,),
        )
        ee_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ee_relations.append(row)

    # ④ locations
    cur = await db.execute(
        """
        SELECT id, project_id, entity_id, name, location_type, attributes,
               source_chapter_id, model_id, extras, created_at, updated_at
        FROM ai_kg_locations WHERE project_id = ? ORDER BY name
        """,
        (project_id,),
    )
    locations: List[Dict[str, Any]] = []
    for r in await cur.fetchall():
        row = dict(r)
        row["attributes"] = _decode_attributes(row.get("attributes"))
        row["extras"] = _decode_extras(row.get("extras"))
        locations.append(row)

    # ⑤ plot_threads (open/hinting 优先)
    cur = await db.execute(
        """
        SELECT id, project_id, thread_id, title, thread_type, status, priority,
               introduced_chapter_id, resolved_chapter_id, related_entity_ids,
               notes, source_chapter_id, model_id, created_at, updated_at
        FROM ai_kg_plot_threads WHERE project_id = ?
        ORDER BY
            CASE status WHEN 'open' THEN 0 WHEN 'hinting' THEN 1
                        WHEN 'resolving' THEN 2 WHEN 'resolved' THEN 3
                        WHEN 'dropped' THEN 4 ELSE 5 END,
            priority DESC, created_at ASC
        """,
        (project_id,),
    )
    threads: List[Dict[str, Any]] = []
    for r in await cur.fetchall():
        row = dict(r)
        if row.get("related_entity_ids"):
            try:
                row["related_entity_ids"] = json.loads(row["related_entity_ids"])
            except (TypeError, ValueError):
                row["related_entity_ids"] = []
        threads.append(row)

    return {
        "characters": characters,
        "events": events,
        "locations": locations,
        "plot_threads": threads,
        "character_event_relations": ce_relations,
        "character_relations": cc_relations,
        "event_relations": ee_relations,
    }


async def get_kg_stats(novel_id: int) -> Dict[str, int]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM characters WHERE novel_id = ?", (novel_id,)
        )
        char_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM events WHERE novel_id = ?", (novel_id,)
        )
        event_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM character_event_relations WHERE novel_id = ?",
            (novel_id,),
        )
        ce_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM character_relations WHERE novel_id = ?",
            (novel_id,),
        )
        cc_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) AS c FROM event_relations WHERE novel_id = ?",
            (novel_id,),
        )
        ee_count = (await cur.fetchone())[0]
    return {
        "characters": char_count,
        "events": event_count,
        "participations": ce_count,
        "character_relations": cc_count,
        "event_relations": ee_count,
    }
