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
    CompassAgent,
    CriticAgent,
    EntityExtractor,
    PlannerAgent,
    PlannerDirection,
    ThreadExtractor,
    WriterAgent,
    generate_chapter_title,
    serialize_kg_for_prompt,
    serialize_threads_for_prompt,
    serialize_themes_for_prompt,
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
        # ⑦ Compass 字段反解
        cw = ch.get("compass_warnings")
        if isinstance(cw, str) and cw.strip():
            try:
                ch["compass_warnings"] = json.loads(cw)
            except (TypeError, ValueError):
                ch["compass_warnings"] = []
        elif not isinstance(ch.get("compass_warnings"), list):
            ch["compass_warnings"] = []
    kg_stats = await db.get_ai_kg_stats(project_id)
    # ④ locations
    locations = await db.list_ai_kg_locations(project_id)
    # ⑤ plot_threads
    plot_threads = await db.list_ai_kg_plot_threads(project_id)
    # ⑨ themes
    themes_progress = await db.get_ai_project_themes(project_id)
    # ⑩ KG 全量 (供前端图谱视图)
    kg_full = await db.get_ai_knowledge_graph(project_id)
    return {
        "project": project,
        "chapters": chapters,
        "kg_stats": kg_stats,
        "locations": locations,
        "plot_threads": plot_threads,
        "themes_progress": themes_progress,
        "kg_full": kg_full,
    }


async def create_project(payload: Dict[str, Any]) -> int:
    project_id = await db.create_ai_project(
        title=payload.get("title") or "未命名项目",
        genre=payload.get("genre", ""),
        worldview=payload.get("worldview", ""),
        outline=payload.get("outline", ""),
        initial_concepts=payload.get("initial_concepts") or [],
        style_pref=payload.get("style_pref") or {},
        model_id=payload.get("model_id"),
    )
    # 自动把 initial_concepts 灌入知识图谱, 让项目从创建那一刻起就有
    # 完整的人物/事件/世界观上下文, 指引整本小说创作.
    if payload.get("initial_concepts"):
        try:
            await seed_kg_from_concepts(project_id)
            logger.info(
                "Auto-seeded KG for new project %s with %d initial concepts",
                project_id,
                len(payload.get("initial_concepts") or []),
            )
        except Exception as exc:  # noqa: BLE001
            # 自动 seed 失败不应阻塞项目创建
            logger.warning("Auto-seed KG failed for project %s: %s", project_id, exc)
    return project_id


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


