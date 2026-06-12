"""AI 小说创作 — 主编排 (项目 CRUD + 三 Agent 单候选生成 + KG 抽取).

工作流 (单章节生成)
-------------------
1. ``create_chapter_for_generation`` 创建 ai_chapters 行 (status=generating)
2. ``generate_chapter_streaming`` 单候选流水线 (最多 ``max_revise`` 轮 Critic 循环):
   - Planner  → 1 direction (SSE: planner_done)
   - Writer   → 正文 (SSE: writer_0_done)
   - Critic   → 综合分 (SSE: critic_0_done); < 阈值则 critic_rejected 后回到 Planner + Writer 重做
   - 收尾写入 1 个 variant, chapter.status = selected, 自动锁定为 final_content
3. ``update_chapter_content`` 用户编辑保存
4. (可选) EntityExtractor 抽取本章新增实体 → 入 ai_kg_* 表 → 状态 confirmed

所有 LLM 调用共用项目设置中的 ``model_id`` (一个 chat 模型).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
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


# P2-#30: 错误信息脱敏 — 不把 API key / 内网地址 / 堆栈返回给前端
_SENSITIVE_PATTERNS = [
    (re.compile(r'sk-[A-Za-z0-9_\-]{8,}'), 'sk-***'),
    (re.compile(r'Bearer\s+[A-Za-z0-9_\-\.]{8,}'), 'Bearer ***'),
    (re.compile(r'://[^/\s]+@'), '://***@'),  # user:pass@host
    (re.compile(r'127\.0\.0\.\d+'), '127.0.0.x'),
    (re.compile(r'10\.\d{1,3}\.\d{1,3}\.\d{1,3}'), '10.x.x.x'),
    (re.compile(r'192\.168\.\d{1,3}\.\d{1,3}'), '192.168.x.x'),
]


def sanitize_error(exc: Exception) -> str:
    """把异常对象转成脱敏后的可展示字符串."""
    msg = str(exc) or exc.__class__.__name__
    for pat, repl in _SENSITIVE_PATTERNS:
        msg = pat.sub(repl, msg)
    # 截断超长堆栈信息
    if len(msg) > 300:
        msg = msg[:300] + '…'
    return msg


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
    """更新项目设定. 当 initial_concepts 列表发生变化时, 自动重新灌入
    知识图谱 (保留 LLM 后抽取的实体, 只新增/补齐 initial_concepts 里的
    人物). 这样用户编辑设定时无需再手动点「灌入」按钮, 也避免了
    灌入覆盖后续章节抽取的新实体.
    """
    # 先拿一次旧值, 用于对比 initial_concepts 是否变了
    old_concepts: Optional[List[Dict[str, Any]]] = None
    if "initial_concepts" in payload:
        old = await db.get_ai_project(project_id)
        old_concepts = old.get("initial_concepts") if old else None

    ok = await db.update_ai_project(
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
    if not ok:
        return False

    # initial_concepts 变更检测: 与旧值不一致就重新灌入 (upsert, 不删除已有实体)
    if "initial_concepts" in payload:
        new_concepts = payload.get("initial_concepts") or []
        if not _concepts_equal(old_concepts, new_concepts):
            try:
                await seed_kg_from_concepts(project_id)
                logger.info(
                    "Auto re-seeded KG after initial_concepts update for project %s",
                    project_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Auto re-seed KG failed for project %s: %s",
                    project_id, exc,
                )
    return True


def _concepts_equal(
    a: Optional[List[Dict[str, Any]]], b: List[Dict[str, Any]]
) -> bool:
    """判断两个 initial_concepts 列表是否等价 (按 name 排序后逐项对比)."""
    if a is None:
        return not b
    if len(a) != len(b):
        return False
    a_norm = sorted(
        [{k: v for k, v in (c or {}).items() if k != "entity_id"} for c in a],
        key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False),
    )
    b_norm = sorted(
        [{k: v for k, v in (c or {}).items() if k != "entity_id"} for c in b],
        key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False),
    )
    return a_norm == b_norm


async def delete_project(project_id: int) -> bool:
    return await db.delete_ai_project(project_id)


async def duplicate_project(project_id: int) -> int:
    """UX-#15: 复制项目. 复制: 设定 / KG 人物事件地点 / 关系 / plot_threads /
    locations / themes_progress. 不复制: 章节正文, 变体, 最终内容.
    标题加 "(副本)" 后缀.
    """
    src = await db.get_ai_project(project_id)
    if not src:
        raise CreationError(f"项目 {project_id} 不存在")
    new_id = await db.create_ai_project(
        title=f"{src.get('title') or '未命名项目'} (副本)",
        genre=src.get("genre", ""),
        worldview=src.get("worldview", ""),
        outline=src.get("outline", ""),
        initial_concepts=src.get("initial_concepts") or [],
        style_pref=src.get("style_pref") or {},
        model_id=src.get("model_id"),
    )
    # 复制 KG 人物
    src_chars = await db._fetch_all_ai_kg_characters(project_id) if False else None  # 用 list
    chars = await db.list_ai_knowledge_graph(project_id)
    if chars.get("characters"):
        for c in chars["characters"]:
            await db.insert_ai_kg_character(
                new_id,
                entity_id=f"char_{_short_id()}",
                name=c.get("name", ""),
                attributes=c.get("attributes") or {},
                role=c.get("role"),
                faction=c.get("faction"),
                status=c.get("status"),
                importance=c.get("importance"),
            )
    # 复制 KG 事件
    if chars.get("events"):
        for e in chars["events"]:
            await db.insert_ai_kg_event(
                new_id,
                entity_id=f"evt_{_short_id()}",
                name=e.get("name", ""),
                attributes=e.get("attributes") or {},
                importance=e.get("importance"),
                in_story_time=e.get("in_story_time"),
            )
    return new_id


def _short_id(n: int = 10) -> str:
    import uuid as _u
    return _u.uuid4().hex[:n]


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
    max_revise: int = 2,
    score_threshold: float = 7.0,
) -> AsyncIterator[Dict[str, Any]]:
    """单章节生成入口 (单候选 + Critic 循环).

    流水线: Planner (1 方向) → Writer → Critic; Critic < 阈值则带反馈回到
    Planner + Writer 重做, 直到通过或达到 ``max_revise`` 轮. 详见
    ``_generate_chapter_streaming_single``.

    事件类型:
      - start:           整章开始
      - planner_done:    Planner 完毕, 附 1 个方向
      - title_generated: 用户没填标题时, 自动生成的章节标题
      - writer_0_done:   Writer 完毕, 附内容预览
      - critic_0_done:   Critic 审核完毕, 附 score + report
      - critic_rejected: Critic 未通过, 附 issues / modifications, 即将重做
      - revision_start:  开始新一轮 Planner + Writer
      - done:            整章完成 (chapter.status=selected, 1 个 variant 自动选中)
      - error:           异常
    """
    async for ev in _generate_chapter_streaming_single(
        project_id,
        user_intent=user_intent,
        chapter_no=chapter_no,
        title=title,
        max_revise=max_revise,
        score_threshold=score_threshold,
    ):
        yield ev


# ---------------------------------------------------------------------------
# ④ 单候选 + Critic 循环 (唯一流水线)
# ---------------------------------------------------------------------------


def _format_critic_feedback(critic_out) -> str:
    """把 Critic 输出压缩成 Planner / Writer 可消化的反馈文本."""
    parts: List[str] = []
    if critic_out.issues:
        parts.append("## 必须修复的问题")
        for x in critic_out.issues[:8]:
            parts.append(f"- {x}")
    if critic_out.modifications:
        parts.append("## 建议改进")
        for x in critic_out.modifications[:8]:
            parts.append(f"- {x}")
    if critic_out.kg_conflicts:
        parts.append("## 与知识图谱的冲突")
        for c in critic_out.kg_conflicts[:5]:
            parts.append(f"- {c}")
    parts.append(
        f"## 综合评分\n{critic_out.overall:.1f}/10 — 需 >= score_threshold 才能通过."
    )
    return "\n".join(parts)


async def _generate_chapter_streaming_single(
    project_id: int,
    *,
    user_intent: str = "",
    chapter_no: Optional[int] = None,
    title: str = "",
    max_revise: int = 2,
    score_threshold: float = 7.0,
) -> AsyncIterator[Dict[str, Any]]:
    """单候选生成: 1 个 Planner 方向 -> 1 个 Writer -> 1 个 Critic.
    Critic 不达标就带反馈回到 Planner + Writer 重做, 直到达标或达到
    ``max_revise`` 轮. 最终自动写入 1 个 variant 并 ``selected_variant_id``
    指向它, 章节状态 ``selected``, 前端直接进编辑器.

    事件列表见 ``generate_chapter_streaming`` 文档.
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
        "mode": "single",
        "max_revise": max_revise,
        "score_threshold": score_threshold,
    }

    planner = PlannerAgent()
    writer = WriterAgent()
    critic = CriticAgent()

    project_id_int = int(project["id"])
    kg_context_base = await _kg_context_for(project_id_int)
    last_chapter_tail = await _get_last_chapter_tail(project_id_int)
    last_summary = await _get_last_chapter_summary(project_id_int)

    # BridgeAgent 仅在有上一章时跑一次, 跟 candidates 流水线保持一致
    bridge_context = ""
    if last_chapter_tail:
        try:
            from services.creation_agents import BridgeAgent
            bridge_agent = BridgeAgent()
            bridge_out = await bridge_agent.run(
                model_cfg=model_cfg,
                prev_tail=last_chapter_tail,
                # 给个 stub direction, BridgeAgent 只看 prev_tail 与 kg_warnings
                # 但签名要求 direction, 这里塞一个空对象
                direction=PlannerDirection(
                    index=0, title="", synopsis="", key_event=""
                ),
                kg_warnings="(无)",
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

    # 自动标题 (仅用户未填时跑一次, 后续轮次复用)
    chapter_title = title.strip()
    auto_title = False
    if not chapter_title:
        try:
            # 先用空 directions 跑一次, 让 LLM 知道我们要写啥; 后面 Planner 出方向
            # 后, 如果标题显得太离谱, 我们会基于最终方向再覆盖一次.
            chapter_title = await generate_chapter_title(
                model_cfg=model_cfg,
                project_title=project.get("title", ""),
                directions=[
                    PlannerDirection(
                        index=0,
                        title="(待规划)",
                        synopsis=user_intent or "(基于用户意图生成)",
                        focus="综合",
                    )
                ],
                chapter_no=target_chapter_no,
                user_intent=user_intent,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("chapter_title failed, fallback: %s", exc)
            chapter_title = f"第 {target_chapter_no} 章"
        auto_title = True
    try:
        await db.update_ai_chapter(chapter_id, title=chapter_title)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to persist auto-title: %s", exc)
    yield {
        "event": "title_generated",
        "chapter_id": chapter_id,
        "title": chapter_title,
        "auto": auto_title,
    }

    max_attempts = max_revise + 1  # 含首次
    last_critic = None
    accepted = False
    final_overall = 0.0
    last_writer_out = None
    last_direction = None
    last_kg_context_used = ""

    for attempt in range(1, max_attempts + 1):
        if attempt > 1:
            yield {
                "event": "revision_start",
                "chapter_id": chapter_id,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "previous_score": last_critic.overall if last_critic else 0.0,
            }

        # 1. Planner (带 Critic 反馈, 如有)
        feedback_text = _format_critic_feedback(last_critic) if last_critic else ""
        try:
            planner_inputs = await _build_planner_inputs(
                project, user_intent, target_chapter_no
            )
            planner_out = await planner.run(
                model_cfg=model_cfg,
                feedback=feedback_text,
                **planner_inputs,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("planner failed (attempt %s)", attempt)
            yield {
                "event": "error",
                "message": f"Planner 失败: {sanitize_error(exc)}",
                "chapter_id": chapter_id,
            }
            return

        # 单候选模式只取 Planner 输出的方向 0 (焦点: 动作, 其它两个忽略)
        if not planner_out.directions:
            yield {"event": "error", "message": "Planner 未返回任何方向", "chapter_id": chapter_id}
            return
        direction = planner_out.directions[0]
        yield {
            "event": "planner_done",
            "chapter_id": chapter_id,
            "attempt": attempt,
            "directions": [direction.to_dict()],
        }

        # 2. Writer
        kg_context_for_writer = (
            kg_context_base + ("\n\n" + bridge_context if bridge_context else "")
        )
        try:
            writer_out = await writer.run(
                model_cfg=model_cfg,
                project=project,
                direction=direction,
                kg_context=kg_context_for_writer,
                last_chapter_tail=last_chapter_tail,
                user_intent=user_intent,
                chapter_no=target_chapter_no,
                chapter_title=chapter_title,
                feedback=feedback_text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("writer failed (attempt %s)", attempt)
            yield {
                "event": "error",
                "message": f"Writer 失败: {sanitize_error(exc)}",
                "chapter_id": chapter_id,
            }
            return

        yield {
            "event": "writer_0_done",
            "chapter_id": chapter_id,
            "attempt": attempt,
            "preview": writer_out.content[:300],
            "word_count": _ascii_word_count(writer_out.content),
        }
        last_writer_out = writer_out
        last_direction = direction
        last_kg_context_used = kg_context_for_writer

        # 3. Critic
        try:
            critic_out = await critic.run(
                model_cfg=model_cfg,
                project=project,
                direction=direction,
                chapter_content=writer_out.content,
                kg_context=kg_context_base,
                last_chapter_summary=last_summary,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("critic failed (attempt %s)", attempt)
            yield {
                "event": "error",
                "message": f"Critic 失败: {sanitize_error(exc)}",
                "chapter_id": chapter_id,
            }
            return

        yield {
            "event": "critic_0_done",
            "chapter_id": chapter_id,
            "attempt": attempt,
            "score": critic_out.overall,
            "passed": critic_out.overall >= score_threshold,
            "issues": critic_out.issues,
            "modifications": critic_out.modifications,
            "kg_conflicts": critic_out.kg_conflicts,
        }
        last_critic = critic_out
        final_overall = critic_out.overall

        if critic_out.overall >= score_threshold:
            accepted = True
            break

        # Critic 未通过, 若是最后一轮, 也直接收尾 (用户允许有未达标)
        if attempt < max_attempts:
            yield {
                "event": "critic_rejected",
                "chapter_id": chapter_id,
                "attempt": attempt,
                "score": critic_out.overall,
                "threshold": score_threshold,
                "issues": critic_out.issues,
                "modifications": critic_out.modifications,
            }

    # 4. 收尾: 写入 1 个 variant, 自动选中, 状态=selected
    variant_id = await db.insert_ai_variant(
        chapter_id=chapter_id,
        variant_index=0,
        planner_direction=(
            f"[{last_direction.focus}] {last_direction.title}\n"
            f"{last_direction.synopsis}\n核心事件: {last_direction.key_event}"
        ),
        content=last_writer_out.content,
        focus_summary=last_writer_out.focus_summary,
        kg_diff={
            "key_event": last_direction.key_event,
            "focus": last_direction.focus,
            "themes": getattr(last_direction, "themes", None) or [],
        },
        critic_report=last_critic.to_dict() if last_critic else {},
        score=final_overall,
        model_id=model_cfg.get("id"),
    )

    # 写入正文字数, 并把 selected_variant_id / final_content 落到章节行,
    # 章节状态设为 "selected", 前端直接进 VariantEditor.
    await db.update_ai_chapter(
        chapter_id,
        selected_variant_id=variant_id,
        final_content=last_writer_out.content,
        word_count=_ascii_word_count(last_writer_out.content),
        status="selected",
    )
    await db.update_ai_project(
        project_id,
        current_chapter_no=target_chapter_no + 1,
    )

    yield {
        "event": "done",
        "chapter_id": chapter_id,
        "variant_id": variant_id,
        "title": chapter_title,
        "attempts": attempt,
        "accepted": accepted,
        "final_score": final_overall,
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
    """删除单个章节 (含变体). KG 中的 source_chapter_id 引用会被 SET NULL.
    P0-#4: 同步将后续 chapter_no 重新编号, 避免出现"第 1、2、4 章"断层.
    """
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        return False
    project_id = int(ch["project_id"])
    deleted_chapter_no = int(ch.get("chapter_no") or 0)
    ok = await db.delete_ai_chapter(chapter_id)
    if not ok:
        return False
    # P0-#4: 删除中间章节后, 重新编号后续章节
    if deleted_chapter_no > 0:
        try:
            await rebalance_chapter_nos(project_id, deleted_chapter_no)
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_chapter: rebalance 失败: %s", exc)
    # 回退 project.current_chapter_no, 避免下次生成空号
    try:
        project = await db.get_ai_project(project_id)
        if project:
            remaining = await db.list_ai_chapters(project_id)
            if remaining:
                # current_chapter_no 设为 max + 1, 准备生成下一章
                max_no = max(int(c.get("chapter_no") or 0) for c in remaining)
                await db.update_ai_project(
                    project_id,
                    current_chapter_no=max_no + 1,
                )
            else:
                # 全删完了, 重置为 1
                await db.update_ai_project(project_id, current_chapter_no=1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_chapter: 回退 current_chapter_no 失败: %s", exc)
    return True


async def rebalance_chapter_nos(project_id: int, after_no: int) -> int:
    """P0-#4: 把 chapter_no > after_no 的章节统一 -1, 消除编号断层.
    涉及 UNIQUE(project_id, chapter_no) 约束, 临时偏移再更新.
    返回被改写的章节数.
    """
    chapters = await db.list_ai_chapters(project_id)
    affected = [c for c in chapters if int(c.get("chapter_no") or 0) > after_no]
    if not affected:
        return 0
    # 临时偏移到 -1 避免唯一冲突, 再写回正式编号
    for ch in affected:
        await db.update_ai_chapter(
            int(ch["id"]),
            chapter_no=int(ch.get("chapter_no") or 0) - 100000,
        )
    for ch in affected:
        new_no = int(ch.get("chapter_no") or 0) - 100000 - 1
        await db.update_ai_chapter(int(ch["id"]), chapter_no=new_no)
    return len(affected)


async def reorder_chapters(project_id: int, orders: List[Dict[str, int]]) -> int:
    """UX-#6: 拖拽重排. 接受 [{id, chapter_no}, ...].

    把所有 id 临时偏移到 -100000, 再写回目标 chapter_no, 避免 UNIQUE 冲突.
    返回被改写的章节数.
    """
    project = await db.get_ai_project(project_id)
    if not project:
        raise CreationError(f"项目 {project_id} 不存在")
    # 校验所有 id 都属于该项目
    chapters = await db.list_ai_chapters(project_id)
    valid_ids = {int(c["id"]) for c in chapters}
    targets = []
    for o in orders:
        cid = int(o.get("id") or 0)
        new_no = int(o.get("chapter_no") or 0)
        if cid not in valid_ids or new_no < 1:
            continue
        targets.append((cid, new_no))
    if not targets:
        return 0
    # 临时偏移
    for cid, _ in targets:
        await db.update_ai_chapter(cid, chapter_no=-100000 - cid)
    # 写回正式编号 (按 order 列表的顺序, 但落库用目标 chapter_no)
    for cid, new_no in targets:
        await db.update_ai_chapter(cid, chapter_no=new_no)
    return len(targets)


async def get_chapter_variants_history(chapter_id: int) -> List[Dict[str, Any]]:
    """P0-#3: 获取章节全部变体 (含历史轮次), 供版本切换 UI 使用."""
    ch = await db.get_ai_chapter(chapter_id)
    if not ch:
        raise CreationError(f"章节 {chapter_id} 不存在")
    return await db.list_ai_variants_full_history(chapter_id)


async def export_project_as_text(project_id: int, format: str = "txt") -> str:
    """UX-#16: 全本导出. 把项目所有 confirmed 章节按 chapter_no 顺序拼接.
    支持 .txt / .md 两种格式.
    """
    project = await db.get_ai_project(project_id)
    if not project:
        raise CreationError(f"项目 {project_id} 不存在")
    chapters = await db.list_ai_chapters(project_id)
    confirmed = [c for c in chapters if c.get("status") == "confirmed" and c.get("final_content")]
    if not confirmed:
        raise CreationError("项目下尚无已确认章节, 无可导出内容")
    confirmed.sort(key=lambda c: int(c.get("chapter_no") or 0))

    title = (project.get("title") or f"项目{project_id}").strip()
    out_lines: List[str] = []
    if format == "md":
        out_lines.append(f"# {title}")
        out_lines.append("")
        out_lines.append(f"> 由 AI 小说管理系统导出 · 章节数 {len(confirmed)}")
        out_lines.append("")
        for c in confirmed:
            ch_no = int(c.get("chapter_no") or 0)
            ch_title = (c.get("title") or "").strip() or f"第 {ch_no} 章"
            out_lines.append(f"## 第 {ch_no} 章 · {ch_title}")
            out_lines.append("")
            out_lines.append((c.get("final_content") or "").rstrip())
            out_lines.append("")
    else:
        out_lines.append(title)
        out_lines.append("=" * max(8, min(40, len(title))))
        out_lines.append(f"由 AI 小说管理系统导出 · 共 {len(confirmed)} 章")
        out_lines.append("")
        for c in confirmed:
            ch_no = int(c.get("chapter_no") or 0)
            ch_title = (c.get("title") or "").strip() or f"第 {ch_no} 章"
            out_lines.append(f"第 {ch_no} 章 · {ch_title}")
            out_lines.append("-" * max(8, min(40, len(ch_title) + 8)))
            out_lines.append("")
            out_lines.append((c.get("final_content") or "").rstrip())
            out_lines.append("")
    return "\n".join(out_lines).rstrip() + "\n"


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
    # ⑦ Compass 字段反解: 数据库里是 JSON 字符串 / NULL / 列表 三种形态,
    # schema (AiChapterOut) 要求 compass_warnings 必须是 List, 必须统一成 list.
    cw = ch.get("compass_warnings")
    if isinstance(cw, str) and cw.strip():
        try:
            ch["compass_warnings"] = json.loads(cw)
        except (TypeError, ValueError):
            ch["compass_warnings"] = []
    elif not isinstance(cw, list):
        ch["compass_warnings"] = []
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
