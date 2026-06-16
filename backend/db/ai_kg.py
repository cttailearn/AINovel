from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from db.common import (
    _aliases_from_db,
    _aliases_to_db,
    _build_entity_extras,
    _build_relation_extras,
    _decode_attributes,
    _decode_extras,
    _encode_attributes,
    _encode_extras,
    _extract_aliases_from_obj,
    _merge_aliases,
)
from db.connection import get_db

logger = logging.getLogger(__name__)

# --- AI 创作专用知识图谱 --------------------------------------------------


async def get_ai_knowledge_graph(project_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """返回项目级 KG (独立 5 表), 结构与现有 get_knowledge_graph 一致."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_characters WHERE project_id = ? ORDER BY entity_id
            """,
            (project_id,),
        )
        characters: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            characters.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_events WHERE project_id = ? ORDER BY entity_id
            """,
            (project_id,),
        )
        events: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["attributes"] = _decode_attributes(row.get("attributes"))
            row["extras"] = _decode_extras(row.get("extras"))
            events.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, source_entity_id, target_entity_id,
                   relation, role, action, properties, extras, source_chapter_id
            FROM ai_kg_character_event_relations WHERE project_id = ?
            """,
            (project_id,),
        )
        ce_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            ce_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, source_entity_id, target_entity_id,
                   relation, properties, extras, source_chapter_id
            FROM ai_kg_character_relations WHERE project_id = ?
            """,
            (project_id,),
        )
        cc_relations: List[Dict[str, Any]] = []
        for r in await cur.fetchall():
            row = dict(r)
            row["properties"] = _decode_attributes(row.get("properties"))
            row["extras"] = _decode_extras(row.get("extras"))
            cc_relations.append(row)

        cur = await db.execute(
            """
            SELECT id, project_id, source_entity_id, target_entity_id,
                   relation, properties, extras, source_chapter_id
            FROM ai_kg_event_relations WHERE project_id = ?
            """,
            (project_id,),
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


async def upsert_ai_kg_from_extraction(
    project_id: int,
    *,
    source_chapter_id: Optional[int],
    characters: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
    character_event_relations: List[Dict[str, Any]],
    character_relations: List[Dict[str, Any]],
    event_relations: List[Dict[str, Any]],
    locations: Optional[List[Dict[str, Any]]] = None,
    model_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """根据单章节抽取结果, UPSERT 到项目级 KG (按 entity_id 同名合并属性).

    合并策略:
    - 已存在 (project_id, entity_id): 合并 attributes (后者覆盖前者), ⑥结构化字段用新值
    - 不存在: 插入新行
    - 关系表: 同 source/target/relation 三元组视为同一条, 重复则跳过
    - ④ Locations / ⑤ Threads / ⑩ character_appearances 走独立分支
    """
    stored: Dict[str, List[Dict[str, Any]]] = {
        "characters": [],
        "events": [],
        "locations": [],
        "character_event_relations": [],
        "character_relations": [],
        "event_relations": [],
    }

    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")

        # ---- characters ----
        for c in characters:
            entity_id = str(c.get("entity_id") or c.get("id") or "").strip()
            if not entity_id:
                continue
            cur = await db.execute(
                "SELECT id, attributes, aliases, description FROM ai_kg_characters "
                "WHERE project_id = ? AND entity_id = ?",
                (project_id, entity_id),
            )
            row = await cur.fetchone()
            merged_attrs = {**(c.get("attributes") or {})}
            extras = _build_entity_extras(c)
            # ⑥ 结构化字段: 来自实体本身, 优先于 attributes
            structured = {
                "role": c.get("role"),
                "faction": c.get("faction"),
                "current_location_entity_id": c.get("current_location_entity_id"),
                "status": c.get("status"),
                "first_appearance_chapter_id": c.get("first_appearance_chapter_id"),
                "importance": c.get("importance"),
            }
            structured = {k: v for k, v in structured.items() if v not in (None, "")}
            # RAG-lite: aliases + description 解析
            new_aliases = _extract_aliases_from_obj(c)
            new_description = str(c.get("description") or "").strip()[:500]

            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                # 别名合并: 历史优先, 新增 append
                old_aliases = _aliases_from_db(row["aliases"])
                merged_aliases = _merge_aliases(old_aliases, new_aliases)
                # description: 优先保留较长的那个
                old_description = (row["description"] or "").strip()
                final_description = (
                    new_description if len(new_description) >= len(old_description)
                    else old_description
                )
                # 动态 SET 子句: 只更新有值的新结构化字段
                set_clauses = [
                    "name = ?",
                    "attributes = ?",
                    "extras = ?",
                    "aliases = ?",
                    "description = ?",
                    "source_chapter_id = COALESCE(?, source_chapter_id)",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                params: List[Any] = [
                    str(c.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    _encode_extras(extras),
                    _aliases_to_db(merged_aliases),
                    final_description,
                    source_chapter_id,
                ]
                for k, v in structured.items():
                    set_clauses.append(f"{k} = ?")
                    params.append(v)
                params.append(row["id"])
                await db.execute(
                    f"UPDATE ai_kg_characters SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                stored["characters"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": c.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "aliases": merged_aliases, "description": final_description,
                    **structured,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cols = ["project_id", "entity_id", "name", "attributes",
                        "source_chapter_id", "model_id", "extras",
                        "aliases", "description"]
                vals: List[Any] = [
                    project_id, entity_id,
                    str(c.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    source_chapter_id, model_id,
                    _encode_extras(extras),
                    _aliases_to_db(new_aliases),
                    new_description,
                ]
                for k, v in structured.items():
                    cols.append(k)
                    vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                cur = await db.execute(
                    f"INSERT INTO ai_kg_characters ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
                stored["characters"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": c.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    **structured,
                })

            # ⑩ 出场记录: 把该角色与本章的关联写入 ai_kg_character_appearances
            if source_chapter_id:
                try:
                    await db.execute(
                        """
                        INSERT OR IGNORE INTO ai_kg_character_appearances
                            (project_id, entity_id, chapter_id, role, importance)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            project_id, entity_id, source_chapter_id,
                            str(c.get("role") or "出场")[:50],
                            int(c.get("importance") or 2) if isinstance(c.get("importance"), (int, float)) else 2,
                        ),
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("character_appearances upsert skipped for %s", entity_id)

        # ---- events ----
        for e in events:
            entity_id = str(e.get("entity_id") or e.get("id") or "").strip()
            if not entity_id:
                continue
            cur = await db.execute(
                "SELECT id, attributes, aliases, description FROM ai_kg_events "
                "WHERE project_id = ? AND entity_id = ?",
                (project_id, entity_id),
            )
            row = await cur.fetchone()
            merged_attrs = {**(e.get("attributes") or {})}
            extras = _build_entity_extras(e)
            structured = {
                "in_story_time": e.get("in_story_time"),
                "chapter_time_label": e.get("chapter_time_label"),
                "importance": e.get("importance"),
            }
            structured = {k: v for k, v in structured.items() if v not in (None, "")}
            new_aliases = _extract_aliases_from_obj(e)
            new_description = str(e.get("description") or "").strip()[:500]

            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                old_aliases = _aliases_from_db(row["aliases"])
                merged_aliases = _merge_aliases(old_aliases, new_aliases)
                old_description = (row["description"] or "").strip()
                final_description = (
                    new_description if len(new_description) >= len(old_description)
                    else old_description
                )
                set_clauses = [
                    "name = ?", "attributes = ?", "extras = ?",
                    "aliases = ?", "description = ?",
                    "source_chapter_id = COALESCE(?, source_chapter_id)",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                params: List[Any] = [
                    str(e.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    _encode_extras(extras),
                    _aliases_to_db(merged_aliases),
                    final_description,
                    source_chapter_id,
                ]
                for k, v in structured.items():
                    set_clauses.append(f"{k} = ?")
                    params.append(v)
                params.append(row["id"])
                await db.execute(
                    f"UPDATE ai_kg_events SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                stored["events"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": e.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "aliases": merged_aliases, "description": final_description,
                    **structured,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cols = ["project_id", "entity_id", "name", "attributes",
                        "source_chapter_id", "model_id", "extras",
                        "aliases", "description"]
                vals: List[Any] = [
                    project_id, entity_id,
                    str(e.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    source_chapter_id, model_id,
                    _encode_extras(extras),
                    _aliases_to_db(new_aliases),
                    new_description,
                ]
                for k, v in structured.items():
                    cols.append(k)
                    vals.append(v)
                placeholders = ", ".join(["?"] * len(vals))
                cur = await db.execute(
                    f"INSERT INTO ai_kg_events ({', '.join(cols)}) VALUES ({placeholders})",
                    vals,
                )
                stored["events"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": e.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "aliases": new_aliases, "description": new_description,
                    **structured,
                })

        # ---- ④ locations ----
        for loc in locations or []:
            entity_id = str(loc.get("entity_id") or loc.get("id") or "").strip()
            if not entity_id:
                continue
            cur = await db.execute(
                "SELECT id, attributes, aliases, description FROM ai_kg_locations "
                "WHERE project_id = ? AND entity_id = ?",
                (project_id, entity_id),
            )
            row = await cur.fetchone()
            merged_attrs = {**(loc.get("attributes") or {})}
            extras = _build_entity_extras(loc)
            new_aliases = _extract_aliases_from_obj(loc)
            new_description = str(loc.get("description") or "").strip()[:500]
            if row:
                old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
                merged_attrs = {**old_attrs, **merged_attrs}
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + ([source_chapter_id] if source_chapter_id else []))
                )
                old_aliases = _aliases_from_db(row["aliases"])
                merged_aliases = _merge_aliases(old_aliases, new_aliases)
                old_description = (row["description"] or "").strip()
                final_description = (
                    new_description if len(new_description) >= len(old_description)
                    else old_description
                )
                set_clauses = [
                    "name = ?", "attributes = ?", "extras = ?",
                    "aliases = ?", "description = ?",
                    "source_chapter_id = COALESCE(?, source_chapter_id)",
                    "updated_at = CURRENT_TIMESTAMP",
                ]
                params: List[Any] = [
                    str(loc.get("name", "")).strip()[:200] or entity_id,
                    _encode_attributes(merged_attrs),
                    _encode_extras(extras),
                    _aliases_to_db(merged_aliases),
                    final_description,
                    source_chapter_id,
                ]
                if loc.get("location_type"):
                    set_clauses.append("location_type = ?")
                    params.append(str(loc["location_type"])[:50])
                params.append(row["id"])
                await db.execute(
                    f"UPDATE ai_kg_locations SET {', '.join(set_clauses)} WHERE id = ?",
                    params,
                )
                stored["locations"].append({
                    "id": row["id"], "project_id": project_id, "entity_id": entity_id,
                    "name": loc.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "location_type": loc.get("location_type"),
                    "aliases": merged_aliases, "description": final_description,
                })
            else:
                if source_chapter_id:
                    extras["source_chapter_ids"] = [source_chapter_id]
                cur = await db.execute(
                    """
                    INSERT INTO ai_kg_locations
                        (project_id, entity_id, name, location_type, attributes,
                         source_chapter_id, model_id, extras, aliases, description)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, entity_id,
                        str(loc.get("name", "")).strip()[:200] or entity_id,
                        str(loc.get("location_type") or "")[:50] or None,
                        _encode_attributes(merged_attrs),
                        source_chapter_id, model_id,
                        _encode_extras(extras),
                        _aliases_to_db(new_aliases),
                        new_description,
                    ),
                )
                stored["locations"].append({
                    "id": cur.lastrowid, "project_id": project_id, "entity_id": entity_id,
                    "name": loc.get("name", ""), "attributes": merged_attrs,
                    "source_chapter_id": source_chapter_id, "extras": extras,
                    "location_type": loc.get("location_type"),
                })

        # ---- relations: 去重插入 ----
        async def _insert_rel(
            table: str, source: str, target: str,
            relation: str, extras_payload: Dict[str, Any], **extra
        ) -> Optional[Dict[str, Any]]:
            cur = await db.execute(
                f"SELECT id FROM {table} WHERE project_id = ? "
                f"AND source_entity_id = ? AND target_entity_id = ? AND relation = ?",
                (project_id, source, target, relation),
            )
            if await cur.fetchone():
                return None
            extras = _build_relation_extras(extras_payload)
            if source_chapter_id:
                extras["source_chapter_ids"] = list(
                    set((extras.get("source_chapter_ids") or []) + [source_chapter_id])
                )
            cols = ["project_id", "source_entity_id", "target_entity_id",
                    "relation", "source_chapter_id", "extras"]
            vals: List[Any] = [project_id, source, target, relation,
                               source_chapter_id, _encode_extras(extras)]
            # ⑥ 关系结构化字段: relation_type
            rtype = extras_payload.get("relation_type")
            if rtype:
                cols.append("relation_type")
                vals.append(str(rtype)[:50])
            for k, v in extra.items():
                if k in cols:
                    continue
                cols.append(k)
                vals.append(v)
            placeholders = ", ".join(["?"] * len(vals))
            cur = await db.execute(
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
            return {
                "id": cur.lastrowid, "project_id": project_id,
                "source_entity_id": source, "target_entity_id": target,
                "relation": relation, **extra, "source_chapter_id": source_chapter_id,
                "extras": extras,
            }

        for r in character_event_relations:
            src = str(r.get("source") or r.get("source_entity_id") or "").strip()
            tgt = str(r.get("target") or r.get("target_entity_id") or "").strip()
            if not src or not tgt:
                continue
            stored_row = await _insert_rel(
                "ai_kg_character_event_relations", src, tgt,
                str(r.get("relation") or "PARTICIPATES_IN").strip() or "PARTICIPATES_IN",
                r,
                role=r.get("role") or None,
                action=r.get("action") or None,
                properties=_encode_attributes(
                    r.get("properties") if isinstance(r.get("properties"), dict) else {}
                ),
            )
            if stored_row:
                stored_row["properties"] = r.get("properties") or {}
                stored["character_event_relations"].append(stored_row)

        for r in character_relations:
            src = str(r.get("source") or r.get("source_entity_id") or "").strip()
            tgt = str(r.get("target") or r.get("target_entity_id") or "").strip()
            if not src or not tgt:
                continue
            stored_row = await _insert_rel(
                "ai_kg_character_relations", src, tgt,
                str(r.get("relation") or "").strip() or "关联",
                r,
                properties=_encode_attributes(
                    r.get("properties") if isinstance(r.get("properties"), dict) else {}
                ),
            )
            if stored_row:
                stored_row["properties"] = r.get("properties") or {}
                stored["character_relations"].append(stored_row)

        for r in event_relations:
            src = str(r.get("source") or r.get("source_entity_id") or "").strip()
            tgt = str(r.get("target") or r.get("target_entity_id") or "").strip()
            if not src or not tgt:
                continue
            stored_row = await _insert_rel(
                "ai_kg_event_relations", src, tgt,
                str(r.get("relation") or "").strip() or "关联",
                r,
                properties=_encode_attributes(
                    r.get("properties") if isinstance(r.get("properties"), dict) else {}
                ),
            )
            if stored_row:
                stored_row["properties"] = r.get("properties") or {}
                stored["event_relations"].append(stored_row)

        await db.commit()
    return stored


async def upsert_ai_kg_plot_threads(
    project_id: int,
    *,
    source_chapter_id: Optional[int],
    threads: List[Dict[str, Any]],
    model_id: Optional[int] = None,
) -> Dict[str, int]:
    """⑤ plot_threads 批量 upsert. action=create|update|resolve|drop."""
    counts = {"create": 0, "update": 0, "resolve": 0, "drop": 0, "skip": 0}
    if not threads:
        return counts
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for t in threads:
            thread_id = str(t.get("thread_id") or "").strip()
            action = str(t.get("action") or "create").strip()
            title = str(t.get("title") or "").strip()
            if not thread_id or not title:
                counts["skip"] += 1
                continue
            cur = await db.execute(
                "SELECT id, status, priority, thread_type, related_entity_ids, notes "
                "FROM ai_kg_plot_threads WHERE project_id = ? AND thread_id = ?",
                (project_id, thread_id),
            )
            row = await cur.fetchone()
            status = str(t.get("status") or "open").strip()
            if action == "drop":
                if row:
                    await db.execute(
                        "DELETE FROM ai_kg_plot_threads WHERE id = ?", (row["id"],)
                    )
                    counts["drop"] += 1
                else:
                    counts["skip"] += 1
                continue
            if action == "resolve" and row:
                await db.execute(
                    """
                    UPDATE ai_kg_plot_threads
                    SET status = 'resolved',
                        resolved_chapter_id = COALESCE(?, resolved_chapter_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (source_chapter_id, row["id"]),
                )
                counts["resolve"] += 1
                continue
            priority = t.get("priority")
            try:
                priority_v = max(1, min(5, int(priority))) if priority not in (None, "") else 3
            except (TypeError, ValueError):
                priority_v = 3
            related = t.get("related_entity_ids") or []
            if isinstance(related, str):
                try:
                    related = json.loads(related)
                except (TypeError, ValueError):
                    related = []
            related_str = json.dumps(related, ensure_ascii=False) if related else None
            notes = str(t.get("notes") or "")[:1000] or None
            ttype = str(t.get("thread_type") or "")[:50] or None
            if row:
                # update
                await db.execute(
                    """
                    UPDATE ai_kg_plot_threads
                    SET title = ?, status = ?, priority = ?, thread_type = COALESCE(?, thread_type),
                        related_entity_ids = COALESCE(?, related_entity_ids),
                        notes = COALESCE(?, notes),
                        source_chapter_id = COALESCE(?, source_chapter_id),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (title, status, priority_v, ttype, related_str, notes, source_chapter_id, row["id"]),
                )
                counts["update"] += 1
            else:
                # create
                await db.execute(
                    """
                    INSERT INTO ai_kg_plot_threads
                        (project_id, thread_id, title, thread_type, status, priority,
                         introduced_chapter_id, related_entity_ids, notes,
                         source_chapter_id, model_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id, thread_id, title, ttype, status, priority_v,
                        source_chapter_id, related_str, notes,
                        source_chapter_id, model_id,
                    ),
                )
                counts["create"] += 1
        await db.commit()
    return counts


async def list_ai_kg_plot_threads(
    project_id: int,
    *,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    threads: List[Dict[str, Any]] = []
    async with get_db() as db:
        sql = """
            SELECT id, project_id, thread_id, title, thread_type, status, priority,
                   introduced_chapter_id, resolved_chapter_id, related_entity_ids,
                   notes, source_chapter_id, model_id, created_at, updated_at
            FROM ai_kg_plot_threads
            WHERE project_id = ?
        """
        params: List[Any] = [project_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY priority DESC, created_at ASC"
        cur = await db.execute(sql, tuple(params))
        rows = await cur.fetchall()
    for r in rows:
        row = dict(r)
        if row.get("related_entity_ids"):
            try:
                row["related_entity_ids"] = json.loads(row["related_entity_ids"])
            except (TypeError, ValueError):
                row["related_entity_ids"] = []
        threads.append(row)
    return threads


# P1-#6: PlotThread 单条 CRUD
async def insert_ai_kg_plot_thread(
    project_id: int,
    *,
    thread_id: str,
    title: str,
    thread_type: str = "",
    status: str = "open",
    priority: int = 3,
    introduced_chapter_id: Optional[int] = None,
    resolved_chapter_id: Optional[int] = None,
    related_entity_ids: Optional[List[str]] = None,
    notes: str = "",
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_kg_plot_threads
                (project_id, thread_id, title, thread_type, status, priority,
                 introduced_chapter_id, resolved_chapter_id, related_entity_ids, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                thread_id,
                title.strip(),
                (thread_type or "").strip() or None,
                status,
                int(priority),
                introduced_chapter_id,
                resolved_chapter_id,
                json.dumps(related_entity_ids or [], ensure_ascii=False),
                notes or "",
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_plot_thread(
    project_id: int,
    thread_id: str,
    *,
    title: Optional[str] = None,
    thread_type: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    notes: Optional[str] = None,
    related_entity_ids: Optional[List[str]] = None,
    resolved_chapter_id: Optional[int] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        values.append(title.strip())
    if thread_type is not None:
        sets.append("thread_type = ?")
        values.append((thread_type or "").strip() or None)
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if priority is not None:
        sets.append("priority = ?")
        values.append(int(priority))
    if notes is not None:
        sets.append("notes = ?")
        values.append(notes)
    if related_entity_ids is not None:
        sets.append("related_entity_ids = ?")
        values.append(json.dumps(related_entity_ids, ensure_ascii=False))
    if resolved_chapter_id is not None:
        sets.append("resolved_chapter_id = ?")
        values.append(int(resolved_chapter_id))
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, thread_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_plot_threads SET {', '.join(sets)} "
            "WHERE project_id = ? AND thread_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_plot_thread(project_id: int, thread_id: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM ai_kg_plot_threads WHERE project_id = ? AND thread_id = ?",
            (project_id, thread_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def list_ai_kg_locations(project_id: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, project_id, entity_id, name, location_type, attributes,
                   source_chapter_id, model_id, extras, created_at, updated_at
            FROM ai_kg_locations WHERE project_id = ?
            ORDER BY name
            """,
            (project_id,),
        )
        rows = await cur.fetchall()
    for r in rows:
        row = dict(r)
        row["attributes"] = _decode_attributes(row.get("attributes"))
        row["extras"] = _decode_extras(row.get("extras"))
        out.append(row)
    return out


async def list_ai_kg_character_appearances(
    project_id: int,
    *,
    entity_id: Optional[str] = None,
    chapter_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    where = ["project_id = ?"]
    params: List[Any] = [project_id]
    if entity_id:
        where.append("entity_id = ?")
        params.append(entity_id)
    if chapter_id:
        where.append("chapter_id = ?")
        params.append(chapter_id)
    async with get_db() as db:
        cur = await db.execute(
            f"""
            SELECT id, project_id, entity_id, chapter_id, role, importance, created_at
            FROM ai_kg_character_appearances
            WHERE {' AND '.join(where)}
            ORDER BY chapter_id ASC
            """,
            tuple(params),
        )
        rows = await cur.fetchall()
    return [dict(r) for r in rows]


async def update_ai_chapter_kg_extraction(
    variant_id: int,
    *,
    entity_count: int,
    event_count: int,
) -> None:
    """① 抽取后更新变体的 kg_extracted_at + 计数.

    修复 #16: 同步把 ai_chapters.kg_extracted 置 1 + kg_extracted_at 时间戳,
    这样 list/detail 端点能直接返回"X 分钟前入图谱"等人类可读信息, 不必
    跨表 JOIN.
    """
    async with get_db() as db:
        await db.execute(
            """
            UPDATE ai_chapter_variants
            SET kg_extracted_at = CURRENT_TIMESTAMP,
                kg_entity_count = ?,
                kg_event_count = ?
            WHERE id = ?
            """,
            (int(entity_count), int(event_count), int(variant_id)),
        )
        # 同时回写 ai_chapters (kg_extracted / 时间戳)
        await db.execute(
            """
            UPDATE ai_chapters
            SET kg_extracted = 1,
                kg_extracted_at = CURRENT_TIMESTAMP,
                kg_entity_count = ?,
                kg_event_count = ?
            WHERE id = (SELECT chapter_id FROM ai_chapter_variants WHERE id = ?)
            """,
            (int(entity_count), int(event_count), int(variant_id)),
        )
        await db.commit()


async def update_ai_chapter_compass(
    chapter_id: int,
    *,
    score: Optional[float] = None,
    warnings: Optional[List[Dict[str, str]]] = None,
    summary: Optional[str] = None,
) -> None:
    """⑦ CompassAgent 评分入档."""
    sets: List[str] = []
    params: List[Any] = []
    if score is not None:
        sets.append("compass_score = ?")
        params.append(float(score))
    if warnings is not None:
        sets.append("compass_warnings = ?")
        params.append(json.dumps(warnings, ensure_ascii=False))
    if summary is not None:
        sets.append("compass_summary = ?")
        params.append(str(summary)[:2000])
    if not sets:
        return
    params.append(int(chapter_id))
    async with get_db() as db:
        await db.execute(
            f"UPDATE ai_chapters SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        await db.commit()


async def update_ai_project_themes(
    project_id: int,
    themes: List[Dict[str, Any]],
) -> None:
    """⑨ 更新项目级主题进度. themes = [{theme, progress(0-1), stage}, ...]"""
    async with get_db() as db:
        await db.execute(
            "UPDATE ai_projects SET themes_progress = ? WHERE id = ?",
            (json.dumps(themes, ensure_ascii=False), int(project_id)),
        )
        await db.commit()


async def get_ai_project_themes(project_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT themes_progress FROM ai_projects WHERE id = ?",
            (project_id,),
        )
        row = await cur.fetchone()
    if not row or not row["themes_progress"]:
        return []
    try:
        return json.loads(row["themes_progress"])
    except (TypeError, ValueError):
        return []


async def reconcile_kg_conflicts(
    project_id: int,
    *,
    chapter_id: int,
    conflicts: List[Dict[str, Any]],
) -> int:
    """② Critic 报告的 kg_conflicts 写回对应实体的 attributes.conflicts_observed.

    conflicts = [{entity, entity_type, claim, kg_fact, severity, chapter_no}, ...]
    返回写入的冲突数.
    """
    if not conflicts:
        return 0
    written = 0
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for c in conflicts:
            entity = (c.get("entity") or "").strip()
            entity_type = (c.get("entity_type") or "character").strip() or "character"
            if not entity:
                continue
            table = "ai_kg_characters" if entity_type == "character" else "ai_kg_events"
            cur = await db.execute(
                f"SELECT id, attributes, name FROM {table} "
                f"WHERE project_id = ? AND name = ? ORDER BY id LIMIT 1",
                (project_id, entity),
            )
            row = await cur.fetchone()
            if not row:
                continue
            old_attrs = _decode_attributes(row["attributes"]) if row["attributes"] else {}
            arr = old_attrs.get("conflicts_observed") or []
            if not isinstance(arr, list):
                arr = []
            arr.append({
                "chapter_no": c.get("chapter_no") or chapter_id,
                "chapter_id": chapter_id,
                "quote": str(c.get("quote") or c.get("claim") or "")[:200],
                "kg_fact": str(c.get("kg_fact") or "")[:200],
                "severity": str(c.get("severity") or "warn"),
                "resolved": False,
            })
            old_attrs["conflicts_observed"] = arr
            await db.execute(
                f"UPDATE {table} SET attributes = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (_encode_attributes(old_attrs), row["id"]),
            )
            written += 1
        await db.commit()
    return written


async def delete_ai_knowledge_graph(project_id: int) -> Dict[str, int]:
    """原子清空项目级 KG."""
    counts: Dict[str, int] = {}
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for table in (
            "ai_kg_character_appearances",
            "ai_kg_plot_threads",
            "ai_kg_locations",
            "ai_kg_character_event_relations",
            "ai_kg_character_relations",
            "ai_kg_event_relations",
            "ai_kg_events",
            "ai_kg_characters",
        ):
            cur = await db.execute(
                f"DELETE FROM {table} WHERE project_id = ?", (project_id,)
            )
            counts[table] = cur.rowcount or 0
        await db.commit()
    return counts


async def get_ai_kg_stats(project_id: int) -> Dict[str, int]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_characters WHERE project_id = ?",
            (project_id,),
        )
        char_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_events WHERE project_id = ?",
            (project_id,),
        )
        evt_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_locations WHERE project_id = ?",
            (project_id,),
        )
        loc_count = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_plot_threads "
            "WHERE project_id = ? AND status IN ('open', 'hinting', 'resolving')",
            (project_id,),
        )
        thread_open = (await cur.fetchone())[0]
        cur = await db.execute(
            "SELECT COUNT(*) FROM ai_kg_character_relations WHERE project_id = ?",
            (project_id,),
        )
        cc_count = (await cur.fetchone())[0]
    return {
        "characters": char_count,
        "events": evt_count,
        "locations": loc_count,
        "threads_open": thread_open,
        "character_relations": cc_count,
    }


# ---------------------------------------------------------------------------
# KG 节点 / 关系 CRUD (供前端手动编辑图谱)
# ---------------------------------------------------------------------------
# 设计原则:
# - 走项目级 5 表 (ai_kg_characters / events / locations / *_relations),
#   与 LLM 抽取共用同一张表, 无须做视图同步.
# - 提供 insert / update / delete 三类原子操作; service 层负责校验.
# - 删除节点时级联清理引用该节点的关系, 避免悬挂引用.


async def get_ai_kg_character_by_entity(
    project_id: int, entity_id: str
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_kg_characters WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        row = await cur.fetchone()
    return _decode_kg_character_row(row) if row else None


async def get_ai_kg_event_by_entity(
    project_id: int, entity_id: str
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_kg_events WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        row = await cur.fetchone()
    return _decode_kg_event_row(row) if row else None


async def get_ai_kg_location_by_entity(
    project_id: int, entity_id: str
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_kg_locations WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        row = await cur.fetchone()
    return _decode_kg_location_row(row) if row else None


def _decode_kg_character_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["attributes"] = _decode_attributes(d.get("attributes"))
    d["extras"] = _decode_extras(d.get("extras"))
    # RAG-lite: aliases + description 字段 (兼容旧列空值)
    d["aliases"] = _aliases_from_db(d.get("aliases"))
    d["description"] = (d.get("description") or "").strip()
    return d


def _decode_kg_event_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["attributes"] = _decode_attributes(d.get("attributes"))
    d["extras"] = _decode_extras(d.get("extras"))
    d["aliases"] = _aliases_from_db(d.get("aliases"))
    d["description"] = (d.get("description") or "").strip()
    return d


def _decode_kg_location_row(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["attributes"] = _decode_attributes(d.get("attributes"))
    d["extras"] = _decode_extras(d.get("extras"))
    d["aliases"] = _aliases_from_db(d.get("aliases"))
    d["description"] = (d.get("description") or "").strip()
    return d


async def insert_ai_kg_character(
    project_id: int,
    *,
    entity_id: str,
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    role: Optional[str] = None,
    faction: Optional[str] = None,
    status: Optional[str] = None,
    importance: Optional[int] = None,
) -> int:
    """新增人物. entity_id 在项目内必须唯一, 冲突抛 ValueError."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM ai_kg_characters WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        if await cur.fetchone():
            raise ValueError(f"人物 entity_id={entity_id} 已存在")
        cur = await db.execute(
            """
            INSERT INTO ai_kg_characters
              (project_id, entity_id, name, attributes, role, faction, status, importance)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_id, name,
                _encode_attributes(attributes or {}),
                role, faction, status, importance,
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_character(
    project_id: int,
    entity_id: str,
    *,
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    role: Optional[str] = None,
    faction: Optional[str] = None,
    status: Optional[str] = None,
    importance: Optional[int] = None,
) -> bool:
    """按 entity_id 更新人物字段. None 表示不动."""
    sets: List[str] = []
    values: List[Any] = []
    if name is not None:
        sets.append("name = ?")
        values.append(name.strip()[:200])
    if attributes is not None:
        sets.append("attributes = ?")
        values.append(_encode_attributes(attributes))
    if role is not None:
        sets.append("role = ?")
        values.append(role or None)
    if faction is not None:
        sets.append("faction = ?")
        values.append(faction or None)
    if status is not None:
        sets.append("status = ?")
        values.append(status or None)
    if importance is not None:
        sets.append("importance = ?")
        values.append(int(importance) if importance else None)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, entity_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_characters SET {', '.join(sets)} "
            "WHERE project_id = ? AND entity_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_character(
    project_id: int, entity_id: str
) -> bool:
    """删除人物, 级联清理引用该 entity_id 的关系."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "DELETE FROM ai_kg_character_event_relations "
            "WHERE project_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
            (project_id, entity_id, entity_id),
        )
        await db.execute(
            "DELETE FROM ai_kg_character_relations "
            "WHERE project_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
            (project_id, entity_id, entity_id),
        )
        await db.execute(
            "DELETE FROM ai_kg_character_appearances "
            "WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        cur = await db.execute(
            "DELETE FROM ai_kg_characters WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def insert_ai_kg_event(
    project_id: int,
    *,
    entity_id: str,
    name: str,
    attributes: Optional[Dict[str, Any]] = None,
    importance: Optional[int] = None,
    in_story_time: Optional[str] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM ai_kg_events WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        if await cur.fetchone():
            raise ValueError(f"事件 entity_id={entity_id} 已存在")
        cur = await db.execute(
            """
            INSERT INTO ai_kg_events
              (project_id, entity_id, name, attributes, importance, in_story_time)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_id, name,
                _encode_attributes(attributes or {}),
                importance, in_story_time,
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_event(
    project_id: int,
    entity_id: str,
    *,
    name: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    importance: Optional[int] = None,
    in_story_time: Optional[str] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if name is not None:
        sets.append("name = ?"); values.append(name.strip()[:200])
    if attributes is not None:
        sets.append("attributes = ?"); values.append(_encode_attributes(attributes))
    if importance is not None:
        sets.append("importance = ?"); values.append(int(importance) if importance else None)
    if in_story_time is not None:
        sets.append("in_story_time = ?"); values.append(in_story_time or None)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, entity_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_events SET {', '.join(sets)} "
            "WHERE project_id = ? AND entity_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_event(project_id: int, entity_id: str) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            "DELETE FROM ai_kg_character_event_relations "
            "WHERE project_id = ? AND target_entity_id = ?",
            (project_id, entity_id),
        )
        await db.execute(
            "DELETE FROM ai_kg_event_relations "
            "WHERE project_id = ? AND (source_entity_id = ? OR target_entity_id = ?)",
            (project_id, entity_id, entity_id),
        )
        cur = await db.execute(
            "DELETE FROM ai_kg_events WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def insert_ai_kg_location(
    project_id: int,
    *,
    entity_id: str,
    name: str,
    location_type: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT 1 FROM ai_kg_locations WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        if await cur.fetchone():
            raise ValueError(f"地点 entity_id={entity_id} 已存在")
        cur = await db.execute(
            """
            INSERT INTO ai_kg_locations
              (project_id, entity_id, name, location_type, attributes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_id, entity_id, name, location_type,
                _encode_attributes(attributes or {}),
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def update_ai_kg_location(
    project_id: int,
    entity_id: str,
    *,
    name: Optional[str] = None,
    location_type: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if name is not None:
        sets.append("name = ?"); values.append(name.strip()[:200])
    if location_type is not None:
        sets.append("location_type = ?"); values.append(location_type or None)
    if attributes is not None:
        sets.append("attributes = ?"); values.append(_encode_attributes(attributes))
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.extend([project_id, entity_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_kg_locations SET {', '.join(sets)} "
            "WHERE project_id = ? AND entity_id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_kg_location(project_id: int, entity_id: str) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        # 同步把人物.current_location_entity_id 指向该 entity 的引用清空
        await db.execute(
            "UPDATE ai_kg_characters SET current_location_entity_id = NULL "
            "WHERE project_id = ? AND current_location_entity_id = ?",
            (project_id, entity_id),
        )
        cur = await db.execute(
            "DELETE FROM ai_kg_locations WHERE project_id = ? AND entity_id = ?",
            (project_id, entity_id),
        )
        await db.commit()
    return cur.rowcount > 0


async def insert_ai_kg_character_event_relation(
    project_id: int,
    *,
    source_entity_id: str,
    target_entity_id: str,
    relation: str = "PARTICIPATES_IN",
    role: Optional[str] = None,
    action: Optional[str] = None,
    properties: Optional[Dict[str, Any]] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_kg_character_event_relations
              (project_id, source_entity_id, target_entity_id,
               relation, role, action, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id, source_entity_id, target_entity_id,
                relation, role, action,
                _encode_attributes(properties or {}),
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def delete_ai_kg_relation(
    project_id: int,
    rel_kind: str,
    rel_id: int,
) -> bool:
    """rel_kind ∈ {'ce', 'cc', 'ee'} 对应 character_event / character / event 关系表."""
    table_map = {
        "ce": "ai_kg_character_event_relations",
        "cc": "ai_kg_character_relations",
        "ee": "ai_kg_event_relations",
    }
    table = table_map.get(rel_kind)
    if not table:
        raise ValueError(f"未知的 rel_kind: {rel_kind}")
    async with get_db() as db:
        cur = await db.execute(
            f"DELETE FROM {table} WHERE id = ? AND project_id = ?",
            (rel_id, project_id),
        )
        await db.commit()
    return cur.rowcount > 0