async def _kg_context_for(
    project_id: int,
    *,
    planner_directions: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """构造给 Planner/Writer/Critic 的知识图谱上下文.

    包含三层:
    1. **项目设定 (核心, 整本小说必须遵守)**: worldview / outline / style_pref /
       title / genre + ⑨ themes_progress. 来自 ai_projects 表, 但作为 KG 上下文的"根设定"呈现.
    2. **抽取出的实体**: 已知人物 / 关键事件 / 关系. 来自 ai_kg_* 表.
    3. **⑤ plot_threads**: 列出 open / hinting 线索, 提示 Writer 推进/回收.

    ③ 排序参数: planner_directions 用于按相关度排序实体 (RAG-lite).
    """
    project = await db.get_ai_project(project_id)
    kg = await db.get_ai_knowledge_graph(project_id)
    last_chapter_tail = await _get_last_chapter_tail(project_id, n_chars=2000)
    outline = project.get("outline", "") if project else ""

    # 上章的方向 (foreshadowing 关键词) — 用于 RAG 排序
    last_directions: List[Dict[str, Any]] = []
    chapters = await db.list_ai_chapters(project_id)
    for ch in chapters[-1:]:
        for v in ch.get("variants") or []:
            d_text = v.get("planner_direction") or ""
            if d_text:
                # 解析 planner_direction: "[focus] title\nsynopsis\n核心事件: ..."
                # 简化为一个 dict 喂给 ranker
                first_line = d_text.split("\n", 1)[0]
                focus = ""
                title = first_line
                if first_line.startswith("[") and "]" in first_line:
                    focus = first_line[1:first_line.index("]")]
                    title = first_line[first_line.index("]") + 1:].strip()
                last_directions.append({
                    "foreshadowing": [],  # 不存
                    "title": title,
                    "focus": focus,
                })

    # ③ 排序 + ② 已知冲突注入 + ④/⑤/⑥ 结构化字段
    kg_text = serialize_kg_for_prompt(
        kg,
        planner_directions=planner_directions,
        last_chapter_content=last_chapter_tail,
        outline=outline,
        last_directions=last_directions if last_directions else None,
    )

    parts: List[str] = []
    if project:
        settings_block = _format_project_settings_for_prompt(project)
        if settings_block:
            parts.append(settings_block)
    # ⑨ 主题进度
    themes = await db.get_ai_project_themes(project_id)
    threads = kg.get("plot_threads") or []
    current_themes: List[str] = []
    if planner_directions:
        for d in planner_directions:
            for t in d.get("themes") or []:
                if t and t not in current_themes:
                    current_themes.append(t)
    themes_block = serialize_themes_for_prompt(
        themes,
        current_themes=current_themes,
    )
    if themes_block:
        parts.append("## 主题进度 (整本节奏)\n" + themes_block)
    # ⑤ 未结线索
    if threads:
        threads_block = serialize_threads_for_prompt(threads, only_active=True)
        if threads_block:
            parts.append("## 剧情线索 (主线 p≥4 必须本章推进)\n" + threads_block)
    if kg_text:
        parts.append(kg_text)
    return "\n\n".join(parts)


def _format_project_settings_for_prompt(project: Dict[str, Any]) -> str:
    """把 ai_projects 里的核心设定格式化为知识图谱的"根设定"段落."""
    title = (project.get("title") or "").strip()
    genre = (project.get("genre") or "").strip()
    worldview = (project.get("worldview") or "").strip()
    outline = (project.get("outline") or "").strip()
    style_pref = project.get("style_pref") or {}

    if not any([title, genre, worldview, outline, style_pref]):
        return ""

    lines: List[str] = ["## 根设定 (整本小说必须严格遵守)"]
    if title:
        lines.append(f"- 标题: {title}")
    if genre:
        lines.append(f"- 类型: {genre}")
    if worldview:
        lines.append(f"- 世界观: {worldview}")
    if outline:
        lines.append(f"- 总纲: {outline}")
    if isinstance(style_pref, dict) and style_pref:
        # style_pref 是 dict (e.g. {"视角": "第三人称", "语气": "热血"})
        style_str = "; ".join(
            f"{k}={v}" for k, v in style_pref.items() if v
        )
        if style_str:
            lines.append(f"- 文风偏好: {style_str}")
    return "\n".join(lines)


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
      - start:           整章开始 (含 chapter_id, chapter_no, title, model_id)
      - planner_done:    Planner 完毕, 附 3 个方向
      - title_generated: 用户没填标题时, 综合 3 方向自动生成的章节标题
      - writer_i_done:   第 i 个方向写作完毕, 附内容预览
      - critic_i_done:   第 i 个候选审核完毕, 附 score + report
      - done:            整章完成 (chapter.status=generated, 含最终 title)
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
        "title": title.strip(),
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

    # ⑨ 主题进度累积: 解析 Planner 的 themes, 与项目 themes_progress 合并
    try:
        cur_themes = await db.get_ai_project_themes(project_id) or []
        new_themes: Dict[str, Dict[str, Any]] = {t.get("theme"): t for t in cur_themes if t.get("theme")}
        # Planner 给的所有 themes
        all_themes_now: List[str] = []
        for d in directions:
            for t in d.get("themes") or []:
                if t and t not in all_themes_now:
                    all_themes_now.append(t)
        # 给新主题默认 stage=铺垫
        for t in all_themes_now:
            if t not in new_themes:
                new_themes[t] = {"theme": t, "progress": 0.0, "stage": "铺垫"}
        if new_themes:
            await db.update_ai_project_themes(project_id, list(new_themes.values()))
            yield {
                "event": "themes_updated",
                "themes": list(new_themes.values()),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("themes update failed: %s", exc)

    # ---- 章节标题生成 (仅当用户未填时) ----
    chapter_title = title.strip()
    if not chapter_title:
        try:
            chapter_title = await generate_chapter_title(
                model_cfg=model_cfg,
                project_title=project.get("title", ""),
                directions=directions,
                chapter_no=target_chapter_no,
                user_intent=user_intent,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chapter_title failed, fallback: %s", exc)
            chapter_title = f"第 {target_chapter_no} 章"
        # 落库 + 推前端
        try:
            await db.update_ai_chapter(chapter_id, title=chapter_title)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to persist auto-title: %s", exc)
        yield {
            "event": "title_generated",
            "chapter_id": chapter_id,
            "title": chapter_title,
            "auto": True,
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
    # ③ RAG 排序: 把 Planner 的方向喂给 kg_context 排序器
    directions_for_rank = [d.to_dict() for d in directions]
    kg_context = await _kg_context_for(
        project_id_int, planner_directions=directions_for_rank
    )
    last_chapter_tail = await _get_last_chapter_tail(project_id_int)

    # ⑧ BridgeAgent 接缝检测: 如果有上一章, 跑一次 (便宜, ~3s)
    bridge_context = ""
    if last_chapter_tail:
        try:
            from services.creation_agents import BridgeAgent
            bridge_agent = BridgeAgent()
            # 用第 0 方向作默认代表 (避免对 3 个方向各跑一次)
            bridge_out = await bridge_agent.run(
                model_cfg=model_cfg,
                prev_tail=last_chapter_tail,
                direction=directions[0],
                kg_warnings="(无)",  # 已经包含在 kg_context 中
            )
            bridge_lines: List[str] = []
            if bridge_out.open_hook_suggestions:
                bridge_lines.append("## BridgeAgent 开头钩子推荐")
                for h in bridge_out.open_hook_suggestions[:3]:
                    bridge_lines.append(f"- {h}")
            if bridge_out.conflicts:
                bridge_lines.append("## BridgeAgent 冲突提示")
                for c in bridge_out.conflicts[:3]:
                    bridge_lines.append(f"- {c}")
            if bridge_out.bridge_score < 7.0:
                bridge_lines.append(
                    f"⚠ 接缝质量较低 ({bridge_out.bridge_score:.1f}/10), 下一章需要更自然承接"
                )
            if bridge_lines:
                bridge_context = "\n".join(bridge_lines)
            yield {
                "event": "bridge_done",
                "bridge_score": bridge_out.bridge_score,
                "conflicts": bridge_out.conflicts,
                "open_hooks": bridge_out.open_hook_suggestions,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("bridge LLM failed: %s", exc)

    async def _run_writer(idx: int, direction: PlannerDirection):
        out = await writer.run(
            model_cfg=model_cfg,
            project=project,
            direction=direction,
            kg_context=(kg_context + ("\n\n" + bridge_context if bridge_context else "")),
            last_chapter_tail=last_chapter_tail,
            user_intent=user_intent,
            chapter_no=target_chapter_no,
            chapter_title=chapter_title,
        )
        await db.update_ai_variant(
            variant_ids[idx],
            critic_report=None,
            score=0.0,
            kg_diff={
                "key_event": direction.key_event,
                "focus": direction.focus,
                "themes": direction.themes,
            },
        )
        # ① 更新 content 同时, 把变体的 kg_extracted_at 也清空 (待 confirm 阶段重抽)
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
        "title": chapter_title,
    }


# ---------------------------------------------------------------------------
# Chapter operations (post-generation)
# ---------------------------------------------------------------------------


async def list_chapters(project_id: int) -> List[Dict[str, Any]]:
    chapters = await db.list_ai_chapters(project_id)
    for ch in chapters:
        ch["variants"] = await db.list_ai_variants(int(ch["id"]))
    return chapters


async def delete_chapter(chapter_id: int) -> bool:
    """删除单个章节 (含变体). KG 中的 source_chapter_id 引用会被 SET NULL."""
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        return False
    ok = await db.delete_ai_chapter(chapter_id)
    if not ok:
        return False
    # 回退 project.current_chapter_no, 避免下次生成空号
    try:
        project = await db.get_ai_project(int(ch["project_id"]))
        if project and int(ch.get("chapter_no", 0)) >= int(project.get("current_chapter_no", 1)):
            await db.update_ai_project(
                int(ch["project_id"]),
                current_chapter_no=int(ch["chapter_no"]),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_chapter: 回退 current_chapter_no 失败: %s", exc)
    return True


async def export_chapter_as_text(chapter_id: int) -> str:
    """把章节导出为可读纯文本, 供前端下载 .txt."""
    detail = await get_chapter_detail(chapter_id)
    ch = detail
    project = await db.get_ai_project(int(ch["project_id"]))
    title = ch.get("title") or f"第 {ch.get('chapter_no')} 章"
    chapter_no = int(ch.get("chapter_no") or 0)
    content = (ch.get("final_content") or "").strip()
    if not content:
        raise CreationError(f"章节 {chapter_id} 尚无内容, 无法导出")

    project_title = (project or {}).get("title") or "未命名项目"
    safe_project = _sanitize_filename(project_title)
    safe_chapter = _sanitize_filename(title) or f"第{chapter_no:03d}章"

    # BOM 让 Windows 记事本能正确识别 UTF-8
    header = (
        f"{project_title}\r\n"
        f"作者: AI 创作 (MiniMax)\r\n"
        f"{'=' * 60}\r\n"
        f"第 {chapter_no} 章 · {title}\r\n"
        f"字数: {ch.get('word_count') or _ascii_word_count(content)}\r\n"
        f"生成时间: {ch.get('created_at') or ''}\r\n"
        f"{'=' * 60}\r\n\r\n"
    )
    body = content + "\r\n"
    return header + body


def _sanitize_filename(name: str) -> str:
    """去除文件名中的非法字符."""
    if not name:
        return ""
    bad = '<>:"/\\|?*\r\n\t'
    out = "".join("_" if ch in bad else ch for ch in name).strip()
    return out[:80] or "chapter"


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
    """选择变体, 写入 final_content. ① 同时跑一次 EntityExtractor 把内容入 KG."""
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

    # ① 抽取并入 KG (best-effort, 失败不阻塞)
    if final.strip():
        try:
            project = await db.get_ai_project(int(ch["project_id"]))
            if project:
                model_cfg = await _resolve_model_cfg(project)
                kg_for_w = await db.get_ai_knowledge_graph(int(ch["project_id"]))
                from services.kg_ranker import _kg_warnings_for_prompt
                kg_w = _kg_warnings_for_prompt(kg_for_w) or "(无)"
                extractor = EntityExtractor()
                ext = await extractor.run(
                    model_cfg=model_cfg,
                    chapter_text=final,
                    chapter_no=int(ch.get("chapter_no") or 0),
                    kg_warnings=kg_w,
                )
                stored = await db.upsert_ai_kg_from_extraction(
                    int(ch["project_id"]),
                    source_chapter_id=chapter_id,
                    characters=ext.characters,
                    events=ext.events,
                    locations=ext.locations,
                    character_event_relations=ext.character_event_relations,
                    character_relations=ext.character_relations,
                    event_relations=ext.event_relations,
                    model_id=model_cfg.get("id"),
                )
                await db.update_ai_chapter_kg_extraction(
                    variant_id,
                    entity_count=len(stored["characters"]) + len(stored.get("locations") or []),
                    event_count=len(stored["events"]),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("select_variant: KG extraction failed: %s", exc)

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
    """确认章节 + 触发 4 个 Agent 流水线:

    1. CompassAgent ⑦ 偏离度检测 (5 维评分)
    2. EntityExtractor v2 ④⑥ 抽取人物/事件/地点 + 结构化字段 + 冲突标注
    3. ② 把 Critic 报告的冲突写回 KG (reconcile)
    4. ⑤ ThreadExtractor 伏笔/线索抽取 (create/update/resolve/drop)
    5. ⑨ 主题进度推进 (per-chapter 推进 0.1)

    任一阶段失败不应阻塞确认; 记录 raw 让前端能排查.
    """
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        raise CreationError(f"章节 {chapter_id} 不存在")
    project = await db.get_ai_project(int(ch["project_id"]))
    if not project:
        raise CreationError(f"项目 {ch['project_id']} 不存在")
    project_id = int(project["id"])
    final = ch.get("final_content") or ""
    if not final.strip():
        raise CreationError("章节内容为空, 无法抽取知识图谱")

    # 当前选中的变体 ID, 用于 ① 落 kg_extracted_at
    variant_id = ch.get("selected_variant_id")
    extracted_count: Dict[str, int] = {
        "characters": 0, "events": 0, "locations": 0,
        "character_event_relations": 0,
        "character_relations": 0, "event_relations": 0,
    }
    errors: List[str] = []
    compass_data: Dict[str, Any] = {}
    threads_count: Dict[str, int] = {"create": 0, "update": 0, "resolve": 0, "drop": 0, "skip": 0}
    conflicts_reconciled = 0

    # ---- 0. 准备: ② 已知冲突 (写回提示词) ----
    kg_for_warnings = await db.get_ai_knowledge_graph(project_id)
    from services.kg_ranker import _kg_warnings_for_prompt
    kg_warnings_text = _kg_warnings_for_prompt(kg_for_warnings) or "(无)"

    # ---- 1. ⑦ CompassAgent 偏离度检测 ----
    try:
        model_cfg = await _resolve_model_cfg(project)
        compass_agent = CompassAgent()
        open_threads = await db.list_ai_kg_plot_threads(
            project_id, status="open"
        ) + await db.list_ai_kg_plot_threads(project_id, status="hinting"
        )
        compass_out = await compass_agent.run(
            model_cfg=model_cfg,
            project=project,
            chapter=ch,
            chapter_content=final,
            open_threads=open_threads,
            kg_warnings=kg_warnings_text,
        )
        compass_data = {
            "score": compass_out.overall,
            "warnings": compass_out.warnings,
            "summary": compass_out.summary,
        }
        await db.update_ai_chapter_compass(
            chapter_id,
            score=compass_out.overall,
            warnings=compass_out.warnings,
            summary=compass_out.summary,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("CompassAgent failed for chapter %s: %s", chapter_id, exc)
        errors.append(f"compass: {exc}")

    # ---- 2. ④⑥ EntityExtractor v2 抽取 ----
    try:
        if "model_cfg" not in locals():
            model_cfg = await _resolve_model_cfg(project)
        extractor = EntityExtractor()
        extracted = await extractor.run(
            model_cfg=model_cfg,
            chapter_text=final,
            chapter_no=int(ch.get("chapter_no") or 0),
            kg_warnings=kg_warnings_text,
        )
        stored = await db.upsert_ai_kg_from_extraction(
            project_id,
            source_chapter_id=chapter_id,
            characters=extracted.characters,
            events=extracted.events,
            locations=extracted.locations,
            character_event_relations=extracted.character_event_relations,
            character_relations=extracted.character_relations,
            event_relations=extracted.event_relations,
            model_id=model_cfg.get("id"),
        )
        extracted_count = {
            "characters": len(stored["characters"]),
            "events": len(stored["events"]),
            "locations": len(stored.get("locations") or []),
            "character_event_relations": len(stored["character_event_relations"]),
            "character_relations": len(stored["character_relations"]),
            "event_relations": len(stored["event_relations"]),
        }
        # ① 落 kg_extracted_at + 计数到选中变体
        if variant_id:
            try:
                await db.update_ai_chapter_kg_extraction(
                    variant_id,
                    entity_count=extracted_count["characters"] + extracted_count["locations"],
                    event_count=extracted_count["events"],
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("kg_extracted_at update failed: %s", exc)

        # ② 把冲突写回 KG (按 name 找实体, 追加 conflicts_observed)
        if extracted.conflicts_in_text:
            try:
                conflicts_reconciled = await db.reconcile_kg_conflicts(
                    project_id,
                    chapter_id=chapter_id,
                    conflicts=extracted.conflicts_in_text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("reconcile_kg_conflicts failed: %s", exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("EntityExtractor v2 failed for chapter %s: %s", chapter_id, exc)
        errors.append(f"extractor: {exc}")

    # ---- 3. ⑤ ThreadExtractor 伏笔/线索 ----
    try:
        if "model_cfg" not in locals():
            model_cfg = await _resolve_model_cfg(project)
        thread_ext = ThreadExtractor()
        open_threads = (
            await db.list_ai_kg_plot_threads(project_id, status="open")
            + await db.list_ai_kg_plot_threads(project_id, status="hinting")
            + await db.list_ai_kg_plot_threads(project_id, status="resolving")
        )
        threads_out = await thread_ext.run(
            model_cfg=model_cfg,
            chapter_content=final,
            chapter_no=int(ch.get("chapter_no") or 0),
            open_threads=open_threads,
        )
        threads_count = await db.upsert_ai_kg_plot_threads(
            project_id,
            source_chapter_id=chapter_id,
            threads=[{
                "thread_id": t.thread_id,
                "action": t.action,
                "title": t.title,
                "thread_type": t.thread_type,
                "status": t.status,
                "priority": t.priority,
                "related_entity_ids": t.related_entity_ids,
                "notes": t.notes,
            } for t in threads_out.threads],
            model_id=model_cfg.get("id"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("ThreadExtractor failed for chapter %s: %s", chapter_id, exc)
        errors.append(f"threads: {exc}")

    # ---- 4. ⑨ 主题进度推进: 把已被 touches 的 theme progress 推 0.1 ----
    try:
        cur_themes = await db.get_ai_project_themes(project_id) or []
        # 当前章 touches 的 themes (来自 Planner)
        cur_touches: List[str] = []
        for d in (ch.get("variants") or []):
            kg_diff = d.get("kg_diff") or {}
            for t in kg_diff.get("themes") or []:
                if t and t not in cur_touches:
                    cur_touches.append(t)
        # 兼容: 从已选变体的 kg_diff 拿不到时, 从 open threads 的 title 兜底
        if not cur_touches:
            for t in (await db.list_ai_kg_plot_threads(project_id, status="resolving"))[:5]:
                if t.get("title") and t.get("title") not in cur_touches:
                    cur_touches.append(t.get("title"))
        for entry in cur_themes:
            if entry.get("theme") in cur_touches:
                p = float(entry.get("progress", 0) or 0)
                if p < 0.95:
                    p = min(0.95, p + 0.1)
                entry["progress"] = p
                if p < 0.3:
                    entry["stage"] = "铺垫"
                elif p < 0.7:
                    entry["stage"] = "发展"
                else:
                    entry["stage"] = "高潮"
        await db.update_ai_project_themes(project_id, cur_themes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("theme progress update failed: %s", exc)

    # ---- 5. 章节状态 → confirmed ----
    await db.update_ai_chapter(
        chapter_id,
        status="confirmed",
        kg_extracted=1,
        confirmed_at="CURRENT_TIMESTAMP",
    )
    detail = await get_chapter_detail(chapter_id)
    detail["extraction"] = {
        "counts": extracted_count,
        "compass": compass_data,
        "threads": threads_count,
        "conflicts_reconciled": conflicts_reconciled,
        "errors": errors,
    }
    return detail
