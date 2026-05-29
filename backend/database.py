import aiosqlite
import os

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "models.db")

async def init_db():
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS model_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                provider TEXT NOT NULL UNIQUE,
                model_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model_name TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        cursor = await db.execute("SELECT * FROM model_configs")
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

async def save_config(provider: str, model_url: str, api_key: str, model_name: str):
    db = await get_db()
    try:
        await db.execute("""
            INSERT INTO model_configs (provider, model_url, api_key, model_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                model_url = excluded.model_url,
                api_key = excluded.api_key,
                model_name = excluded.model_name,
                updated_at = CURRENT_TIMESTAMP
        """, (provider, model_url, api_key, model_name))
        await db.commit()
        return True
    finally:
        await db.close()

async def delete_config(provider: str):
    db = await get_db()
    try:
        await db.execute("DELETE FROM model_configs WHERE provider = ?", (provider,))
        await db.commit()
        return True
    finally:
        await db.close()