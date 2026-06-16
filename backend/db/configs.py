from __future__ import annotations

from typing import Any, Dict, List, Optional

from db.connection import _rows_to_dicts, get_db

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


async def get_enabled_configs_by_capability(capability: str) -> List[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM model_configs WHERE enabled = 1 AND capability = ? "
            "ORDER BY created_at DESC, id DESC",
            (capability,),
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
    capability: str = "chat",
) -> int:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO model_configs
                (name, provider, model_url, api_key, model_name, capability, enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, provider, model_url, api_key, model_name, capability, enabled),
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
    capability: str = "chat",
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
                capability = ?,
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, provider, model_url, api_key, model_name, capability, enabled, config_id),
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
