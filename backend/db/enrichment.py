from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import aiosqlite

from db.connection import _rows_to_dicts, get_db

# ---------------------------------------------------------------------------
# Novel enrichment (小说加料)
# ---------------------------------------------------------------------------


def _decode_recognition_json(raw: Optional[str]) -> Dict[str, Any]:
    """recognition_json 列的 JSON 解码, 兼容空/坏数据."""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _encode_recognition_json(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _row_to_enrichment(row: aiosqlite.Row) -> Dict[str, Any]:
    data = dict(row)
    data["recognition"] = _decode_recognition_json(data.get("recognition_json"))
    return data


async def upsert_enrichment(
    *,
    novel_id: int,
    chapter_id: int,
    summary: Optional[str] = None,
    summary_status: Optional[str] = None,
    summary_error: Optional[str] = None,
    summary_model_id: Optional[int] = None,
    recognition: Optional[Dict[str, Any]] = None,
    recognition_status: Optional[str] = None,
    recognition_error: Optional[str] = None,
    recognition_model_id: Optional[int] = None,
    rewrite_text: Optional[str] = None,
    rewrite_status: Optional[str] = None,
    rewrite_error: Optional[str] = None,
    rewrite_model_id: Optional[int] = None,
    scene_tag: Optional[str] = None,
    enrichment_intent: Optional[str] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    """按需更新 chapter_enrichments 的某些字段, 缺失则保留原值.

    仅在至少传入了 1 个可写字段时才执行写入. 三个步骤独立可写.
    """
    sets: List[str] = []
    values: List[Any] = []
    if summary is not None:
        sets.append("summary = ?")
        values.append(summary)
    if summary_status is not None:
        sets.append("summary_status = ?")
        values.append(summary_status)
    if summary_error is not None:
        sets.append("summary_error = ?")
        values.append(summary_error)
    if summary_model_id is not None:
        sets.append("summary_model_id = ?")
        values.append(int(summary_model_id))
    if recognition is not None:
        sets.append("recognition_json = ?")
        values.append(_encode_recognition_json(recognition))
    if recognition_status is not None:
        sets.append("recognition_status = ?")
        values.append(recognition_status)
    if recognition_error is not None:
        sets.append("recognition_error = ?")
        values.append(recognition_error)
    if recognition_model_id is not None:
        sets.append("recognition_model_id = ?")
        values.append(int(recognition_model_id))
    if rewrite_text is not None:
        sets.append("rewrite_text = ?")
        values.append(rewrite_text)
    if rewrite_status is not None:
        sets.append("rewrite_status = ?")
        values.append(rewrite_status)
    if rewrite_error is not None:
        sets.append("rewrite_error = ?")
        values.append(rewrite_error)
    if rewrite_model_id is not None:
        sets.append("rewrite_model_id = ?")
        values.append(int(rewrite_model_id))
    if scene_tag is not None:
        sets.append("scene_tag = ?")
        values.append(scene_tag)
    if enrichment_intent is not None:
        sets.append("enrichment_intent = ?")
        values.append(enrichment_intent)
    if status is not None:
        sets.append("status = ?")
        values.append(status)
    if error is not None:
        sets.append("error = ?")
        values.append(error)
    if not sets:
        row = await get_enrichment_by_chapter(chapter_id)
        if row:
            return row
        return {}
    # column_names 仅取写入列 (不含 updated_at 这种 SQL 片段)
    column_names = [s.split(" = ")[0] for s in sets]
    sets.append("updated_at = CURRENT_TIMESTAMP")
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        cur = await db.execute(
            "SELECT id FROM chapter_enrichments WHERE chapter_id = ?",
            (chapter_id,),
        )
        row = await cur.fetchone()
        if row:
            await db.execute(
                f"UPDATE chapter_enrichments SET {', '.join(sets)} "
                "WHERE id = ?",
                (*values, row["id"]),
            )
        else:
            placeholders = ", ".join(["?"] * len(values))
            await db.execute(
                f"INSERT INTO chapter_enrichments "
                f"(novel_id, chapter_id, {', '.join(column_names)}) "
                f"VALUES (?, ?, {placeholders})",
                (novel_id, chapter_id, *values),
            )
        await db.commit()
    return await get_enrichment_by_chapter(chapter_id) or {}


async def get_enrichment_by_chapter(chapter_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM chapter_enrichments WHERE chapter_id = ?
            """,
            (chapter_id,),
        )
        row = await cur.fetchone()
        return _row_to_enrichment(row) if row else None


async def list_enrichment_by_novel(novel_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM chapter_enrichments WHERE novel_id = ?
            """,
            (novel_id,),
        )
        rows = await cur.fetchall()
    return [_row_to_enrichment(r) for r in rows]


async def list_failed_chapter_ids(novel_id: int) -> List[int]:
    """返回任意步骤失败的章节 ID, 用于「重试失败章节」按钮."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT chapter_id FROM chapter_enrichments
            WHERE novel_id = ?
              AND (
                summary_status = 'failed'
                OR recognition_status = 'failed'
                OR rewrite_status = 'failed'
              )
            """,
            (novel_id,),
        )
        rows = await cur.fetchall()
    return [int(r["chapter_id"]) for r in rows]


async def reset_novel_enrichments(novel_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM chapter_enrichments WHERE novel_id = ?",
            (novel_id,),
        )
        await db.commit()
    return int(cur.rowcount or 0)


# ---------------------------------------------------------------------------
# enrichment_suggestions CRUD
# ---------------------------------------------------------------------------


async def insert_suggestion(
    *,
    chapter_id: int,
    novel_id: int,
    original_snapshot: str,
    rewrite_text: str,
    enrichment_id: Optional[int] = None,
    model_id: Optional[int] = None,
    summary_snapshot: Optional[str] = None,
    recognition_snapshot: Optional[str] = None,
    scene_tag: Optional[str] = None,
    enrichment_intent: Optional[str] = None,
    status: str = "applied",
) -> int:
    """新增一条加料应用记录.

    业务规则: 同时把同 chapter 当前的 applied 改为 superseded, 保留历史链.
    """
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute(
            """
            UPDATE enrichment_suggestions
            SET status = 'superseded'
            WHERE chapter_id = ? AND status = 'applied'
            """,
            (chapter_id,),
        )
        cur = await db.execute(
            """
            INSERT INTO enrichment_suggestions
                (chapter_id, novel_id, enrichment_id, original_snapshot,
                 rewrite_text, model_id, summary_snapshot, recognition_snapshot,
                 scene_tag, enrichment_intent, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chapter_id,
                novel_id,
                enrichment_id,
                original_snapshot,
                rewrite_text,
                model_id,
                summary_snapshot,
                recognition_snapshot,
                scene_tag,
                enrichment_intent,
                status,
            ),
        )
        await db.commit()
        return int(cur.lastrowid or 0)


async def list_suggestions_by_chapter(chapter_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM enrichment_suggestions
            WHERE chapter_id = ?
            ORDER BY applied_at DESC, id DESC
            """,
            (chapter_id,),
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_suggestion(suggestion_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM enrichment_suggestions WHERE id = ?",
            (suggestion_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_latest_applied_suggestion(
    chapter_id: int,
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT * FROM enrichment_suggestions
            WHERE chapter_id = ? AND status = 'applied'
            ORDER BY applied_at DESC, id DESC
            LIMIT 1
            """,
            (chapter_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def mark_suggestion_status(
    suggestion_id: int, status: str
) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "UPDATE enrichment_suggestions SET status = ? WHERE id = ?",
            (status, suggestion_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def touch_suggestion_applied(suggestion_id: int) -> bool:
    """把指定 suggestion 重新标记为 applied (用于回滚恢复)."""
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE enrichment_suggestions
            SET status = 'applied', applied_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (suggestion_id,),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_suggestions_by_novel(novel_id: int) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM enrichment_suggestions WHERE novel_id = ?",
            (novel_id,),
        )
        await db.commit()
    return int(cur.rowcount or 0)
