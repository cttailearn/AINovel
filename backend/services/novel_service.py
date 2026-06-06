import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config import (
    DEFAULT_CHUNK_SIZE,
    MAX_RAW_PREVIEW_SIZE,
    NOVELS_DIR,
    PARSE_RULE_PREVIEW_LIMIT,
)
from database import (
    get_all_novels,
    get_chapter_with_file,
    get_chapters_by_novel,
    get_novel_by_id,
    replace_chapters,
    save_novel,
    update_novel_file_path,
    update_novel_parse_rule,
    update_novel_status,
    update_novel_title_author,
)
from services import file_service

logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    chapter_number: int
    title: str
    start_position: int = 0
    end_position: int = 0
    content: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "chapter_number": self.chapter_number,
            "title": self.title,
            "start_position": self.start_position,
            "end_position": self.end_position,
            "content": self.content,
        }


class ParseError(ValueError):
    """Raised when chapter parsing fails."""


def _safe_filename(raw: str) -> str:
    name = os.path.basename(raw or "").strip()
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", name)
    return name or "novel.txt"


def _read_metadata_from_header(content: bytes) -> Tuple[str, str]:
    try:
        text = content[:4096].decode("utf-8", errors="ignore")
    except Exception:
        return "", ""
    title = ""
    author = ""
    for line in text.splitlines()[:20]:
        line = line.strip()
        if not line:
            continue
        if not title and ("书名" in line or "title" in line.lower()):
            parts = re.split(r"[:：]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                title = parts[1].strip()
        if not author and ("作者" in line or "author" in line.lower()):
            parts = re.split(r"[:：]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                author = parts[1].strip()
    return title, author


def _build_summary(content: bytes, max_len: int = 140) -> str:
    try:
        text = content[:8192].decode("utf-8", errors="ignore")
    except Exception:
        return ""
    pieces: List[str] = []
    # 元数据标签：仅在「行首是标签 + 紧跟冒号」时跳过，
    # 避免把正文里出现的"书名/作者"等字样误删。
    meta_re = re.compile(
        r"^\s*(?:书\s*名|title|作\s*者|author)\s*[:：]"
    )
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if meta_re.match(stripped):
            continue
        pieces.append(stripped)
        if sum(len(p) for p in pieces) >= max_len:
            break
    summary = " ".join(pieces)
    if len(summary) > max_len:
        summary = summary[: max_len].rstrip() + "..."
    return summary


def _build_chapters_from_matches(
    content: str, matches: List[re.Match[str]]
) -> List[Chapter]:
    total = len(content)
    chapters: List[Chapter] = []

    def _normalize_start(pos: int) -> int:
        """跳过 pos 处的横向空白与换行符，返回真实内容起点。"""
        while pos < total and content[pos] in " \t\r\n":
            pos += 1
        return pos

    for idx, m in enumerate(matches):
        title_start = _normalize_start(m.start())
        if idx + 1 < len(matches):
            end = _normalize_start(matches[idx + 1].start())
        else:
            end = total
        if end < title_start:
            end = title_start
        # 标题延伸到行末（同行内的章节名/副标题等），
        # 但不超过下一章节起始位置，避免吞并下一章。
        newline_pos = content.find("\n", title_start)
        if newline_pos == -1:
            newline_pos = total
        title_end = min(newline_pos, end)
        title = content[title_start:title_end].strip()[:200]
        chapters.append(
            Chapter(
                chapter_number=idx + 1,
                title=title,
                start_position=title_start,
                end_position=end,
            )
        )
    return chapters


def parse_with_rule(content: str, rule: str) -> List[Chapter]:
    try:
        pattern = re.compile(rule, re.MULTILINE)
    except re.error as exc:
        raise ParseError(f"正则表达式无效: {exc}") from exc
    matches = list(pattern.finditer(content))
    return _build_chapters_from_matches(content, matches)


def parse_with_fixed_size(content: str, chunk_size: int) -> List[Chapter]:
    if chunk_size <= 0:
        raise ParseError("chunk_size 必须为正整数")

    paragraphs = [p for p in content.splitlines() if p.strip()]
    punctuation = set("。！？；，.!?,;\n")
    chapters: List[Chapter] = []
    chapter_no = 0
    buffer: List[str] = []
    buffer_len = 0

    def flush_buffer(force: bool = False) -> None:
        nonlocal chapter_no, buffer, buffer_len
        if not buffer:
            return
        if not force and buffer_len < chunk_size:
            return
        chapter_no += 1
        text = "\n".join(buffer).strip()
        # 标题包含段号 + 前若干字，便于在目录中区分
        snippet = text[:30].replace("\n", " ")
        title = f"第{chapter_no}段 {snippet}{'...' if len(text) > 30 else ''}"
        chapters.append(
            Chapter(
                chapter_number=chapter_no,
                title=title,
                start_position=0,
                end_position=0,
                content=text,
            )
        )
        buffer = []
        buffer_len = 0

    def cut_at_punct(text: str, target: int) -> int:
        end = min(target, len(text))
        if end >= len(text):
            return end
        window_start = max(end - 200, 0)
        for i in range(end - 1, window_start, -1):
            if text[i] in punctuation:
                return i + 1
        return end

    for para in paragraphs:
        pos = 0
        while pos < len(para):
            remaining = len(para) - pos
            if buffer and buffer_len + remaining > chunk_size:
                flush_buffer(force=True)
            if remaining > chunk_size:
                cut = cut_at_punct(para, pos + chunk_size)
                if cut <= pos:
                    cut = pos + chunk_size
                piece = para[pos:cut]
                if not piece:
                    break
                buffer.append(piece)
                buffer_len += len(piece)
                flush_buffer(force=True)
                pos = cut
            else:
                buffer.append(para[pos:])
                buffer_len += remaining
                pos = len(para)
                if buffer_len >= chunk_size:
                    flush_buffer(force=True)

    flush_buffer(force=True)
    return chapters


async def list_all_novels() -> List[Dict[str, Any]]:
    return await get_all_novels()


async def get_novel_detail(novel_id: int) -> Optional[Dict[str, Any]]:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    chapters = await get_chapters_by_novel(novel_id)
    novel["chapters"] = chapters
    novel["chapter_count"] = len(chapters)
    return novel


async def upload_novel(
    *,
    original_filename: str,
    content: bytes,
) -> Dict[str, Any]:
    if not content:
        raise ParseError("文件内容为空")

    safe = _safe_filename(original_filename)
    derived_title, derived_author = _read_metadata_from_header(content)
    if not derived_title:
        derived_title = os.path.splitext(safe)[0]
    if not derived_author:
        derived_author = "未知作者"
    derived_summary = _build_summary(content)

    placeholder_path = str(NOVELS_DIR / f"pending_{safe}")
    await file_service.write_bytes(placeholder_path, content)

    novel_id = await save_novel(
        derived_title,
        derived_author,
        safe,
        placeholder_path,
        len(content),
        derived_summary,
    )

    final_path = str(NOVELS_DIR / f"{novel_id}_{safe}")
    await file_service.write_bytes(final_path, content)
    await file_service.remove_file(placeholder_path)
    await update_novel_file_path(novel_id, final_path)

    return {
        "id": novel_id,
        "title": derived_title,
        "author": derived_author,
        "filename": safe,
        "status": "pending",
        "summary": derived_summary,
        "message": "上传成功",
    }


async def update_novel_info(
    novel_id: int,
    title: Optional[str] = None,
    author: Optional[str] = None,
) -> bool:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return False
    new_title = title.strip() if title else novel["title"]
    new_author = author.strip() if author else novel["author"]
    return await update_novel_title_author(novel_id, new_title, new_author)


async def delete_novel(novel_id: int) -> bool:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return False
    await file_service.remove_file(novel.get("file_path"))
    return await _delete_novel_db(novel_id)


async def _delete_novel_db(novel_id: int) -> bool:
    from database import delete_novel_by_id
    return await delete_novel_by_id(novel_id)


async def parse_chapters_by_rule(
    novel_id: int, rule: str
) -> Dict[str, Any]:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ParseError("小说不存在")
    file_path = novel.get("file_path")
    if not file_path:
        raise ParseError("文件路径缺失")

    content = await file_service.read_text_file(file_path)
    chapters = parse_with_rule(content, rule)
    return await _commit_chapters(novel_id, chapters, rule)


async def parse_chapters_fixed_size(
    novel_id: int, chunk_size: int
) -> Dict[str, Any]:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ParseError("小说不存在")
    file_path = novel.get("file_path")
    if not file_path:
        raise ParseError("文件路径缺失")

    content = await file_service.read_text_file(file_path)
    chapters = parse_with_fixed_size(content, chunk_size)
    return await _commit_chapters(novel_id, chapters, f"fixed:{chunk_size}")


async def preview_chapters_by_rule(
    novel_id: int, rule: str, limit: int = PARSE_RULE_PREVIEW_LIMIT
) -> Dict[str, Any]:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ParseError("小说不存在")
    file_path = novel.get("file_path")
    if not file_path:
        raise ParseError("文件路径缺失")
    content = await file_service.read_text_file(file_path)
    chapters = parse_with_rule(content, rule)
    return {
        "chapters_found": len(chapters),
        "preview": [c.as_dict() for c in chapters[:limit]],
    }


async def _commit_chapters(
    novel_id: int, chapters: List[Chapter], rule: str
) -> Dict[str, Any]:
    payload = [c.as_dict() for c in chapters]
    inserted = await replace_chapters(novel_id, payload)
    count = len(inserted)
    await update_novel_status(novel_id, "parsed" if count else "pending")
    if count:
        await update_novel_parse_rule(novel_id, rule)
    return {
        "success": count > 0,
        "chapters_found": count,
        "chapters": inserted,
        "message": (
            f"成功解析 {count} 个章节" if count else "未找到匹配的章节"
        ),
    }


async def get_chapter(novel_id: int, chapter_id: int) -> Optional[Dict[str, Any]]:
    chapter = await get_chapter_with_file(novel_id, chapter_id)
    if not chapter:
        return None
    stored_content = chapter.get("content")
    if stored_content:
        chapter["content"] = stored_content
        return chapter
    file_path = chapter.get("file_path")
    if file_path and await file_service.file_size(file_path) > 0:
        chapter["content"] = await file_service.read_text_slice(
            file_path, chapter["start_position"], chapter["end_position"]
        )
    else:
        chapter["content"] = ""
    return chapter


async def get_raw_content(
    novel_id: int, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> Optional[Dict[str, Any]]:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    file_path = novel.get("file_path")
    if not file_path:
        raise ParseError("文件路径缺失")

    size = await file_service.file_size(file_path)
    if size > MAX_RAW_PREVIEW_SIZE:
        raise ParseError(
            f"文件过大({size} bytes)，超过原始预览上限 {MAX_RAW_PREVIEW_SIZE}"
        )
    content = await file_service.read_text_file(file_path)
    return {
        "id": novel["id"],
        "title": novel["title"],
        "author": novel["author"],
        "status": novel["status"],
        "total_length": len(content),
        "chunks": smart_chunk_content(content, chunk_size),
    }


def smart_chunk_content(content: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> List[Dict[str, Any]]:
    if chunk_size <= 0:
        chunk_size = DEFAULT_CHUNK_SIZE
    if not content:
        return []

    paragraphs = [p for p in content.splitlines() if p.strip()]
    punctuation = set("。！？；，.!?,;")
    chunks: List[Dict[str, Any]] = []
    state = {"number": 0}

    def title_for(text: str) -> str:
        return text[:10] if len(text) >= 10 else text

    def add(text: str) -> None:
        text = text.strip()
        if not text:
            return
        state["number"] += 1
        chunks.append(
            {
                "chunk_number": state["number"],
                "title": title_for(text),
                "content": text,
            }
        )

    current = ""
    for para in paragraphs:
        if len(para) > chunk_size:
            if current:
                add(current)
                current = ""
            start = 0
            while start < len(para):
                end = min(start + chunk_size, len(para))
                if end < len(para):
                    window_start = max(start, end - 200)
                    cut = end
                    for i in range(window_start, end):
                        if para[i] in punctuation:
                            cut = i + 1
                            break
                    end = cut
                add(para[start:end])
                start = end
            continue
        if current and len(current) + len(para) + 1 > chunk_size:
            add(current)
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    if current:
        add(current)
    return chunks
