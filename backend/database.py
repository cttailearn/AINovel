import aiosqlite
import os

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "models.db")

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