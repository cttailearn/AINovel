"""加料应用历史服务: apply / revert / history / diff.

与 ``enrichment_service`` 解耦, 只关心 enrichment_suggestions 表和
chapters.content 的回写, 不直接触发 LLM.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from database import (
    get_chapter_with_file,
    get_db,
    get_enrichment_by_chapter,
    get_latest_applied_suggestion,
    get_suggestion,
    insert_suggestion,
    list_suggestions_by_chapter,
    mark_suggestion_status,
    touch_suggestion_applied,
    update_chapter,
)
from services import file_service
from services.diff_service import compute_diff

logger = logging.getLogger(__name__)


async def _read_chapter_content(chapter: Dict[str, Any]) -> str:
    """与 enrichment_service 保持一致的章节正文读取."""
    if chapter.get("content"):
        return chapter["content"]
    file_path = chapter.get("file_path")
    if file_path and await file_service.file_size(file_path) > 0:
        try:
            return await file_service.read_text_slice(
                file_path,
                int(chapter.get("start_position") or 0),
                int(chapter.get("end_position") or 0),
            )
        except Exception:  # noqa: BLE001
            return ""
    return ""


async def _get_chapter_by_id(chapter_id: int) -> Optional[Dict[str, Any]]:
    """通过 chapter_id 查 chapter + 关联 novel file_path, 不依赖 novel_id."""
    async with get_db() as db:
        cur = await db.execute(
            """
            SELECT c.*, n.file_path AS _file_path
            FROM chapters c
            JOIN novels n ON c.novel_id = n.id
            WHERE c.id = ?
            """,
            (chapter_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        data = dict(row)
        data["file_path"] = data.pop("_file_path", None)
        return data


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


async def diff_chapter(
    chapter_id: int,
    *,
    max_chars: int = 60_000,
) -> Dict[str, Any]:
    """对比 chapters.content (current) 与 chapter_enrichments.rewrite_text."""
    chapter = await _get_chapter_by_id(chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    enrichment = await get_enrichment_by_chapter(chapter_id) or {}
    original = await _read_chapter_content(chapter)
    rewrite = (enrichment.get("rewrite_text") or "").strip()
    if not rewrite:
        raise ValueError("该章节尚未生成改写结果, 无法做 diff")
    if max_chars and len(original) + len(rewrite) > max_chars * 2:
        segs, stats, truncated = compute_diff(original[:max_chars], rewrite[:max_chars])
    else:
        segs, stats, truncated = compute_diff(original, rewrite)
    return {
        "chapter_id": chapter_id,
        "novel_id": chapter["novel_id"],
        "original_length": stats["original_length"],
        "rewrite_length": stats["rewrite_length"],
        "added_length": stats["added_length"],
        "removed_length": stats["removed_length"],
        "segments": segs,
        "truncated": truncated,
    }


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------


async def apply_chapter(
    chapter_id: int,
    *,
    rewrite_text: Optional[str] = None,
    enrichment_intent: Optional[str] = None,
) -> Dict[str, Any]:
    """把当前 chapter_enrichments.rewrite_text (或传入的 rewrite_text) 写入 chapters.content.

    业务规则:
    1. 用当前 chapters.content 作为 original_snapshot 留底
    2. 写入新内容
    3. 落 enrichment_suggestions, 旧 applied 自动变 superseded
    4. 计算新增/删除长度, 返回供前端展示
    """
    chapter = await _get_chapter_by_id(chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    enrichment = await get_enrichment_by_chapter(chapter_id) or {}
    target_rewrite = (
        rewrite_text
        if (rewrite_text is not None and str(rewrite_text).strip())
        else (enrichment.get("rewrite_text") or "")
    )
    target_rewrite = (target_rewrite or "").strip()
    if not target_rewrite:
        raise ValueError("该章节尚无 rewrite_text, 请先在 AI 加料中生成改写")

    original_content = await _read_chapter_content(chapter)
    if target_rewrite == original_content.strip():
        raise ValueError("改写内容与原文完全相同, 无需应用")

    # 0) 如果传了 intent, 同时更新 chapter_enrichments.enrichment_intent
    intent_to_record = (
        enrichment_intent
        if enrichment_intent is not None
        else enrichment.get("enrichment_intent")
    )

    # 1) 写 chapters.content
    await update_chapter(
        chapter["novel_id"],
        chapter_id,
        content=target_rewrite,
    )

    # 2) 落 suggestion 记录
    suggestion_id = await insert_suggestion(
        chapter_id=chapter_id,
        novel_id=chapter["novel_id"],
        original_snapshot=original_content,
        rewrite_text=target_rewrite,
        enrichment_id=enrichment.get("id"),
        model_id=enrichment.get("rewrite_model_id"),
        summary_snapshot=enrichment.get("summary"),
        recognition_snapshot=json.dumps(
            enrichment.get("recognition") or {}, ensure_ascii=False
        )
        or None,
        scene_tag=enrichment.get("scene_tag"),
        enrichment_intent=intent_to_record,
        status="applied",
    )

    # 3) 计算 added / removed
    _, stats, _ = compute_diff(original_content, target_rewrite)

    return {
        "success": True,
        "message": "已应用加料到原文",
        "chapter_id": chapter_id,
        "suggestion_id": suggestion_id,
        "applied_at": "",
        "original_length": stats["original_length"],
        "rewrite_length": stats["rewrite_length"],
        "added_length": stats["added_length"],
        "removed_length": stats["removed_length"],
        "enrichment_intent": intent_to_record,
    }


# ---------------------------------------------------------------------------
# revert
# ---------------------------------------------------------------------------


async def revert_chapter(
    chapter_id: int,
    *,
    target_suggestion_id: Optional[int] = None,
) -> Dict[str, Any]:
    """回滚到指定 suggestion 的内容.

    业务规则:
    * 若指定 ``target_suggestion_id``:
        - 把当前 applied 的 status 改为 reverted
        - 把 target 的 status 改为 applied, applied_at = now
        - chapters.content = target.rewrite_text
    * 若未指定:
        - 找到最近一条 status='superseded' 的记录, 把它"激活"成 applied
        - chapters.content = 那条记录的 rewrite_text
    """
    chapter = await _get_chapter_by_id(chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    current_applied = await get_latest_applied_suggestion(chapter_id)
    if not current_applied:
        raise ValueError("当前没有已应用的加料, 无法回滚")

    target: Optional[Dict[str, Any]] = None
    if target_suggestion_id is not None:
        target = await get_suggestion(int(target_suggestion_id))
        if not target or int(target.get("chapter_id") or 0) != chapter_id:
            raise ValueError("目标 suggestion 不存在或不属于该章节")
    else:
        # 找上一条 superseded
        all_rows = await list_suggestions_by_chapter(chapter_id)
        for row in all_rows:
            if row.get("status") == "superseded":
                target = row
                break
        if not target:
            raise ValueError("没有更早的版本可回滚")

    if int(target.get("id") or 0) == int(current_applied.get("id") or 0):
        raise ValueError("目标版本与当前一致, 无需回滚")

    # 1) 当前 applied -> reverted
    await mark_suggestion_status(int(current_applied["id"]), "reverted")
    # 2) target -> applied
    await touch_suggestion_applied(int(target["id"]))
    # 3) 写 chapters.content
    await update_chapter(
        chapter["novel_id"],
        chapter_id,
        content=str(target.get("rewrite_text") or ""),
    )

    return {
        "success": True,
        "message": "已回滚到历史版本",
        "chapter_id": chapter_id,
        "reverted_suggestion_id": int(current_applied["id"]),
        "new_applied_suggestion_id": int(target["id"]),
        "new_content_length": len(str(target.get("rewrite_text") or "")),
    }


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


async def list_history(chapter_id: int) -> Dict[str, Any]:
    chapter = await _get_chapter_by_id(chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    rows = await list_suggestions_by_chapter(chapter_id)
    items: List[Dict[str, Any]] = []
    for r in rows:
        original_snapshot = str(r.get("original_snapshot") or "")
        rewrite_text = str(r.get("rewrite_text") or "")
        # 不在前端回传全文, 节省带宽
        _, stats, _ = compute_diff(original_snapshot, rewrite_text)
        items.append(
            {
                "id": int(r["id"]),
                "chapter_id": int(r["chapter_id"]),
                "novel_id": int(r["novel_id"]),
                "enrichment_id": r.get("enrichment_id"),
                "model_id": r.get("model_id"),
                "scene_tag": r.get("scene_tag"),
                "status": r.get("status") or "applied",
                "applied_at": str(r.get("applied_at")) if r.get("applied_at") else None,
                "reverted_at": str(r.get("reverted_at")) if r.get("reverted_at") else None,
                "original_length": stats["original_length"],
                "rewrite_length": stats["rewrite_length"],
                "added_length": stats["added_length"],
                "removed_length": stats["removed_length"],
            }
        )
    return {
        "chapter_id": chapter_id,
        "novel_id": chapter["novel_id"],
        "items": items,
    }


# ---------------------------------------------------------------------------
# 辅助: 给 enrichment_service.get_detail 用, 拿到当前 applied 信息
# ---------------------------------------------------------------------------


async def get_current_applied_info(chapter_id: int) -> Dict[str, Any]:
    """返回当前章节的 applied suggestion 简信息 (供详情接口填充)."""
    row = await get_latest_applied_suggestion(chapter_id)
    if not row:
        return {
            "has_applied": False,
            "applied_suggestion_id": None,
            "applied_at": None,
            "content_is_enriched": False,
        }
    return {
        "has_applied": True,
        "applied_suggestion_id": int(row["id"]),
        "applied_at": str(row.get("applied_at")) if row.get("applied_at") else None,
        "content_is_enriched": True,
    }
