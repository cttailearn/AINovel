from __future__ import annotations

from typing import Any, Dict, List, Optional

from db.connection import _rows_to_dicts, get_db

async def save_novel(
    title: str,
    author: str,
    filename: str,
    file_path: str,
    file_size: int,
    summary: Optional[str] = None,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO novels
                (title, author, filename, file_path, file_size, status, summary)
            VALUES (?, ?, ?, ?, ?, 'pending', ?)
            """,
            (title, author, filename, file_path, file_size, summary),
        )
        await db.commit()
        return cur.lastrowid or 0


async def update_novel_title_author(
    novel_id: int, title: str, author: str
) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                title = ?, author = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, author, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_novel_status(novel_id: int, status: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_novel_parse_rule(novel_id: int, rule: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                parse_rule = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (rule, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def update_novel_file_path(novel_id: int, file_path: str) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE novels SET
                file_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (file_path, novel_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def get_novel_by_id(novel_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute("SELECT * FROM novels WHERE id = ?", (novel_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_novels() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT n.*, COUNT(c.id) AS chapter_count
            FROM novels n
            LEFT JOIN chapters c ON n.id = c.novel_id
            GROUP BY n.id
            ORDER BY n.created_at DESC, n.id DESC
            """
        )
        return _rows_to_dicts(await cur.fetchall())


async def delete_novel_by_id(novel_id: int) -> bool:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        cur = await db.execute("DELETE FROM novels WHERE id = ?", (novel_id,))
        await db.commit()
        return cur.rowcount > 0


async def replace_chapters(
    novel_id: int, chapters: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    async with get_db() as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        if not chapters:
            await db.commit()
            return []
        inserted: List[Dict[str, Any]] = []
        for c in chapters:
            cur = await db.execute(
                """
                INSERT INTO chapters
                    (novel_id, chapter_number, title,
                     start_position, end_position, content)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    novel_id,
                    c["chapter_number"],
                    c["title"],
                    c["start_position"],
                    c["end_position"],
                    c.get("content"),
                ),
            )
            inserted.append(
                {
                    "id": cur.lastrowid,
                    "novel_id": novel_id,
                    "chapter_number": c["chapter_number"],
                    "title": c["title"],
                    "start_position": c["start_position"],
                    "end_position": c["end_position"],
                }
            )
        await db.commit()
        return inserted


async def get_chapters_by_novel(novel_id: int) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT id, novel_id, chapter_number, title,
                   start_position, end_position, created_at
            FROM chapters
            WHERE novel_id = ?
            ORDER BY chapter_number
            """,
            (novel_id,),
        )
        return _rows_to_dicts(await cur.fetchall())


async def update_chapter(
    novel_id: int,
    chapter_id: int,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
) -> bool:
    """更新章节的标题/正文。

    仅修改传入的字段,未传入的保持原值。编辑后内容不再回退到文件切片,
    因此把 ``start_position`` 置 0、``end_position`` 设为新内容长度。
    """
    fields: List[str] = []
    values: List[Any] = []
    if title is not None:
        fields.append("title = ?")
        values.append(title)
    if content is not None:
        fields.append("content = ?")
        # 同步起止位置: 编辑后的内容不再回退到文件切片
        fields.append("start_position = 0")
        fields.append("end_position = ?")
        values.append(len(content))
        values.append(len(content))
    if not fields:
        return False
    values.extend([chapter_id, novel_id])
    async with get_db() as db:
        cur = await db.execute(
            f"UPDATE chapters SET {', '.join(fields)} "
            "WHERE id = ? AND novel_id = ?",
            values,
        )
        await db.commit()
        return cur.rowcount > 0


async def get_chapter_with_file(
    novel_id: int, chapter_id: int
) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT c.*, n.file_path AS _file_path
            FROM chapters c
            JOIN novels n ON c.novel_id = n.id
            WHERE c.id = ? AND c.novel_id = ?
            """,
            (chapter_id, novel_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["file_path"] = data.pop("_file_path", None)
        return data
