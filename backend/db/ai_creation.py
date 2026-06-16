from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import aiosqlite

from db.connection import get_db

# ============================================================================
# AI 小说创作 (AI Creation) CRUD
# ============================================================================


def _decode_ai_json(raw: Any) -> Any:
    """AI 创作模块通用 JSON 解码 (initial_concepts / style_pref / kg_diff / critic_report)."""
    if not raw:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _row_to_ai_project(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    data["initial_concepts"] = _decode_ai_json(data.get("initial_concepts")) or []
    data["style_pref"] = _decode_ai_json(data.get("style_pref")) or {}
    return data


def _row_to_ai_chapter(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    # 修复 #16: 把 0/1 标量转成更友好的展示值, 默认值兜底
    data["kg_extracted"] = int(data.get("kg_extracted") or 0)
    data["kg_entity_count"] = int(data.get("kg_entity_count") or 0)
    data["kg_event_count"] = int(data.get("kg_event_count") or 0)
    return data


def _row_to_ai_variant(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    data["kg_diff"] = _decode_ai_json(data.get("kg_diff")) or {}
    data["critic_report"] = _decode_ai_json(data.get("critic_report")) or {}
    data["kg_entity_count"] = int(data.get("kg_entity_count") or 0)
    data["kg_event_count"] = int(data.get("kg_event_count") or 0)
    # P0-#3: 显式转换 superseded 为 bool/int, 方便前端判断
    data["superseded"] = int(data.get("superseded") or 0)
    data["generation_round"] = int(data.get("generation_round") or 1)
    return data


# --- ai_projects ----------------------------------------------------------


async def create_ai_project(
    *,
    title: str,
    genre: str = "",
    worldview: str = "",
    outline: str = "",
    initial_concepts: Optional[List[Dict[str, Any]]] = None,
    style_pref: Optional[Dict[str, Any]] = None,
    model_id: Optional[int] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_projects
                (title, genre, worldview, outline, initial_concepts,
                 style_pref, model_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                genre.strip(),
                worldview.strip(),
                outline.strip(),
                json.dumps(initial_concepts or [], ensure_ascii=False),
                json.dumps(style_pref or {}, ensure_ascii=False),
                model_id,
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def list_ai_projects() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_projects ORDER BY created_at DESC, id DESC"
        )
        return [_row_to_ai_project(r) for r in await cur.fetchall()]


async def get_ai_project(project_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_projects WHERE id = ?", (project_id,)
        )
        row = await cur.fetchone()
        return _row_to_ai_project(row) if row else None


async def get_ai_project_id(project_id: int) -> Optional[int]:
    """修复 #7: 轻量校验项目是否存在, 只返回 id 字段.

    比 ``get_ai_project`` 节省全部行数据反序列化 + JSON 解析 (initial_concepts /
    style_pref 是 JSON 列). 用于 KG/PlotThread 端点的存在性校验.
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT id FROM ai_projects WHERE id = ?", (project_id,)
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def update_ai_project(
    project_id: int,
    *,
    title: Optional[str] = None,
    genre: Optional[str] = None,
    worldview: Optional[str] = None,
    outline: Optional[str] = None,
    initial_concepts: Optional[List[Dict[str, Any]]] = None,
    style_pref: Optional[Dict[str, Any]] = None,
    model_id: Optional[int] = None,
    current_chapter_no: Optional[int] = None,
    status: Optional[str] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        values.append(title.strip())
    if genre is not None:
        sets.append("genre = ?")
        values.append(genre.strip())
    if worldview is not None:
        sets.append("worldview = ?")
        values.append(worldview.strip())
    if outline is not None:
        sets.append("outline = ?")
        values.append(outline.strip())
    if initial_concepts is not None:
        sets.append("initial_concepts = ?")
        values.append(json.dumps(initial_concepts, ensure_ascii=False))
    if style_pref is not None:
        sets.append("style_pref = ?")
        values.append(json.dumps(style_pref, ensure_ascii=False))
    if model_id is not None:
        sets.append("model_id = ?")
        values.append(model_id)
    if current_chapter_no is not None:
        sets.append("current_chapter_no = ?")
        values.append(int(current_chapter_no))
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.append(project_id)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_projects SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_project(project_id: int) -> bool:
    """级联删除 (依赖外键 ON DELETE CASCADE)."""
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute("DELETE FROM ai_projects WHERE id = ?", (project_id,))
        await db.commit()
    return cur.rowcount > 0


# --- ai_chapters ----------------------------------------------------------


async def create_ai_chapter(
    *,
    project_id: int,
    chapter_no: int,
    title: str = "",
    user_intent: str = "",
    status: str = "draft",
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_chapters
                (project_id, chapter_no, title, user_intent, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, chapter_no, title.strip(), user_intent.strip(), status),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def get_ai_chapter(chapter_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapters WHERE id = ?", (chapter_id,)
        )
        row = await cur.fetchone()
        return _row_to_ai_chapter(row) if row else None


async def list_ai_chapters(project_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapters WHERE project_id = ? ORDER BY chapter_no ASC",
            (project_id,),
        )
        return [_row_to_ai_chapter(r) for r in await cur.fetchall()]


async def next_available_chapter_no(project_id: int) -> int:
    """修复 #15: 取下一个可用的 chapter_no (1-based).

    行为: 找出 project 内已用的所有 chapter_no, 返回 min(>=1 不在已用集合的最小值).
    这样用户删除第 5 章后, 重新生成会补到 5 而不是直接用 current_chapter_no 跳过.
    """
    async with get_db() as db:
        cur = await db.execute(
            "SELECT chapter_no FROM ai_chapters WHERE project_id = ? ORDER BY chapter_no ASC",
            (project_id,),
        )
        used = {int(r[0]) for r in await cur.fetchall()}
    n = 1
    while n in used:
        n += 1
    return n


async def update_ai_chapter(
    chapter_id: int,
    *,
    title: Optional[str] = None,
    user_intent: Optional[str] = None,
    status: Optional[str] = None,
    selected_variant_id: Optional[int] = None,
    final_content: Optional[str] = None,
    word_count: Optional[int] = None,
    kg_extracted: Optional[int] = None,
    kg_extracted_at: Optional[str] = None,
    kg_entity_count: Optional[int] = None,
    kg_event_count: Optional[int] = None,
    confirmed_at: Optional[str] = None,
    chapter_no: Optional[int] = None,
    clear_selected_variant: bool = False,
    clear_final_content: bool = False,
    clear_compass: bool = False,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if title is not None:
        sets.append("title = ?")
        values.append(title.strip())
    if user_intent is not None:
        sets.append("user_intent = ?")
        values.append(user_intent.strip())
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if selected_variant_id is not None:
        sets.append("selected_variant_id = ?")
        values.append(int(selected_variant_id))
    if final_content is not None:
        sets.append("final_content = ?")
        values.append(final_content)
    if word_count is not None:
        sets.append("word_count = ?")
        values.append(int(word_count))
    if kg_extracted is not None:
        sets.append("kg_extracted = ?")
        values.append(int(kg_extracted))
    if kg_extracted_at is not None:
        sets.append("kg_extracted_at = ?")
        values.append(kg_extracted_at)
    if kg_entity_count is not None:
        sets.append("kg_entity_count = ?")
        values.append(int(kg_entity_count))
    if kg_event_count is not None:
        sets.append("kg_event_count = ?")
        values.append(int(kg_event_count))
    if confirmed_at is not None:
        sets.append("confirmed_at = ?")
        values.append(confirmed_at)
    if chapter_no is not None:
        sets.append("chapter_no = ?")
        values.append(int(chapter_no))
    if clear_selected_variant:
        sets.append("selected_variant_id = NULL")
    if clear_final_content:
        sets.append("final_content = NULL")
    if clear_compass:
        sets.extend([
            "compass_score = NULL",
            "compass_warnings = NULL",
            "compass_summary = NULL",
        ])
    if not sets:
        return False
    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.append(chapter_id)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_chapters SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_ai_chapter(chapter_id: int) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await _null_ai_chapter_references(db, chapter_id)
        cur = await db.execute(
            "DELETE FROM ai_chapters WHERE id = ?", (chapter_id,)
        )
        await db.commit()
    return cur.rowcount > 0


async def _null_ai_chapter_references(
    db: aiosqlite.Connection,
    chapter_id: int,
) -> None:
    """把所有指向该章节的 KG/线索引用置空.

    删除章节与"重新生成同一章"都要做这个步骤, 避免旧正文残留的 source_chapter_id
    继续指向已被覆盖的新章节内容.
    """
    for table in (
        "ai_kg_characters",
        "ai_kg_events",
        "ai_kg_character_event_relations",
        "ai_kg_character_relations",
        "ai_kg_event_relations",
        "ai_kg_locations",
        "ai_kg_plot_threads",
        "ai_kg_character_appearances",
    ):
        await db.execute(
            f"UPDATE {table} SET source_chapter_id = NULL "
            "WHERE source_chapter_id = ?",
            (chapter_id,),
        )
    await db.execute(
        "UPDATE ai_kg_characters SET first_appearance_chapter_id = NULL "
        "WHERE first_appearance_chapter_id = ?",
        (chapter_id,),
    )
    await db.execute(
        "UPDATE ai_kg_plot_threads SET introduced_chapter_id = NULL "
        "WHERE introduced_chapter_id = ?",
        (chapter_id,),
    )
    await db.execute(
        "UPDATE ai_kg_plot_threads SET resolved_chapter_id = NULL "
        "WHERE resolved_chapter_id = ?",
        (chapter_id,),
    )
    await db.execute(
        "UPDATE ai_kg_character_relations SET start_chapter_id = NULL "
        "WHERE start_chapter_id = ?",
        (chapter_id,),
    )
    await db.execute(
        "UPDATE ai_kg_character_relations SET end_chapter_id = NULL "
        "WHERE end_chapter_id = ?",
        (chapter_id,),
    )


async def prepare_ai_chapter_for_regeneration(
    chapter_id: int,
    *,
    title: str = "",
    user_intent: str = "",
) -> int:
    """把章节重置为 generating, 保留旧变体历史并返回新的 generation_round.

    兼容旧库里 ``UNIQUE(chapter_id, variant_index)`` 的约束: 归档旧轮次时把
    variant_index 平移到保留区间, 为新一轮的 ``variant_index=0`` 腾出位置.
    """
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        current_round = 0
        cur = await db.execute(
            "SELECT MAX(generation_round) AS r FROM ai_chapter_variants WHERE chapter_id = ?",
            (chapter_id,),
        )
        row = await cur.fetchone()
        if row and row["r"] is not None:
            current_round = int(row["r"])
        if current_round > 0:
            await db.execute(
                """
                UPDATE ai_chapter_variants
                SET superseded = 1,
                    superseded_at = CURRENT_TIMESTAMP,
                    variant_index = variant_index + (? * 1000)
                WHERE chapter_id = ? AND generation_round = ? AND superseded = 0
                """,
                (current_round, chapter_id, current_round),
            )
        await _null_ai_chapter_references(db, chapter_id)
        await db.execute(
            """
            UPDATE ai_chapters
            SET title = ?,
                user_intent = ?,
                status = 'generating',
                selected_variant_id = NULL,
                final_content = NULL,
                word_count = 0,
                kg_extracted = 0,
                kg_extracted_at = NULL,
                kg_entity_count = 0,
                kg_event_count = 0,
                compass_score = NULL,
                compass_warnings = NULL,
                compass_summary = NULL,
                confirmed_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title.strip(), user_intent.strip(), chapter_id),
        )
        await db.commit()
    return current_round + 1


# --- ai_chapter_variants --------------------------------------------------


async def insert_ai_variant(
    *,
    chapter_id: int,
    variant_index: int,
    planner_direction: str = "",
    content: str = "",
    focus_summary: str = "",
    kg_diff: Optional[Dict[str, Any]] = None,
    critic_report: Optional[Dict[str, Any]] = None,
    score: float = 0.0,
    model_id: Optional[int] = None,
    generation_round: int = 1,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO ai_chapter_variants
                (chapter_id, variant_index, planner_direction, content,
                 focus_summary, kg_diff, critic_report, score, model_id,
                 generation_round)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                int(variant_index),
                planner_direction.strip(),
                content,
                focus_summary.strip(),
                json.dumps(kg_diff or {}, ensure_ascii=False),
                json.dumps(critic_report or {}, ensure_ascii=False),
                float(score),
                model_id,
                int(generation_round),
            ),
        )
        await db.commit()
    return int(cur.lastrowid or 0)


async def list_ai_variants(
    chapter_id: int, include_superseded: bool = False
) -> List[Dict[str, Any]]:
    """列出变体. 默认只返回当前 round 的活跃变体; 历史版本需显式 include."""
    async with get_db() as db:
        if include_superseded:
            cur = await db.execute(
                "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
                "ORDER BY generation_round DESC, variant_index ASC",
                (chapter_id,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
                "AND superseded = 0 "
                "ORDER BY generation_round DESC, variant_index ASC",
                (chapter_id,),
            )
        return [_row_to_ai_variant(r) for r in await cur.fetchall()]


async def list_ai_variants_full_history(chapter_id: int) -> List[Dict[str, Any]]:
    """列出全部变体 (含历史), 按轮次/索引排序. 供 P0-#3 版本历史 UI 使用."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapter_variants WHERE chapter_id = ? "
            "ORDER BY generation_round DESC, variant_index ASC, created_at DESC",
            (chapter_id,),
        )
        return [_row_to_ai_variant(r) for r in await cur.fetchall()]


async def archive_ai_variants(chapter_id: int, round_no: int) -> int:
    """P0-#3: 重新生成时把当前轮次的所有变体标 superseded=1.
    返回被归档的变体数.
    """
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE ai_chapter_variants
            SET superseded = 1, superseded_at = CURRENT_TIMESTAMP
            WHERE chapter_id = ? AND generation_round = ? AND superseded = 0
            """,
            (chapter_id, round_no),
        )
        await db.commit()
    return int(cur.rowcount or 0)


async def max_variant_round(chapter_id: int) -> int:
    """返回该章节已生成的最大轮次. 用于 P0-#3 决定下一轮 round 编号."""
    async with get_db() as db:
        cur = await db.execute(
            "SELECT MAX(generation_round) AS r FROM ai_chapter_variants "
            "WHERE chapter_id = ?",
            (chapter_id,),
        )
        row = await cur.fetchone()
        if not row or row["r"] is None:
            return 0
        return int(row["r"])


async def get_ai_variant(variant_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM ai_chapter_variants WHERE id = ?", (variant_id,)
        )
        row = await cur.fetchone()
        return _row_to_ai_variant(row) if row else None


async def update_ai_variant(
    variant_id: int,
    *,
    critic_report: Optional[Dict[str, Any]] = None,
    score: Optional[float] = None,
    kg_diff: Optional[Dict[str, Any]] = None,
) -> bool:
    sets: List[str] = []
    values: List[Any] = []
    if critic_report is not None:
        sets.append("critic_report = ?")
        values.append(json.dumps(critic_report, ensure_ascii=False))
    if score is not None:
        sets.append("score = ?")
        values.append(float(score))
    if kg_diff is not None:
        sets.append("kg_diff = ?")
        values.append(json.dumps(kg_diff, ensure_ascii=False))
    if not sets:
        return False
    values.append(variant_id)
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE ai_chapter_variants SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await db.commit()
    return cur.rowcount > 0


async def delete_variants_by_chapter(chapter_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM ai_chapter_variants WHERE chapter_id = ?",
            (chapter_id,),
        )
        await db.commit()
    return int(cur.rowcount or 0)
