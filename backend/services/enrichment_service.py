"""Novel enrichment (小说加料) service.

Each chapter goes through 3 independent LLM steps:

* ``summary``     - 100~200 字章节摘要
* ``recognition`` - 抽取登场人物 / 关键事件 / 场景标签 (JSON)
* ``rewrite``     - 结合 summary + recognition + 改写规则, 重写正文

The service does NOT depend on the knowledge graph: enrichment is per-chapter
and per-novel-id only, so it never touches the ``characters / events /
*_relations`` tables. This keeps the two pipelines independent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Tuple

from config import ENRICHMENT_DEFAULT_CONCURRENCY
from database import (
    get_chapter_with_file,
    get_chapters_by_novel,
    get_config_by_id,
    get_enrichment_by_chapter,
    get_novel_by_id,
    list_enrichment_by_novel,
    reset_novel_enrichments,
    upsert_enrichment,
)
from schemas import ENRICHMENT_STEPS
from services import ai_service, file_service, prompt_service
from services.novel_service import get_chapter

logger = logging.getLogger(__name__)


# 改写规则分类名 (与 prompt_service.PROMPT_CATEGORIES 中的 key 对齐)
REWRITE_GENERAL_CATEGORY = "rewrite_general"
REWRITE_SCENE_CATEGORY = "rewrite_scene"

# 内置 prompt key 映射, 与 DEFAULT_PROMPTS 中的 key 一致
STEP_PROMPT_KEY = {
    "summary": "enrichment.summary",
    "recognition": "enrichment.recognition",
    "rewrite": "enrichment.rewrite",
}


# ---------------------------------------------------------------------------
# 内部辅助
# ---------------------------------------------------------------------------


async def _resolve_model_cfg(model_id: int) -> Dict[str, Any]:
    cfg = await get_config_by_id(model_id)
    if not cfg:
        raise ValueError(f"模型配置不存在: {model_id}")
    if not int(cfg.get("enabled") or 0):
        raise ValueError("该模型当前未启用")
    return cfg


async def _resolve_prompt(
    step: str,
    override_prompt: Optional[str] = None,
    prompt_key: Optional[str] = None,
) -> Dict[str, Any]:
    """加载 prompt 模板, 优先级: override_prompt > DB > 内置默认."""
    if override_prompt and override_prompt.strip():
        return {
            "name": f"{step}.override",
            "system_prompt": "",
            "user_prompt_template": override_prompt,
            "temperature": 0.3,
            "max_tokens": 2400,
            "is_override": True,
        }
    key = prompt_key or STEP_PROMPT_KEY.get(step)
    if not key:
        return {
            "system_prompt": "",
            "user_prompt_template": "",
            "temperature": 0.3,
            "max_tokens": 2400,
        }
    try:
        tmpl = await prompt_service.get_active_prompt_by_key(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB prompt lookup failed for %s: %s", key, exc)
        tmpl = None
    if not tmpl:
        tmpl = prompt_service.get_default_prompt(key) or {}
    return tmpl


def _chapter_text(content: Optional[str]) -> str:
    if not content:
        return ""
    return content.strip()


def _enrich_status(states: Dict[str, str]) -> str:
    """汇总 summary/recognition/rewrite 三态到总状态."""
    if any(v == "running" for v in states.values()):
        return "running"
    if all(v == "done" for v in states.values()):
        return "done"
    if any(v == "failed" for v in states.values()) and not any(
        v in ("running", "pending") for v in states.values()
    ):
        return "partial"
    return "pending"


def _truncate(text: str, limit: int) -> str:
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


# ---------------------------------------------------------------------------
# 公开接口: 列表 / 详情 / 编辑
# ---------------------------------------------------------------------------


async def list_progress(novel_id: int) -> Dict[str, Any]:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ValueError("小说不存在")
    chapters = await get_chapters_by_novel(novel_id)
    enrichments = {e["chapter_id"]: e for e in await list_enrichment_by_novel(novel_id)}

    items: List[Dict[str, Any]] = []
    summary_done = recognition_done = rewrite_done = 0
    summary_failed = recognition_failed = rewrite_failed = 0
    total = len(chapters)
    for c in chapters:
        e = enrichments.get(c["id"]) or {}
        ss = e.get("summary_status") or "pending"
        rs = e.get("recognition_status") or "pending"
        ws = e.get("rewrite_status") or "pending"
        if ss == "done":
            summary_done += 1
        elif ss == "failed":
            summary_failed += 1
        if rs == "done":
            recognition_done += 1
        elif rs == "failed":
            recognition_failed += 1
        if ws == "done":
            rewrite_done += 1
        elif ws == "failed":
            rewrite_failed += 1
        items.append(
            {
                "chapter_id": c["id"],
                "novel_id": novel_id,
                "chapter_number": c["chapter_number"],
                "title": c["title"],
                "word_count": int(
                    (e.get("rewrite_text") and len(e["rewrite_text"])) or 0
                )
                if e.get("rewrite_text")
                else int(c.get("end_position") or 0) - int(c.get("start_position") or 0),
                "summary_status": ss,
                "recognition_status": rs,
                "rewrite_status": ws,
                "status": _enrich_status(
                    {"summary": ss, "recognition": rs, "rewrite": ws}
                ),
                "scene_tag": e.get("scene_tag"),
            }
        )

    overall = 0.0
    if total > 0:
        # 三步平均 done 比例, 一章三步全完成 = 100%
        overall = (summary_done + recognition_done + rewrite_done) / (3 * total)

    return {
        "novel_id": novel_id,
        "total": total,
        "summary_done": summary_done,
        "recognition_done": recognition_done,
        "rewrite_done": rewrite_done,
        "summary_failed": summary_failed,
        "recognition_failed": recognition_failed,
        "rewrite_failed": rewrite_failed,
        "overall_percent": round(overall * 100, 1),
        "items": items,
    }


async def get_detail(chapter_id: int) -> Optional[Dict[str, Any]]:
    chapter = await get_chapter_with_file_by_chapter_id(chapter_id)
    if not chapter:
        return None
    e = await get_enrichment_by_chapter(chapter_id) or {}
    content = await _read_chapter_content(chapter)
    ss = e.get("summary_status") or "pending"
    rs = e.get("recognition_status") or "pending"
    ws = e.get("rewrite_status") or "pending"
    return {
        "chapter_id": chapter["id"],
        "novel_id": chapter["novel_id"],
        "chapter_number": chapter["chapter_number"],
        "title": chapter["title"],
        "word_count": len(content),
        "content": content,
        "summary": e.get("summary"),
        "summary_status": ss,
        "summary_error": e.get("summary_error"),
        "summary_model_id": e.get("summary_model_id"),
        "recognition": e.get("recognition") or {},
        "recognition_status": rs,
        "recognition_error": e.get("recognition_error"),
        "recognition_model_id": e.get("recognition_model_id"),
        "rewrite_text": e.get("rewrite_text"),
        "rewrite_status": ws,
        "rewrite_error": e.get("rewrite_error"),
        "rewrite_model_id": e.get("rewrite_model_id"),
        "scene_tag": e.get("scene_tag"),
        "status": _enrich_status({"summary": ss, "recognition": rs, "rewrite": ws}),
        "error": e.get("error"),
        "updated_at": str(e.get("updated_at")) if e.get("updated_at") else None,
    }


async def update_manual(
    chapter_id: int,
    *,
    summary: Optional[str] = None,
    rewrite_text: Optional[str] = None,
    scene_tag: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    chapter = await get_chapter_with_file_by_chapter_id(chapter_id)
    if not chapter:
        return None
    fields: Dict[str, Any] = {}
    if summary is not None:
        fields["summary"] = summary
        # 手动编辑也视为完成
        fields["summary_status"] = "done"
        fields["summary_error"] = None
    if rewrite_text is not None:
        fields["rewrite_text"] = rewrite_text
        fields["rewrite_status"] = "done"
        fields["rewrite_error"] = None
    if scene_tag is not None:
        fields["scene_tag"] = scene_tag
    if not fields:
        return await get_enrichment_by_chapter(chapter_id)
    fields["status"] = "partial"  # 由 get_detail 重新计算
    await upsert_enrichment(novel_id=chapter["novel_id"], chapter_id=chapter_id, **fields)
    return await get_enrichment_by_chapter(chapter_id)


# ---------------------------------------------------------------------------
# 单章单步执行
# ---------------------------------------------------------------------------


async def run_step(
    chapter_id: int,
    step: str,
    *,
    model_config_id: int,
    prompt_key: Optional[str] = None,
    override_prompt: Optional[str] = None,
    general_rule: Optional[str] = None,
    scene_rule: Optional[str] = None,
) -> Dict[str, Any]:
    """执行单章的单个步骤, 完成后回写数据库."""
    if step not in ENRICHMENT_STEPS:
        raise ValueError(f"未知步骤: {step}")
    chapter = await get_chapter_with_file_by_chapter_id(chapter_id)
    if not chapter:
        raise ValueError("章节不存在")
    novel_id = chapter["novel_id"]
    content = await _read_chapter_content(chapter)
    if not content:
        raise ValueError("章节内容为空, 请先在「工作台」解析章节")

    model_cfg = await _resolve_model_cfg(model_config_id)
    tmpl = await _resolve_prompt(step, override_prompt, prompt_key)

    # 写入 running 状态 (best-effort, 失败不影响主流程)
    await upsert_enrichment(
        novel_id=novel_id,
        chapter_id=chapter_id,
        **{f"{step}_status": "running", f"{step}_error": None},
    )

    started = time.monotonic()
    try:
        if step == "summary":
            result_text = await _step_summary(content, chapter, tmpl, model_cfg)
            await upsert_enrichment(
                novel_id=novel_id,
                chapter_id=chapter_id,
                summary=result_text,
                summary_status="done",
                summary_error=None,
                summary_model_id=model_config_id,
            )
            return _build_run_response(
                chapter_id=chapter_id, step=step, success=True,
                status="done", message="摘要生成完成",
                model_id=model_config_id, started=started,
                summary=result_text,
            )
        if step == "recognition":
            payload = await _step_recognition(content, chapter, tmpl, model_cfg)
            scene_tag = (payload.get("scene_tag") or "").strip() or None
            await upsert_enrichment(
                novel_id=novel_id,
                chapter_id=chapter_id,
                recognition=payload,
                recognition_status="done",
                recognition_error=None,
                recognition_model_id=model_config_id,
                scene_tag=scene_tag,
            )
            return _build_run_response(
                chapter_id=chapter_id, step=step, success=True,
                status="done", message="识别完成",
                model_id=model_config_id, started=started,
                recognition=payload, scene_tag=scene_tag,
            )
        # rewrite
        existing = await get_enrichment_by_chapter(chapter_id) or {}
        rewrite_text = await _step_rewrite(
            content, chapter, tmpl, model_cfg,
            summary=existing.get("summary") or "",
            recognition=existing.get("recognition") or {},
            general_rule=general_rule,
            scene_rule=scene_rule,
        )
        await upsert_enrichment(
            novel_id=novel_id,
            chapter_id=chapter_id,
            rewrite_text=rewrite_text,
            rewrite_status="done",
            rewrite_error=None,
            rewrite_model_id=model_config_id,
        )
        return _build_run_response(
            chapter_id=chapter_id, step=step, success=True,
            status="done", message="改写完成",
            model_id=model_config_id, started=started,
            rewrite_text=rewrite_text,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("run_step %s failed for chapter %s", step, chapter_id)
        err_msg = str(exc)[:500]
        await upsert_enrichment(
            novel_id=novel_id,
            chapter_id=chapter_id,
            **{f"{step}_status": "failed", f"{step}_error": err_msg},
        )
        return _build_run_response(
            chapter_id=chapter_id, step=step, success=False,
            status="failed", message=err_msg,
            model_id=model_config_id, started=started,
        )


# ---------------------------------------------------------------------------
# 批处理 (SSE 进度)
# ---------------------------------------------------------------------------


ProgressCallback = Callable[[Dict[str, Any]], Awaitable[None]]


async def run_batch(
    novel_id: int,
    *,
    model_config_id: int,
    steps: List[str],
    chapter_ids: Optional[List[int]] = None,
    concurrency: int = ENRICHMENT_DEFAULT_CONCURRENCY,
    skip_existing: bool = True,
    general_rule: Optional[str] = None,
    scene_rule: Optional[str] = None,
    on_event: Optional[ProgressCallback] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> None:
    """整本跑指定步骤, 通过 on_event 推送进度."""
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ValueError("小说不存在")
    chapters = await get_chapters_by_novel(novel_id)
    if chapter_ids:
        target_set = set(int(x) for x in chapter_ids)
        chapters = [c for c in chapters if c["id"] in target_set]
    if not chapters:
        return

    steps = [s for s in steps if s in ENRICHMENT_STEPS]
    if not steps:
        return

    sem = asyncio.Semaphore(max(1, concurrency))
    total_chapters = len(chapters)
    # step -> {done, total}
    step_progress: Dict[str, Dict[str, int]] = {
        s: {"done": 0, "total": total_chapters} for s in steps
    }

    async def emit(payload: Dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            await on_event(payload)
        except Exception:  # noqa: BLE001
            logger.warning("on_event callback raised", exc_info=True)

    # 先发一个"开始"事件, 方便前端立即刷新
    await emit({
        "event": "start",
        "novel_id": novel_id,
        "total": total_chapters,
        "steps": steps,
        "step_progress": step_progress,
    })

    async def _run_one_step(chapter: Dict[str, Any], step: str) -> None:
        # 取消检查
        if should_cancel and should_cancel():
            await emit({
                "event": "cancelled",
                "step": step,
                "chapter_id": chapter["id"],
            })
            return
        if skip_existing:
            e = await get_enrichment_by_chapter(chapter["id"])
            if e and e.get(f"{step}_status") == "done":
                step_progress[step]["done"] += 1
                await emit({
                    "event": "skip",
                    "step": step,
                    "chapter_id": chapter["id"],
                    "chapter_number": chapter["chapter_number"],
                    "title": chapter["title"],
                    "step_progress": step_progress,
                })
                return
        async with sem:
            await emit({
                "event": "chapter_start",
                "step": step,
                "chapter_id": chapter["id"],
                "chapter_number": chapter["chapter_number"],
                "title": chapter["title"],
                "step_progress": step_progress,
            })
            try:
                await run_step(
                    chapter["id"],
                    step,
                    model_config_id=model_config_id,
                    general_rule=general_rule,
                    scene_rule=scene_rule,
                )
                step_progress[step]["done"] += 1
                await emit({
                    "event": "chapter_done",
                    "step": step,
                    "chapter_id": chapter["id"],
                    "chapter_number": chapter["chapter_number"],
                    "title": chapter["title"],
                    "success": True,
                    "step_progress": step_progress,
                })
            except Exception as exc:  # noqa: BLE001
                # run_step 内部已经把 *_status 标 failed, 这里只汇报
                step_progress[step]["done"] += 1
                await emit({
                    "event": "chapter_done",
                    "step": step,
                    "chapter_id": chapter["id"],
                    "chapter_number": chapter["chapter_number"],
                    "title": chapter["title"],
                    "success": False,
                    "error": str(exc)[:300],
                    "step_progress": step_progress,
                })

    for step in steps:
        await emit({
            "event": "step_start",
            "step": step,
            "total": total_chapters,
        })
        tasks = [asyncio.create_task(_run_one_step(c, step)) for c in chapters]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await emit({
            "event": "step_done",
            "step": step,
            "total": total_chapters,
            "done": step_progress[step]["done"],
        })

    await emit({
        "event": "complete",
        "novel_id": novel_id,
        "total": total_chapters,
        "step_progress": step_progress,
    })


# ---------------------------------------------------------------------------
# 重置 / 导出
# ---------------------------------------------------------------------------


async def reset_novel(novel_id: int) -> int:
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ValueError("小说不存在")
    return await reset_novel_enrichments(novel_id)


async def export_enriched_txt(novel_id: int) -> Tuple[str, str]:
    """把已加料的章节拼成一份 TXT, 返回 (filename, content)."""
    novel = await get_novel_by_id(novel_id)
    if not novel:
        raise ValueError("小说不存在")
    chapters = await get_chapters_by_novel(novel_id)
    enrichments = {e["chapter_id"]: e for e in await list_enrichment_by_novel(novel_id)}

    parts: List[str] = []
    used_rewrite = 0
    used_original = 0
    for c in chapters:
        e = enrichments.get(c["id"]) or {}
        text = (e.get("rewrite_text") or "").strip()
        if text and e.get("rewrite_status") == "done":
            used_rewrite += 1
        else:
            # 回退到原章节正文
            text = await _read_chapter_content(c)
            used_original += 1
        parts.append(f"\n\n{c['title']}\n\n{text.strip()}\n")
    body = "".join(parts).strip() + "\n"
    header = (
        f"# 《{novel['title']}》 加料版\n"
        f"# 作者: {novel.get('author') or '未知作者'}\n"
        f"# 来源: 原文 + AI 加料改写\n"
        f"# 统计: 加料章节 {used_rewrite} / 原文兜底 {used_original} / 总章节 {len(chapters)}\n"
        f"# 注意: 本文件由 AI 加料工作台自动生成, 仅供学习/研究使用.\n\n"
    )
    safe_title = re.sub(r"[\\/:*?\"<>|\r\n]", "_", str(novel["title"])).strip() or "novel"
    return f"{safe_title}.enriched.txt", header + body


# ---------------------------------------------------------------------------
# 私有: 章节内容读取
# ---------------------------------------------------------------------------


async def _read_chapter_content(chapter: Dict[str, Any]) -> str:
    """优先用 chapter.content, 否则按 start/end 切片读原文."""
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


async def get_chapter_with_file_by_chapter_id(chapter_id: int) -> Optional[Dict[str, Any]]:
    """通过 chapter_id 查 chapter + 关联 file_path, 不依赖 novel_id."""
    from database import get_db

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
# 私有: 三个步骤的具体 LLM 调用
# ---------------------------------------------------------------------------


def _build_user_prompt(
    tmpl: Dict[str, Any], variables: Dict[str, str]
) -> str:
    body = (tmpl.get("user_prompt_template") or "").format(**variables)
    return body


async def _call_llm(
    model_cfg: Dict[str, Any], tmpl: Dict[str, Any], user_prompt: str
) -> str:
    return await ai_service.chat_completion(
        provider=model_cfg["provider"],
        model_url=model_cfg["model_url"],
        api_key=model_cfg["api_key"],
        model_name=model_cfg["model_name"],
        system_prompt=tmpl.get("system_prompt", ""),
        user_prompt=user_prompt,
        temperature=float(tmpl.get("temperature") or 0.3),
        max_tokens=int(tmpl.get("max_tokens") or 2400),
        retries=2,
    )


async def _step_summary(
    content: str, chapter: Dict[str, Any], tmpl: Dict[str, Any], model_cfg: Dict[str, Any]
) -> str:
    user_prompt = _build_user_prompt(
        tmpl,
        {
            "chapter_title": chapter.get("title") or "",
            "chapter_text": _truncate(content, 12000),
        },
    )
    raw = await _call_llm(model_cfg, tmpl, user_prompt)
    return raw.strip()


_RECOGNITION_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _parse_recognition(raw: str) -> Dict[str, Any]:
    """解析识别结果. 期望结构: {characters, events, scene_tag}.

    对 LLM 输出尽量宽松: 兼容 JSON 对象 / 代码块 / 数组包裹等.
    """
    if not raw:
        raise ValueError("AI 响应为空")
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _RECOGNITION_FENCE.sub("", cleaned).strip()
    parsed: Any = None
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = ai_service.parse_json_object(cleaned)
    if parsed is None:
        # 兜底: 取首个 JSON 块
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        # 数组被返回的话, 套一层
        if isinstance(parsed, list):
            return {"characters": parsed, "events": [], "scene_tag": ""}
        raise ValueError("识别结果不是合法的 JSON 对象")

    def _norm_list(value: Any) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            return []
        out: List[Dict[str, str]] = []
        for item in value:
            if isinstance(item, str):
                out.append({"name": item, "description": ""})
            elif isinstance(item, dict):
                name = str(item.get("name") or item.get("character") or "").strip()
                desc = str(item.get("description") or item.get("desc") or "").strip()
                if not name:
                    continue
                out.append({"name": name, "description": desc})
        return out

    return {
        "characters": _norm_list(parsed.get("characters")),
        "events": _norm_list(parsed.get("events")),
        "scene_tag": str(parsed.get("scene_tag") or "").strip(),
    }


async def _step_recognition(
    content: str, chapter: Dict[str, Any], tmpl: Dict[str, Any], model_cfg: Dict[str, Any]
) -> Dict[str, Any]:
    user_prompt = _build_user_prompt(
        tmpl,
        {
            "chapter_title": chapter.get("title") or "",
            "chapter_text": _truncate(content, 12000),
        },
    )
    raw = await _call_llm(model_cfg, tmpl, user_prompt)
    return _parse_recognition(raw)


async def _step_rewrite(
    content: str,
    chapter: Dict[str, Any],
    tmpl: Dict[str, Any],
    model_cfg: Dict[str, Any],
    *,
    summary: str,
    recognition: Dict[str, Any],
    general_rule: Optional[str] = None,
    scene_rule: Optional[str] = None,
) -> str:
    recognition_json = json.dumps(recognition or {}, ensure_ascii=False, indent=2)
    user_prompt = _build_user_prompt(
        tmpl,
        {
            "chapter_title": chapter.get("title") or "",
            "chapter_text": _truncate(content, 16000),
            "summary": summary or "",
            "recognition_json": recognition_json,
            "scene_tag": (recognition or {}).get("scene_tag") or "",
            "general_rule": general_rule or "",
            "scene_rule": scene_rule or "",
        },
    )
    raw = await _call_llm(model_cfg, tmpl, user_prompt)
    return raw.strip()


def _build_run_response(
    *,
    chapter_id: int,
    step: str,
    success: bool,
    status: str,
    message: str,
    model_id: int,
    started: float,
    summary: Optional[str] = None,
    recognition: Optional[Dict[str, Any]] = None,
    rewrite_text: Optional[str] = None,
    scene_tag: Optional[str] = None,
) -> Dict[str, Any]:
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "success": success,
        "status": status,
        "message": message,
        "chapter_id": chapter_id,
        "step": step,
        "duration_ms": duration_ms,
        "model_id": model_id,
        "summary": summary,
        "recognition": recognition,
        "rewrite_text": rewrite_text,
        "scene_tag": scene_tag,
    }


# Re-export for back-compat with callers expecting get_chapter
__all__ = [
    "ENRICHMENT_STEPS",
    "STEP_PROMPT_KEY",
    "list_progress",
    "get_detail",
    "update_manual",
    "run_step",
    "run_batch",
    "reset_novel",
    "export_enriched_txt",
    "ProgressCallback",
]