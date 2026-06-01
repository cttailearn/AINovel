import asyncio
import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


async def read_text_file(path: str) -> str:
    def _read() -> str:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    return await asyncio.to_thread(_read)


async def read_text_slice(
    path: str, start: int, end: int
) -> str:
    def _read() -> str:
        length = max(0, end - start)
        with open(path, "rb") as f:
            f.seek(start)
            raw = f.read(length)
        return raw.decode("utf-8", errors="replace")

    return await asyncio.to_thread(_read)


async def write_bytes(path: str, data: bytes) -> None:
    def _write() -> None:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)

    await asyncio.to_thread(_write)


async def file_size(path: str) -> int:
    def _size() -> int:
        return os.path.getsize(path) if os.path.exists(path) else 0

    return await asyncio.to_thread(_size)


async def remove_file(path: Optional[str]) -> None:
    if not path:
        return

    def _remove() -> None:
        if os.path.exists(path):
            os.remove(path)

    try:
        await asyncio.to_thread(_remove)
    except OSError as exc:
        logger.warning("Failed to remove %s: %s", path, exc)
