"""AI 小说创作 — 主编排 (项目 CRUD + 三 Agent 生成 + KG 抽取).

工作流 (单章节生成)
-------------------
1. ``create_chapter_for_generation`` 创建 ai_chapters 行 (status=generating)
2. ``generate_chapter_streaming`` 串行:
   - Planner  → 3 directions (SSE: planner_done)
   - Writer x3 并行 (SSE: writer_<i>_done)
   - Critic x3 并行 (SSE: critic_<i>_done, 更新 score + critic_report)
   - chapter.status = generated, 等待用户选择
3. ``select_variant`` 锁定一个变体为 final_content
4. ``update_chapter_content`` 用户编辑保存
5. ``confirm_chapter`` 触发 EntityExtractor 抽取 → 入 ai_kg_* 表 → 状态 confirmed

所有 LLM 调用共用项目设置中的 ``model_id`` (一个 chat 模型).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

import database as db
from services.creation_agents import (
    CriticAgent,
    EntityExtractor,
    PlannerAgent,
    PlannerDirection,
    WriterAgent,
    serialize_kg_for_prompt,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CreationError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


async def list_projects() -> List[Dict[str, Any]]:
    return await db.list_ai_projects()


async def get_project_detail(project_id: int) -> Dict[str, Any]:
    project = await db.get_ai_project(project_id)
    if not project:
        raise CreationError(f"项目 {project_id} 不存在")
    chapters = await db.list_ai_chapters(project_id)
    # 补齐每个章节的变体
    for ch in chapters:
        ch["variants"] = await db.list_ai_variants(int(ch["id"]))
        # final_content 缺失时用选中变体填充
        if not ch.get("final_content") and ch.get("selected_variant_id"):
            v = next(
                (v for v in ch["variants"] if v["id"] == ch["selected_variant_id"]),
                None,
            )
            if v:
                ch["final_content"] = v.get("content") or ""
        ch["word_count"] = ch.get("word_count") or len(ch.get("final_content") or "")
    kg_stats = await db.get_ai_kg_stats(project_id)
    return {"project": project, "chapters": chapters, "kg_stats": kg_stats}


async def create_project(payload: Dict[str, Any]) -> int:
    return await db.create_ai_project(
        title=payload.get("title") or "未命名项目",
        genre=payload.get("genre", ""),
        worldview=payload.get("worldview", ""),
        outline=payload.get("outline", ""),
        initial_concepts=payload.get("initial_concepts") or [],
        style_pref=payload.get("style_pref") or {},
        model_id=payload.get("model_id"),
    )


async def update_project(project_id: int, payload: Dict[str, Any]) -> bool:
    return await db.update_ai_project(
        project_id,
        title=payload.get("title"),
        genre=payload.get("genre"),
        worldview=payload.get("worldview"),
        outline=payload.get("outline"),
        initial_concepts=payload.get("initial_concepts"),
        style_pref=payload.get("style_pref"),
        model_id=payload.get("model_id"),
        status=payload.get("status"),
    )


async def delete_project(project_id: int) -> bool:
    return await db.delete_ai_project(project_id)


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


async def get_kg(project_id: int) -> Dict[str, List[Dict[str, Any]]]:
    return await db.get_ai_knowledge_graph(project_id)


async def delete_kg(project_id: int) -> Dict[str, int]:
    return await db.delete_ai_knowledge_graph(project_id)


async def seed_kg_from_concepts(project_id: int) -> Dict[str, int]:
    """把 ai_projects.initial_concepts (用户手填) 灌入 ai_kg_characters.

    initial_concepts 格式: [{name, attributes?}, ...] — 仅支持人物种子.
    """
    project = await db.get_ai_project(project_id)
    if not project:
        raise CreationError(f"项目 {project_id} 不存在")
    concepts = project.get("initial_concepts") or []
    chars: List[Dict[str, Any]] = []
    for i, c in enumerate(concepts, start=1):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or c.get("entity_id") or "").strip()
        if not name:
            continue
        attrs = c.get("attributes") if isinstance(c.get("attributes"), dict) else {}
        chars.append({
            "entity_id": f"char_{i:03d}",
            "name": name,
            "attributes": attrs,
        })
    if not chars:
        return {"characters": 0}
    result = await db.upsert_ai_kg_from_extraction(
        project_id,
        source_chapter_id=None,
        characters=chars,
        events=[],
        character_event_relations=[],
        character_relations=[],
        event_relations=[],
    )
    return {"characters": len(result["characters"])}


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


async def _resolve_model_cfg(project: Dict[str, Any]) -> Dict[str, Any]:
    """取项目设置的 model_id 对应的 chat 模型配置.

    若项目未指定, 回落到第一个 enabled 的 chat 模型. 都不可用时抛错.
    """
    model_id = project.get("model_id")
    if model_id:
        cfg = await db.get_config_by_id(int(model_id))
        if cfg and cfg.get("enabled"):
            return cfg
        logger.warning(
            "project.model_id=%s unavailable, falling back to first chat config",
            model_id,
        )
    enabled = await db.get_enabled_configs_by_capability("chat")
    if not enabled:
        raise CreationError(
            "未配置可用的 chat 模型. 请先在「系统设置 → 模型配置」中添加并启用."
        )
    return enabled[0]


def _ascii_word_count(text: str) -> int:
    """按"可见字符"估算字数 (中英文统一: 汉字 / 非空白均计入)."""
    if not text:
        return 0
    n = 0
    for ch in text:
        if not ch.isspace():
            n += 1
    return n


# ---------------------------------------------------------------------------
# Chapter generation (orchestrator)
# ---------------------------------------------------------------------------


async def _get_last_chapter_tail(project_id: int, n_chars: int = 600) -> str:
    chapters = await db.list_ai_chapters(project_id)
    if not chapters:
        return ""
    last = chapters[-1]
    content = last.get("final_content") or ""
    if not content and last.get("selected_variant_id"):
        v = await db.get_ai_variant(int(last["selected_variant_id"]))
        if v:
            content = v.get("content") or ""
    return content[-n_chars:] if content else ""


async def _get_last_chapter_summary(project_id: int, n_chars: int = 400) -> str:
    """简化版摘要: 直接复用上一章 final_content 的前 n_chars 字符."""
    chapters = await db.list_ai_chapters(project_id)
    if not chapters:
        return ""
    last = chapters[-1]
    content = last.get("final_content") or ""
    if not content and last.get("selected_variant_id"):
        v = await db.get_ai_variant(int(last["selected_variant_id"]))
        if v:
            content = v.get("content") or ""
    return content[:n_chars] if content else ""


async def _kg_context_for(project_id: int) -> str:
    kg = await db.get_ai_knowledge_graph(project_id)
    return serialize_kg_for_prompt(kg)


async def _build_planner_inputs(
    project: Dict[str, Any], user_intent: str, chapter_no: int
) -> Dict[str, Any]:
    project_id = int(project["id"])
    return {
        "project": project,
        "kg_context": await _kg_context_for(project_id),
        "last_chapter_summary": await _get_last_chapter_summary(project_id),
        "user_intent": user_intent,
        "chapter_no": chapter_no,
    }


async def generate_chapter_streaming(
    project_id: int,
    *,
    user_intent: str = "",
    chapter_no: Optional[int] = None,
    title: str = "",
) -> AsyncIterator[Dict[str, Any]]:
    """单章节三 Agent 生成, 通过 SSE 推事件.

    事件类型:
      - start:           整章开始 (含 chapter_id, chapter_no, model_id)
      - planner_done:    Planner 完毕, 附 3 个方向
      - writer_i_done:   第 i 个方向写作完毕, 附内容预览
      - critic_i_done:   第 i 个候选审核完毕, 附 score + report
      - done:            整章完成 (chapter.status=generated)
      - error:           异常
    """
    project = await db.get_ai_project(project_id)
    if not project:
        yield {"event": "error", "message": f"项目 {project_id} 不存在"}
        return

    try:
        model_cfg = await _resolve_model_cfg(project)
    except CreationError as exc:
        yield {"event": "error", "message": str(exc)}
        return

    target_chapter_no = int(chapter_no or project.get("current_chapter_no") or 1)
    # 同一 chapter_no 已存在则视为重试, 删掉原行 + 变体
    existing = await db.list_ai_chapters(project_id)
    for ch in existing:
        if int(ch.get("chapter_no")) == target_chapter_no:
            await db.delete_ai_chapter(int(ch["id"]))

    chapter_id = await db.create_ai_chapter(
        project_id=project_id,
        chapter_no=target_chapter_no,
        title=title.strip(),
        user_intent=user_intent.strip(),
        status="generating",
    )

    yield {
        "event": "start",
        "chapter_id": chapter_id,
        "chapter_no": target_chapter_no,
        "model_id": model_cfg.get("id"),
    }

    planner = PlannerAgent()
    writer = WriterAgent()
    critic = CriticAgent()

    # ---- Planner ----
    try:
        inputs = await _build_planner_inputs(
            project, user_intent, target_chapter_no
        )
        planner_out = await planner.run(model_cfg=model_cfg, **inputs)
    except Exception as exc:  # noqa: BLE001
        logger.exception("planner failed")
        yield {"event": "error", "message": f"Planner 失败: {exc}", "chapter_id": chapter_id}
        return

    directions = planner_out.directions
    yield {
        "event": "planner_done",
        "chapter_id": chapter_id,
        "directions": [d.to_dict() for d in directions],
    }

    # 立即插入 3 个 variant 占位 (后续随 writer/critic 更新)
    variant_ids: List[int] = []
    for d in directions:
        vid = await db.insert_ai_variant(
            chapter_id=chapter_id,
            variant_index=int(d.index),
            planner_direction=(
                f"[{d.focus}] {d.title}\n{d.synopsis}\n核心事件: {d.key_event}"
            ),
            content="",
            focus_summary="",
            kg_diff={},
            critic_report={},
            score=0.0,
            model_id=model_cfg.get("id"),
        )
        variant_ids.append(vid)

    # ---- Writers (3 路并行) ----
    project_id_int = int(project["id"])
    kg_context = await _kg_context_for(project_id_int)
    last_chapter_tail = await _get_last_chapter_tail(project_id_int)

    async def _run_writer(idx: int, direction: PlannerDirection):
        out = await writer.run(
            model_cfg=model_cfg,
            project=project,
            direction=direction,
            kg_context=kg_context,
            last_chapter_tail=last_chapter_tail,
            user_intent=user_intent,
            chapter_no=target_chapter_no,
        )
        await db.update_ai_variant(
            variant_ids[idx],
            critic_report=None,
            score=0.0,
            kg_diff={"key_event": direction.key_event, "focus": direction.focus},
        )
        # 更新 content (用 SQL 覆盖: 这里 insert 已经写了空, 走一条直写)
        async with db.get_db() as conn:
            cur = await conn.execute(
                "UPDATE ai_chapter_variants SET content = ?, focus_summary = ? "
                "WHERE id = ?",
                (out.content, out.focus_summary, variant_ids[idx]),
            )
            await conn.commit()
        return idx, out, direction

    writer_results: List[Any] = [None, None, None]  # type: ignore[list-item]
    try:
        results = await asyncio.gather(
            *[_run_writer(i, d) for i, d in enumerate(directions)],
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("writer gather failed")
        yield {"event": "error", "message": f"Writer 启动失败: {exc}", "chapter_id": chapter_id}
        return

    for r in results:
        if isinstance(r, Exception):
            logger.warning("writer task failed: %s", r)
            continue
        idx, out, direction = r
        writer_results[idx] = (out, direction)
        yield {
            "event": f"writer_{idx}_done",
            "chapter_id": chapter_id,
            "variant_id": variant_ids[idx],
            "preview": out.content[:300],
            "word_count": _ascii_word_count(out.content),
        }

    # ---- Critics (3 路并行) ----
    last_summary = await _get_last_chapter_summary(project_id_int)

    async def _run_critic(idx: int, wout, direction: PlannerDirection):
        if wout is None:
            return idx, None, direction
        out = await critic.run(
            model_cfg=model_cfg,
            project=project,
            direction=direction,
            chapter_content=wout.content,
            kg_context=kg_context,
            last_chapter_summary=last_summary,
        )
        await db.update_ai_variant(
            variant_ids[idx],
            critic_report=out.to_dict(),
            score=out.overall,
        )
        return idx, out, direction

    critic_results: List[Any] = [None, None, None]  # type: ignore[list-item]
    results = await asyncio.gather(
        *[
            _run_critic(i, writer_results[i][0] if writer_results[i] else None,
                        writer_results[i][1] if writer_results[i] else directions[i])
            for i in range(3)
        ],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            logger.warning("critic task failed: %s", r)
            continue
        idx, out, _direction = r
        critic_results[idx] = out
        yield {
            "event": f"critic_{idx}_done",
            "chapter_id": chapter_id,
            "variant_id": variant_ids[idx],
            "score": out.overall if out else 0.0,
        }

    # ---- 收尾 ----
    await db.update_ai_chapter(
        chapter_id,
        status="generated",
    )
    await db.update_ai_project(
        project_id,
        current_chapter_no=target_chapter_no + 1,
    )
    yield {
        "event": "done",
        "chapter_id": chapter_id,
        "variants": variant_ids,
    }


# ---------------------------------------------------------------------------
# Chapter operations (post-generation)
# ---------------------------------------------------------------------------


async def list_chapters(project_id: int) -> List[Dict[str, Any]]:
    chapters = await db.list_ai_chapters(project_id)
    for ch in chapters:
        ch["variants"] = await db.list_ai_variants(int(ch["id"]))
    return chapters


async def get_chapter_detail(chapter_id: int) -> Dict[str, Any]:
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        raise CreationError(f"章节 {chapter_id} 不存在")
    ch["variants"] = await db.list_ai_variants(chapter_id)
    if not ch.get("final_content") and ch.get("selected_variant_id"):
        v = next(
            (v for v in ch["variants"] if v["id"] == ch["selected_variant_id"]),
            None,
        )
        if v:
            ch["final_content"] = v.get("content") or ""
    return ch


async def select_variant(chapter_id: int, variant_id: int) -> Dict[str, Any]:
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        raise CreationError(f"章节 {chapter_id} 不存在")
    v = await db.get_ai_variant(variant_id)
    if not v or int(v["chapter_id"]) != chapter_id:
        raise CreationError(f"变体 {variant_id} 不属于章节 {chapter_id}")
    final = v.get("content") or ""
    word_count = _ascii_word_count(final)
    await db.update_ai_chapter(
        chapter_id,
        selected_variant_id=variant_id,
        final_content=final,
        word_count=word_count,
        status="selected",
    )
    return await get_chapter_detail(chapter_id)


async def update_chapter_content(chapter_id: int, content: str) -> Dict[str, Any]:
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        raise CreationError(f"章节 {chapter_id} 不存在")
    word_count = _ascii_word_count(content)
    await db.update_ai_chapter(
        chapter_id,
        final_content=content,
        word_count=word_count,
        status="edited",
    )
    return await get_chapter_detail(chapter_id)


async def confirm_chapter(chapter_id: int) -> Dict[str, Any]:
    """确认章节 + 触发 EntityExtractor 抽取实体 → 入 ai_kg_*.

    抽取失败不应阻塞确认; 记录 raw 让前端能排查.
    """
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        raise CreationError(f"章节 {chapter_id} 不存在")
    project = await db.get_ai_project(int(ch["project_id"]))
    if not project:
        raise CreationError(f"项目 {ch['project_id']} 不存在")
    final = ch.get("final_content") or ""
    if not final.strip():
        raise CreationError("章节内容为空, 无法抽取知识图谱")

    extracted_count: Dict[str, int] = {
        "characters": 0, "events": 0,
        "character_event_relations": 0,
        "character_relations": 0, "event_relations": 0,
    }
    error: Optional[str] = None
    try:
        model_cfg = await _resolve_model_cfg(project)
        extractor = EntityExtractor()
        extracted = await extractor.run(
            model_cfg=model_cfg,
            chapter_text=final,
        )
        stored = await db.upsert_ai_kg_from_extraction(
            int(project["id"]),
            source_chapter_id=chapter_id,
            characters=extracted.characters,
            events=extracted.events,
            character_event_relations=extracted.character_event_relations,
            character_relations=extracted.character_relations,
            event_relations=extracted.event_relations,
            model_id=model_cfg.get("id"),
        )
        extracted_count = {
            "characters": len(stored["characters"]),
            "events": len(stored["events"]),
            "character_event_relations": len(stored["character_event_relations"]),
            "character_relations": len(stored["character_relations"]),
            "event_relations": len(stored["event_relations"]),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("KG extraction failed for chapter %s: %s", chapter_id, exc)
        error = str(exc)[:500]

    await db.update_ai_chapter(
        chapter_id,
        status="confirmed",
        kg_extracted=1,
        confirmed_at="CURRENT_TIMESTAMP",
    )
    detail = await get_chapter_detail(chapter_id)
    detail["extraction"] = {"counts": extracted_count, "error": error}
    return detail
