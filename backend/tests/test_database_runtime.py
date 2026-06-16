from __future__ import annotations

import pytest

import database


@pytest.mark.asyncio
async def test_init_db_sets_latest_user_version():
    async with database.get_db() as db:
        cur = await db.execute("PRAGMA user_version")
        row = await cur.fetchone()
    assert int(row[0] or 0) == database.LATEST_USER_VERSION


@pytest.mark.asyncio
async def test_get_db_reuses_shared_connection():
    async with database.get_db() as db1:
        async with database.get_db() as db2:
            assert db1 is db2
