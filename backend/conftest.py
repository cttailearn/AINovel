import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import AsyncIterator, Iterator

import pytest
import pytest_asyncio

BACKEND_DIR = Path(__file__).parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        novels = ws / "novels"
        novels.mkdir(parents=True, exist_ok=True)
        os.environ["API_PORT"] = "0"
        yield ws


@pytest_asyncio.fixture(autouse=True)
async def _isolate_storage(temp_workspace, monkeypatch) -> AsyncIterator[None]:
    db_path = temp_workspace / "test.db"
    novels_dir = temp_workspace / "novels"
    monkeypatch.setattr("config.DATABASE_PATH", db_path)
    monkeypatch.setattr("config.NOVELS_DIR", novels_dir)
    monkeypatch.setattr("database.DATABASE_PATH", db_path)
    monkeypatch.setattr("services.novel_service.NOVELS_DIR", novels_dir)
    novels_dir.mkdir(parents=True, exist_ok=True)
    from database import init_db

    await init_db()
    yield
