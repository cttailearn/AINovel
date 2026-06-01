import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


SCHEMA_STATEMENTS: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS model_configs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        provider TEXT NOT NULL,
        model_url TEXT NOT NULL,
        api_key TEXT NOT NULL,
        model_name TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS novels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        author TEXT NOT NULL DEFAULT '未知作者',
        filename TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending',
        parse_rule TEXT,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        novel_id INTEGER NOT NULL,
        chapter_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        content TEXT,
        start_position INTEGER NOT NULL DEFAULT 0,
        end_position INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE,
        UNIQUE (novel_id, chapter_number)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_chapters_novel ON chapters(novel_id)",
    "CREATE INDEX IF NOT EXISTS idx_novels_created ON novels(created_at DESC)",
]


async def init_db() -> None:
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        for stmt in SCHEMA_STATEMENTS:
            await db.execute(stmt)
        await db.commit()


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    try:
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
    finally:
        await db.close()


def _rows_to_dicts(rows: Iterable[aiosqlite.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


async def get_all_configs() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs ORDER BY created_at DESC, id DESC"
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_enabled_configs() -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs WHERE enabled = 1 "
            "ORDER BY created_at DESC, id DESC"
        )
        return _rows_to_dicts(await cur.fetchall())


async def get_config_by_id(config_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs WHERE id = ?", (config_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def save_config(
    name: str,
    provider: str,
    model_url: str,
    api_key: str,
    model_name: str,
    enabled: int = 1,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO model_configs
                (name, provider, model_url, api_key, model_name, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, provider, model_url, api_key, model_name, enabled),
        )
        await db.commit()
        return cur.lastrowid or 0


async def update_config(
    config_id: int,
    name: str,
    provider: str,
    model_url: str,
    api_key: str,
    model_name: str,
    enabled: int,
) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE model_configs SET
                name = ?,
                provider = ?,
                model_url = ?,
                api_key = ?,
                model_name = ?,
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, provider, model_url, api_key, model_name, enabled, config_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def toggle_config_enabled(config_id: int, enabled: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            """
            UPDATE model_configs SET
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (enabled, config_id),
        )
        await db.commit()
        return cur.rowcount > 0


async def delete_config_by_id(config_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "DELETE FROM model_configs WHERE id = ?", (config_id,)
        )
        await db.commit()
        return cur.rowcount > 0


async def save_novel(
    title: str,
    author: str,
    filename: str,
    file_path: str,
    file_size: int,
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO novels
                (title, author, filename, file_path, file_size, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
            """,
            (title, author, filename, file_path, file_size),
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


def _safe_remove(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Failed to remove file %s: %s", path, exc)
