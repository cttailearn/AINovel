"""共享连接 / 通用辅助 — 拆分自原 ``database.py``.

``db.configs / novels / common / novel_kg / enrichment / ai_creation / ai_kg``
全部从这个模块导入 ``get_db / rows_to_dicts / get_table_columns`` 等, 避免
``db.*`` 内部再 ``import database`` 造成循环依赖.

``database.py`` 自身会 ``from db.connection import *`` 并把它重新导出,
因此 ``from database import get_db`` 这种历史用法继续可用.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Iterable, List, Optional

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)

LATEST_USER_VERSION = 1

_shared_db: Optional[aiosqlite.Connection] = None
_shared_db_path: Optional[str] = None
_shared_db_lock = asyncio.Lock()


def rows_to_dicts(rows: Iterable[aiosqlite.Row]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]


# 兼容旧命名
_rows_to_dicts = rows_to_dicts


async def get_table_columns(
    db: aiosqlite.Connection, table: str
) -> List[str]:
    cur = await db.execute(f"PRAGMA table_info({table})")
    rows = await cur.fetchall()
    return [row[1] for row in rows]


# 兼容旧命名
_get_table_columns = get_table_columns


def _safe_remove(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Failed to remove file %s: %s", path, exc)


def _decode_attributes(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _encode_attributes(value: Any) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _encode_extras(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _decode_extras(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


async def open_db(force_reopen: bool = False) -> aiosqlite.Connection:
    """获取共享 aiosqlite 连接 (修复 #6).

    使用 ``check_same_thread=False`` + ``busy_timeout`` + WAL, 配合 FastAPI
    lifespan 关闭.  ``force_reopen=True`` 用于 ``conftest`` 测试切库.
    """
    global _shared_db, _shared_db_path

    # 用 ``config`` 模块实时解析, 而不是闭包内的 ``DATABASE_PATH`` 引用,
    # 这样 ``monkeypatch.setattr("config.DATABASE_PATH", ...)`` 能被立即看到.
    import config as _config

    db_path = str(_config.DATABASE_PATH)
    async with _shared_db_lock:
        if (
            not force_reopen
            and _shared_db is not None
            and _shared_db_path == db_path
        ):
            return _shared_db

        if _shared_db is not None:
            try:
                await _shared_db.close()
            except Exception:
                logger.warning("close old shared db failed", exc_info=True)
            finally:
                _shared_db = None
                _shared_db_path = None

        Path(_config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(_config.DATABASE_PATH, check_same_thread=False)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.commit()
        _shared_db = db
        _shared_db_path = db_path
        return db


async def close_db() -> None:
    global _shared_db, _shared_db_path
    async with _shared_db_lock:
        if _shared_db is not None:
            await _shared_db.close()
        _shared_db = None
        _shared_db_path = None


@asynccontextmanager
async def get_db() -> AsyncIterator[aiosqlite.Connection]:
    db = await open_db()
    yield db
