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
    """按字符偏移读取文件切片。

    入参 ``start`` / ``end`` 是 UTF-8 解码后字符串中的**字符偏移**
    （与 ``re.Match.start()`` / ``len(text)`` 一致），而不是字节偏移。
    中文等多字节字符若按字节读取会落在字符中间导致乱码，因此这里
    统一读取全文后按字符切片。
    """
    def _read() -> str:
        if end <= start:
            return ""
        with open(path, "rb") as f:
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        lo = max(0, min(start, len(text)))
        hi = max(lo, min(end, len(text)))
        return text[lo:hi]

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
