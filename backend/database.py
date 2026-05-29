import aiosqlite
import os
from pathlib import Path

DATABASE_PATH = Path(__file__).parent / "models.db"

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS model_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model_name TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE model_configs ADD COLUMN name TEXT NOT NULL DEFAULT ''")
        except Exception:
            pass
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS novels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT DEFAULT '未知作者',
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                parse_rule TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS chapters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                novel_id INTEGER NOT NULL,
                chapter_number INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                start_position INTEGER DEFAULT 0,
                end_position INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (novel_id) REFERENCES novels(id) ON DELETE CASCADE
            )
        """)
        
        await db.commit()

async def get_db():
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db

async def get_all_configs():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM model_configs ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

async def get_enabled_configs():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM model_configs WHERE enabled = 1 ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

async def get_config_by_provider(provider: str):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM model_configs WHERE provider = ?", (provider,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def get_config_by_id(id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM model_configs WHERE id = ?", (id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def save_config(name: str, provider: str, model_url: str, api_key: str, model_name: str, enabled: int = 1):
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO model_configs (name, provider, model_url, api_key, model_name, enabled)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, provider, model_url, api_key, model_name, enabled))
        await db.commit()
        return True
    finally:
        await db.close()

async def update_config(id: int, name: str, provider: str, model_url: str, api_key: str, model_name: str, enabled: int = 1):
    db = await get_db()
    try:
        await db.execute("""
            UPDATE model_configs SET
                name = ?,
                provider = ?,
                model_url = ?,
                api_key = ?,
                model_name = ?,
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (name, provider, model_url, api_key, model_name, enabled, id))
        await db.commit()
        return True
    finally:
        await db.close()

async def toggle_config_enabled(id: int, enabled: int):
    db = await get_db()
    try:
        await db.execute("""
            UPDATE model_configs SET
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (enabled, id))
        await db.commit()
        return True
    finally:
        await db.close()

async def delete_config_by_id(id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM model_configs WHERE id = ?", (id,))
        await db.commit()
        return True
    finally:
        await db.close()

async def save_novel(title: str, author: str, filename: str, file_path: str, file_size: int):
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO novels (title, author, filename, file_path, file_size, status)
            VALUES (?, ?, ?, ?, ?, 'pending')
        """, (title, author, filename, file_path, file_size))
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()

async def get_novel_by_id(id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM novels WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def get_all_novels():
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT n.*, 
                   COUNT(c.id) as chapter_count
            FROM novels n
            LEFT JOIN chapters c ON n.id = c.novel_id
            GROUP BY n.id
            ORDER BY n.created_at DESC
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

async def update_novel_title(id: int, title: str, author: str = None):
    db = await get_db()
    try:
        if author:
            await db.execute("""
                UPDATE novels SET title = ?, author = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (title, author, id))
        else:
            await db.execute("""
                UPDATE novels SET title = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (title, id))
        await db.commit()
        return True
    finally:
        await db.close()

async def update_novel_status(id: int, status: str):
    db = await get_db()
    try:
        await db.execute("""
            UPDATE novels SET status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (status, id))
        await db.commit()
        return True
    finally:
        await db.close()

async def update_novel_parse_rule(id: int, rule: str):
    db = await get_db()
    try:
        await db.execute("""
            UPDATE novels SET parse_rule = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (rule, id))
        await db.commit()
        return True
    finally:
        await db.close()

async def update_novel_file_path(id: int, file_path: str):
    db = await get_db()
    try:
        await db.execute("""
            UPDATE novels SET file_path = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (file_path, id))
        await db.commit()
        return True
    finally:
        await db.close()

async def delete_novel_by_id(id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM chapters WHERE novel_id = ?", (id,))
        await db.execute("DELETE FROM novels WHERE id = ?", (id,))
        await db.commit()
        return True
    finally:
        await db.close()

async def save_chapter(novel_id: int, chapter_number: int, title: str, start_position: int, end_position: int):
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO chapters (novel_id, chapter_number, title, start_position, end_position)
            VALUES (?, ?, ?, ?, ?)
        """, (novel_id, chapter_number, title, start_position, end_position))
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()

async def save_chapter_with_content(novel_id: int, chapter_number: int, title: str, content: str, start_position: int, end_position: int):
    db = await get_db()
    try:
        cursor = await db.execute("""
            INSERT INTO chapters (novel_id, chapter_number, title, content, start_position, end_position)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (novel_id, chapter_number, title, content, start_position, end_position))
        await db.commit()
        return cursor.lastrowid
    finally:
        await db.close()

async def get_chapters_by_novel(novel_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT id, novel_id, chapter_number, title, start_position, end_position, created_at
            FROM chapters WHERE novel_id = ?
            ORDER BY chapter_number
        """, (novel_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
    finally:
        await db.close()

async def get_chapter_by_id(chapter_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM chapters WHERE id = ?", (chapter_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
    finally:
        await db.close()

async def get_chapter_content(novel_id: int, chapter_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("""
            SELECT c.*, n.file_path 
            FROM chapters c
            JOIN novels n ON c.novel_id = n.id
            WHERE c.id = ? AND c.novel_id = ?
        """, (chapter_id, novel_id))
        row = await cursor.fetchone()
        if row:
            chapter = dict(row)
            file_path = chapter.pop('file_path', None)
            if file_path and os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    f.seek(chapter['start_position'])
                    content = f.read(chapter['end_position'] - chapter['start_position'])
                    chapter['content'] = content
            else:
                chapter['content'] = chapter.get('content', '')
            return chapter
        return None
    finally:
        await db.close()

async def delete_chapters_by_novel(novel_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM chapters WHERE novel_id = ?", (novel_id,))
        await db.commit()
        return True
    finally:
        await db.close()