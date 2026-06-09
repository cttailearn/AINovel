"""AI 小说创作 — 三 Agent (Planner / Writer / Critic) + 实体抽取.

设计要点
--------
* 三个 Agent 互相解耦, 各自封装一次 LLM 调用, 由 creation_service 编排.
* 知识图谱上下文由 orchestrator 拼成文本, 直接塞进 user_prompt, 实现轻量 RAG.
* 容忍 JSON 解析失败: 退化为 "把整段当作内容/方向" 走兜底路径, 不让单次解析失败
  阻塞整章生成.
* ``_call_llm`` 统一管理重试, 失败时抛 ``AgentCallError`` 供上层决定重试 / 兜底.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services import ai_service, prompt_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class AgentCallError(RuntimeError):
    """LLM 调用失败 (网络 / 鉴权 / 重试耗尽)."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlannerDirection:
    """一个 Planner 输出的方向 (共 3 个)."""

    index: int
    title: str
    synopsis: str
    focus: str = "动作"           # 动作 | 心理 | 意外
    key_entities: List[str] = field(default_factory=list)
    foreshadowing: List[str] = field(default_factory=list)
    tone: str = "紧张"
    hard_constraints: List[str] = field(default_factory=list)
    key_event: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "title": self.title,
            "synopsis": self.synopsis,
            "focus": self.focus,
            "key_entities": list(self.key_entities),
            "foreshadowing": list(self.foreshadowing),
            "tone": self.tone,
            "hard_constraints": list(self.hard_constraints),
            "key_event": self.key_event,
        }


@dataclass
class PlannerOutput:
    directions: List[PlannerDirection] = field(default_factory=list)
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "directions": [d.to_dict() for d in self.directions],
            "raw": self.raw,
        }


@dataclass
class WriterOutput:
    content: str
    focus_summary: str = ""
    raw: str = ""


@dataclass
class CriticOutput:
    scores: Dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    strengths: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    modifications: List[str] = field(default_factory=list)
    kg_conflicts: List[Dict[str, str]] = field(default_factory=list)
    raw: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scores": dict(self.scores),
            "overall": self.overall,
            "strengths": list(self.strengths),
            "issues": list(self.issues),
            "modifications": list(self.modifications),
            "kg_conflicts": list(self.kg_conflicts),
        }


# ---------------------------------------------------------------------------
# LLM dispatch
# ---------------------------------------------------------------------------


async def _resolve_prompt(key: str) -> Optional[Dict[str, Any]]:
    """优先 DB 中用户自定义模板, 缺失时回落到内置 default."""
    try:
        tmpl = await prompt_service.get_active_prompt_by_key(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("DB prompt lookup failed for %s: %s", key, exc)
        tmpl = None
    if not tmpl:
        tmpl = prompt_service.get_default_prompt(key) or {}
    return tmpl or {}


async def _call_llm(
    *,
    model_cfg: Dict[str, Any],
    prompt_key: str,
    template_vars: Dict[str, Any],
    fallback_user_prompt: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """统一 LLM 调用: 解析 prompt → 调 ai_service → 返回 content 字符串.

    ``template_vars`` 必须是 dict (与模板里的 ``{key}`` 占位符一一对应).
    历史原因: 之前传 ``user_prompt`` 是 JSON 字符串, 但 ``format_map`` 拿它当 dict
    查表, 导致 ``_SafeDict.__missing__`` 永远命中, 模板里所有占位符都被替换为 "".
    现在强制传 dict, 保证 LLM 真正拿到项目设定.
    """
    if not isinstance(template_vars, dict):
        raise TypeError(
            f"template_vars 必须是 dict, 实际是 {type(template_vars).__name__}"
        )
    tmpl = await _resolve_prompt(prompt_key)
    system_prompt = tmpl.get("system_prompt", "") or ""
    raw_user_tmpl = tmpl.get("user_prompt_template", "") or fallback_user_prompt
    # 调用方覆盖 > prompt 模板默认 > 内置默认
    if temperature is None:
        try:
            temperature = float(tmpl.get("temperature") or 0.5)
        except (TypeError, ValueError):
            temperature = 0.5
    if max_tokens is None:
        try:
            max_tokens = int(tmpl.get("max_tokens") or 2400)
        except (TypeError, ValueError):
            max_tokens = 2400
    if raw_user_tmpl and "{" in raw_user_tmpl:
        try:
            user_prompt_resolved = raw_user_tmpl.format_map(_SafeDict(template_vars))
        except Exception as exc:  # noqa: BLE001
            logger.warning("prompt.format failed for %s: %s", prompt_key, exc)
            user_prompt_resolved = raw_user_tmpl
    else:
        # 没有模板占位符时, 把 dict 序列化成 YAML 风格的 key: value 当成 user prompt
        user_prompt_resolved = _dict_to_plain_text(template_vars)

    try:
        return await ai_service.chat_completion(
            provider=model_cfg["provider"],
            model_url=model_cfg["model_url"],
            api_key=model_cfg["api_key"],
            model_name=model_cfg["model_name"],
            system_prompt=system_prompt,
            user_prompt=user_prompt_resolved,
            temperature=temperature,
            max_tokens=max_tokens,
            retries=1,
        )
    except Exception as exc:  # noqa: BLE001
        raise AgentCallError(f"{prompt_key} LLM 调用失败: {exc}") from exc


def _dict_to_plain_text(d: Dict[str, Any]) -> str:
    """把 dict 序列化成 key: value 形式 (供没有模板占位符的 prompt 使用)."""
    lines: List[str] = []
    for k, v in d.items():
        if v is None or v == "":
            continue
        if isinstance(v, (dict, list)):
            try:
                v = json.dumps(v, ensure_ascii=False)
            except (TypeError, ValueError):
                v = str(v)
        lines.append(f"{k}: {v}")
    return "\n".join(lines)


class _SafeDict(dict):
    """模板占位符兜底: 缺失键不抛 KeyError, 替换为空字符串."""

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        logger.debug("prompt placeholder %s is missing, fallback to ''", key)
        return ""


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}|\[[\s\S]*\]")


def _extract_json(raw: str) -> Optional[Any]:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(cleaned)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# PlannerAgent — 决策 Agent
# ---------------------------------------------------------------------------


class PlannerAgent:
    """生成 3 个分叉方向. 失败时返回兜底方向 (基于 user_intent 切分关键词)."""

    DEFAULT_FALLBACK_FOCUS = ("动作", "心理", "意外")

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        project: Dict[str, Any],
        kg_context: str,
        last_chapter_summary: str,
        user_intent: str,
        chapter_no: int,
    ) -> PlannerOutput:
        vars_payload = {
            "project_title": project.get("title", ""),
            "genre": project.get("genre", ""),
            "worldview": project.get("worldview", ""),
            "outline": project.get("outline", ""),
            "style_pref": json.dumps(
                project.get("style_pref") or {}, ensure_ascii=False
            ),
            "kg_context": kg_context or "(暂无知识图谱)",
            "last_chapter_summary": last_chapter_summary or "(本章为首章)",
            "user_intent": user_intent or "(无额外意图)",
            "chapter_no": str(chapter_no),
        }
        prompt_str = json.dumps(vars_payload, ensure_ascii=False)
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.planner.direction",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("planner LLM failed, using fallback: %s", exc)
            return PlannerOutput(
                directions=self._fallback_directions(user_intent, chapter_no),
                raw=str(exc),
            )
        parsed = _extract_json(raw)
        directions = self._parse_directions(parsed, raw, user_intent, chapter_no)
        return PlannerOutput(directions=directions, raw=raw)

    @classmethod
    def _parse_directions(
        cls,
        parsed: Optional[Any],
        raw: str,
        user_intent: str,
        chapter_no: int,
    ) -> List[PlannerDirection]:
        items: List[Dict[str, Any]] = []
        if isinstance(parsed, dict):
            arr = parsed.get("directions")
            if isinstance(arr, list):
                items = [x for x in arr if isinstance(x, dict)]
        elif isinstance(parsed, list):
            items = [x for x in parsed if isinstance(x, dict)]

        # 兜底: 无法解析时给 3 个空方向
        if not items:
            return cls._fallback_directions(user_intent, chapter_no)

        directions: List[PlannerDirection] = []
        for i, obj in enumerate(items[:3]):
            directions.append(
                PlannerDirection(
                    index=int(obj.get("index", i)),
                    title=str(obj.get("title") or f"方向 {i + 1}").strip()[:80],
                    synopsis=str(obj.get("synopsis") or "").strip()[:200],
                    focus=str(obj.get("focus") or cls.DEFAULT_FALLBACK_FOCUS[i])
                    .strip()[:20],
                    key_entities=[
                        str(x) for x in (obj.get("key_entities") or []) if x
                    ][:8],
                    foreshadowing=[
                        str(x) for x in (obj.get("foreshadowing") or []) if x
                    ][:8],
                    tone=str(obj.get("tone") or "紧张").strip()[:20],
                    hard_constraints=[
                        str(x) for x in (obj.get("hard_constraints") or []) if x
                    ][:8],
                    key_event=str(obj.get("key_event") or "").strip()[:200],
                )
            )
        # 补齐到 3 个
        while len(directions) < 3:
            directions.append(
                cls._fallback_directions(user_intent, chapter_no)[len(directions)]
            )
        return directions

    @classmethod
    def _fallback_directions(
        cls, user_intent: str, chapter_no: int
    ) -> List[PlannerDirection]:
        focus_seq = cls.DEFAULT_FALLBACK_FOCUS
        base_intent = user_intent.strip() or "推进主线"
        return [
            PlannerDirection(
                index=i,
                title=f"第 {chapter_no} 章 · 方向 {i + 1} ({focus_seq[i]})",
                synopsis=base_intent,
                focus=focus_seq[i],
                key_entities=[],
                foreshadowing=[],
                tone="紧张",
                hard_constraints=[],
                key_event=base_intent,
            )
            for i in range(3)
        ]


# ---------------------------------------------------------------------------
# ChapterTitleAgent — 章节标题生成 (在 Planner 之后, Writer 之前调用)
# ---------------------------------------------------------------------------


async def generate_chapter_title(
    *,
    model_cfg: Dict[str, Any],
    project_title: str,
    directions: List[PlannerDirection],
    chapter_no: int,
    user_intent: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    """综合 Planner 给定的 3 个方向, 提炼一个能代表本章核心的章节级标题.

    返回清洗过的标题 (≤18 字). 失败时返回空串 (调用方决定如何兜底).
    """
    if not directions:
        return ""
    directions_block = "\n".join(
        f"- 方向 {i + 1} · 标题: {d.title}\n"
        f"    梗概: {d.synopsis or '(无)'}\n"
        f"    核心事件: {d.key_event or '(无)'}\n"
        f"    侧重点: {d.focus or '(无)'}"
        for i, d in enumerate(directions)
    )
    vars_payload = {
        "project_title": project_title or "",
        "chapter_no": str(chapter_no),
        "directions_block": directions_block,
        "user_intent": user_intent or "(无额外意图)",
    }
    try:
        raw = await _call_llm(
            model_cfg=model_cfg,
            prompt_key="creation.writer.chapter_title",
            template_vars=vars_payload,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("chapter_title LLM failed: %s", exc)
        return ""
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        title = str(parsed.get("title") or "").strip()
    else:
        # 兜底: 直接从 raw 提取第一行非空文本
        for line in (raw or "").splitlines():
            line = line.strip().strip("\"'` ")
            if line and len(line) <= 30 and not line.startswith(("{", "[", "#", "##", "**")):
                title = line
                break
        else:
            title = ""
    # 清理: 去掉「第N章」「Chapter N」等前缀
    title = re.sub(r"^\s*第[一二三四五六七八九十百千零0-9]+章\s*[:：、\.]?\s*", "", title)
    title = re.sub(r"^\s*Chapter\s+\d+\s*[:：、\.]?\s*", "", title, flags=re.IGNORECASE)
    title = title.strip().strip("\"'`「」《》").strip()
    # 截断到 18 字
    if len(title) > 18:
        title = title[:18]
    return title or f"第 {chapter_no} 章"


# ---------------------------------------------------------------------------
# WriterAgent — 执行 Agent
# ---------------------------------------------------------------------------


class WriterAgent:
    """按方向写完整章节. JSON 失败时把整段 raw 当正文."""

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        project: Dict[str, Any],
        direction: PlannerDirection,
        kg_context: str,
        last_chapter_tail: str,
        user_intent: str,
        chapter_no: int,
        chapter_title: str = "",
    ) -> WriterOutput:
        vars_payload = {
            "project_title": project.get("title", ""),
            "genre": project.get("genre", ""),
            "worldview": project.get("worldview", ""),
            "style_pref": json.dumps(
                project.get("style_pref") or {}, ensure_ascii=False
            ),
            "chapter_title": chapter_title or f"第 {chapter_no} 章",
            "last_chapter_tail": last_chapter_tail or "(无前文, 直接开始)",
            "kg_context": kg_context or "(暂无知识图谱)",
            "direction_title": direction.title,
            "direction_synopsis": direction.synopsis,
            "direction_focus": direction.focus,
            "direction_entities": ", ".join(direction.key_entities) or "(无)",
            "direction_foreshadowing": "; ".join(direction.foreshadowing) or "(无)",
            "direction_tone": direction.tone,
            "direction_constraints": "; ".join(direction.hard_constraints) or "(无)",
            "direction_key_event": direction.key_event,
            "user_intent": user_intent or "(无额外意图)",
            "chapter_no": str(chapter_no),
        }
        prompt_str = json.dumps(vars_payload, ensure_ascii=False)
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.writer.chapter",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("writer LLM failed: %s", exc)
            return WriterOutput(
                content=f"（章节生成失败: {exc}）", focus_summary="", raw=str(exc)
            )
        content = _strip_wrappers(raw).strip()
        if not content:
            content = raw.strip() or "（生成结果为空）"
        focus_summary = self._derive_focus_summary(content, direction)
        return WriterOutput(content=content, focus_summary=focus_summary, raw=raw)

    @staticmethod
    def _derive_focus_summary(content: str, direction: PlannerDirection) -> str:
        first_para = re.split(r"[。\n]", content, maxsplit=2)
        lead = (first_para[0] if first_para else "").strip()[:80]
        focus = direction.focus or ""
        return f"侧重: {focus} | 开篇: {lead}" if focus else f"开篇: {lead}"


def _strip_wrappers(text: str) -> str:
    """去除 LLM 输出中常见的多余包裹 (markdown code fence, 章节标题前缀)."""
    if not text:
        return text
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:markdown|md|text|json)?", "", cleaned).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    # 去除最前面的 "第 X 章" 之类的标题行 (如果整段没有正文, 则保留)
    lines = [ln for ln in cleaned.splitlines() if ln.strip()]
    if lines and re.match(r"^\s*(第[一二三四五六七八九十百千零0-9]+章|Chapter\s+\d+)", lines[0]):
        # 只有当去掉这行后还有内容时才去掉
        if len(lines) > 1:
            lines = lines[1:]
            cleaned = "\n".join(lines).strip()
    return cleaned


# ---------------------------------------------------------------------------
# CriticAgent — 审核 Agent
# ---------------------------------------------------------------------------


class CriticAgent:
    """对单候选章节做 5 维评分, 失败时给最低分 + 兜底建议."""

    DEFAULT_SCORES: Dict[str, float] = {
        "consistency": 6.0,
        "logic": 6.0,
        "foreshadowing": 5.0,
        "style": 6.0,
        "differentiation": 5.0,
    }

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        project: Dict[str, Any],
        direction: PlannerDirection,
        chapter_content: str,
        kg_context: str,
        last_chapter_summary: str,
    ) -> CriticOutput:
        vars_payload = {
            "chapter_content": chapter_content[:6000],
            "project_title": project.get("title", ""),
            "genre": project.get("genre", ""),
            "worldview": project.get("worldview", ""),
            "kg_context": kg_context or "(暂无知识图谱)",
            "last_chapter_summary": last_chapter_summary or "(无前文)",
            "direction_title": direction.title,
            "direction_focus": direction.focus,
            "direction_constraints": "; ".join(direction.hard_constraints) or "(无)",
        }
        prompt_str = json.dumps(vars_payload, ensure_ascii=False)
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.critic.review",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("critic LLM failed: %s", exc)
            return CriticOutput(
                scores=dict(self.DEFAULT_SCORES),
                overall=sum(self.DEFAULT_SCORES.values()) / 5,
                issues=[f"Critic 调用失败: {exc}"],
                modifications=[],
                raw=str(exc),
            )
        return self._parse_critic(raw)

    @classmethod
    def _parse_critic(cls, raw: str) -> CriticOutput:
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return CriticOutput(
                scores=dict(cls.DEFAULT_SCORES),
                overall=sum(cls.DEFAULT_SCORES.values()) / 5,
                issues=["Critic 未返回 JSON, 已采用兜底评分"],
                raw=raw,
            )
        scores_in = parsed.get("scores") or {}
        scores: Dict[str, float] = {}
        for k, default in cls.DEFAULT_SCORES.items():
            try:
                v = float(scores_in.get(k, default))
            except (TypeError, ValueError):
                v = default
            scores[k] = max(0.0, min(10.0, v))
        try:
            overall = float(parsed.get("overall", 0))
        except (TypeError, ValueError):
            overall = 0.0
        if overall <= 0:
            overall = sum(scores.values()) / max(1, len(scores))
        overall = max(0.0, min(10.0, overall))
        return CriticOutput(
            scores=scores,
            overall=overall,
            strengths=[str(x) for x in (parsed.get("strengths") or []) if x],
            issues=[str(x) for x in (parsed.get("issues") or []) if x],
            modifications=[
                str(x) for x in (parsed.get("modifications") or []) if x
            ],
            kg_conflicts=[
                {str(k): str(v) for k, v in item.items()}
                for item in (parsed.get("kg_conflicts") or [])
                if isinstance(item, dict)
            ],
            raw=raw,
        )


# ---------------------------------------------------------------------------
# EntityExtractor — 单章实体抽取 (章节确认后调用)
# ---------------------------------------------------------------------------


@dataclass
class ExtractedKG:
    characters: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    character_event_relations: List[Dict[str, Any]] = field(default_factory=list)
    character_relations: List[Dict[str, Any]] = field(default_factory=list)
    event_relations: List[Dict[str, Any]] = field(default_factory=list)
    raw: str = ""


class EntityExtractor:
    """对单章节正文做 5 段式抽取."""

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        chapter_text: str,
    ) -> ExtractedKG:
        vars_payload = {"chapter_text": chapter_text[:8000]}
        prompt_str = json.dumps(vars_payload, ensure_ascii=False)
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.extractor.entity",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("extractor LLM failed: %s", exc)
            return ExtractedKG(raw=str(exc))
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return ExtractedKG(raw=raw)
        return ExtractedKG(
            characters=[
                {k: v for k, v in c.items() if k in {"entity_id", "name", "attributes"}}
                for c in (parsed.get("characters") or [])
                if isinstance(c, dict)
            ],
            events=[
                {k: v for k, v in e.items() if k in {"entity_id", "name", "attributes"}}
                for e in (parsed.get("events") or [])
                if isinstance(e, dict)
            ],
            character_event_relations=[
                {k: v for k, v in r.items() if k in {"source", "target", "relation", "role", "action"}}
                for r in (parsed.get("character_event_relations") or [])
                if isinstance(r, dict)
            ],
            character_relations=[
                {k: v for k, v in r.items() if k in {"source", "target", "relation", "properties"}}
                for r in (parsed.get("character_relations") or [])
                if isinstance(r, dict)
            ],
            event_relations=[
                {k: v for k, v in r.items() if k in {"source", "target", "relation", "properties"}}
                for r in (parsed.get("event_relations") or [])
                if isinstance(r, dict)
            ],
            raw=raw,
        )


# ---------------------------------------------------------------------------
# Context serializer — 把 KG 序列化为 prompt 片段
# ---------------------------------------------------------------------------


def serialize_kg_for_prompt(
    kg: Dict[str, List[Dict[str, Any]]],
    *,
    planner_directions: Optional[List[Dict[str, Any]]] = None,
    last_chapter_content: str = "",
    outline: str = "",
    last_directions: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """把项目级 KG 压缩成 Planner/Writer 友好的简短文本.

    ③ RAG 排序: 人物/事件/地点按相关度 top-30, 关系跟着实体裁剪.
    ⑥ 结构化字段: importance/role/status/time_label 等直接序列化, 替代旧版 JSON 反解.
    ④ Locations: 单独成段.
    ⑤ Threads: 列出 open / hinting 线索, 提示 Writer 推进/回收.
    ② Warnings: 未解决冲突 + LLM 已知冲突 合并列出, 高优先级提醒.
    """
    # ③ 排序 + top-K
    from services.kg_ranker import rank_kg, _kg_warnings_for_prompt
    ranked = rank_kg(
        kg,
        planner_directions=planner_directions,
        last_chapter_content=last_chapter_content,
        outline=outline,
        last_directions=last_directions,
    )

    chars = ranked.get("characters") or []
    events = ranked.get("events") or []
    locations = ranked.get("locations") or []
    char_rels = ranked.get("character_relations") or []
    char_event_rels = ranked.get("character_event_relations") or []
    event_rels = ranked.get("event_relations") or []

    parts: List[str] = []

    # ② 已知冲突 — 给 LLM 一个硬性提醒
    warnings_text = _kg_warnings_for_prompt(kg)
    if warnings_text and warnings_text != "(无)":
        parts.append("## ⚠ 已知冲突 (本章必须回填或避开)")
        parts.append(warnings_text)

    if chars:
        parts.append("## 已知人物 (按相关度排序)")
        for c in chars:
            name = c.get("name") or c.get("entity_id", "")
            role = c.get("role")
            status = c.get("status")
            faction = c.get("faction")
            importance = c.get("importance")
            attrs = c.get("attributes") or {}
            line = f"- **{name}**"
            meta = []
            if role:
                meta.append(f"角色={role}")
            if status:
                meta.append(f"状态={status}")
            if faction:
                meta.append(f"势力={faction}")
            if importance:
                meta.append(f"重要度={importance}")
            if meta:
                line += f" ({'; '.join(meta)})"
            if attrs:
                # 取前 5 个属性
                attr_items = list(attrs.items())[:5]
                attr_str = "; ".join(f"{k}={v}" for k, v in attr_items)
                line += f" — {attr_str}"
            parts.append(line)
    if events:
        parts.append("\n## 关键事件 (按时间顺序)")
        for e in events:
            name = e.get("name") or e.get("entity_id", "")
            in_story_time = e.get("in_story_time")
            chapter_time_label = e.get("chapter_time_label")
            attrs = e.get("attributes") or {}
            line = f"- {name}"
            meta = []
            if in_story_time:
                meta.append(f"故事内时间: {in_story_time}")
            if chapter_time_label:
                meta.append(f"章内时间: {chapter_time_label}")
            if attrs:
                loc = attrs.get("地点") or attrs.get("location")
                if loc:
                    meta.append(f"地点: {loc}")
            if meta:
                line += f" 〔{'; '.join(meta)}〕"
            parts.append(line)
    if locations:
        parts.append("\n## 已知地点")
        for l in locations:
            name = l.get("name") or l.get("entity_id", "")
            ltype = l.get("location_type")
            attrs = l.get("attributes") or {}
            ctrl = attrs.get("控制势力") or attrs.get("controller")
            line = f"- {name}"
            meta = []
            if ltype:
                meta.append(f"类型={ltype}")
            if ctrl:
                meta.append(f"控制: {ctrl}")
            if meta:
                line += f" ({'; '.join(meta)})"
            parts.append(line)
    if char_rels:
        parts.append("\n## 人物关系")
        for r in char_rels[:15]:
            parts.append(
                f"- {r.get('source_entity_id', '')} --[{r.get('relation', '')}]--> {r.get('target_entity_id', '')}"
            )
    if char_event_rels:
        parts.append("\n## 人物-事件")
        for r in char_event_rels[:15]:
            parts.append(
                f"- {r.get('source_entity_id', '')} 参与 {r.get('target_entity_id', '')}"
                f" (role={r.get('role','') or '-'}, action={r.get('action','') or '-'})"
            )
    if event_rels:
        parts.append("\n## 事件-事件")
        for r in event_rels[:10]:
            t = r.get("relation_type") or ""
            parts.append(
                f"- {r.get('source_entity_id', '')} --[{r.get('relation', '')}{(' / ' + t) if t else ''}]--> {r.get('target_entity_id', '')}"
            )
    if not parts:
        return ""
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# ⑥ Schema 校验 — 抽取出来的实体在入库前先过滤
# ---------------------------------------------------------------------------

# 人物结构化字段: 必填 + 可选
CHAR_ALLOWED = {
    # 必填 (role/status/importance)
    "role", "status", "importance",
    # 可选
    "faction", "current_location_entity_id", "first_appearance_chapter_id",
    # 自由 attributes
    "attributes",
    # 标识
    "entity_id", "name",
}
CHAR_IMPORTANCE_RANGE = (1, 5)
CHAR_ALLOWED_ROLES = {"主角", "配角", "路人", "反派", "未指定", ""}
CHAR_ALLOWED_STATUSES = {"存活", "失踪", "死亡", "转生", "未指定", ""}

EV_ALLOWED = {
    "in_story_time", "chapter_time_label", "importance",
    "attributes", "entity_id", "name",
}
EV_IMPORTANCE_RANGE = (1, 5)

LOC_ALLOWED = {
    "location_type", "attributes", "entity_id", "name",
}
LOC_ALLOWED_TYPES = {"城市", "建筑", "秘境", "区域", "异空间", "未指定", ""}

# 关系 (含 relation_type)
REL_ALLOWED = {
    "source", "target", "source_entity_id", "target_entity_id",
    "relation", "role", "action", "properties", "relation_type",
}

RELATION_TYPES = {"causal", "temporal", "spatial", ""}


def _coerce_int(value: Any, default: int, lo: int, hi: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _coerce_enum(value: Any, allowed: set, default: str = "") -> str:
    if not isinstance(value, str):
        return default
    v = value.strip()
    if v in allowed:
        return v
    # 兼容性: 接受英文 enum
    mapping = {
        "main": "主角", "supporting": "配角", "minor": "路人", "villain": "反派",
        "alive": "存活", "missing": "失踪", "dead": "死亡", "reincarnated": "转生",
        "city": "城市", "building": "建筑", "realm": "秘境", "area": "区域", "exotic": "异空间",
    }
    if v in mapping:
        return mapping[v]
    return default


def validate_extracted_character(c: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """⑥ 校验 + 清洗 1 个 character entity. 返回 (cleaned, warnings)."""
    warnings: List[str] = []
    if not isinstance(c, dict):
        return {}, ["character 不是 dict"]
    cleaned = {k: v for k, v in c.items() if k in CHAR_ALLOWED}
    name = (cleaned.get("name") or "").strip()
    if not name:
        return {}, ["character 缺 name, 丢弃"]
    cleaned["name"] = name
    entity_id = (cleaned.get("entity_id") or "").strip()
    if not entity_id:
        cleaned["entity_id"] = f"char_{(hash(name) & 0xFFFF):03d}"
    # importance 必填 1..5
    cleaned["importance"] = _coerce_int(
        cleaned.get("importance"), 2, *CHAR_IMPORTANCE_RANGE
    )
    # role / status 清洗
    if "role" in cleaned:
        cleaned["role"] = _coerce_enum(cleaned["role"], CHAR_ALLOWED_ROLES)
    if "status" in cleaned:
        cleaned["status"] = _coerce_enum(cleaned["status"], CHAR_ALLOWED_STATUSES)
    # attributes 必须是 dict
    attrs = cleaned.get("attributes")
    if attrs is not None and not isinstance(attrs, dict):
        warnings.append(f"character {name} 的 attributes 不是 dict, 已丢弃")
        cleaned.pop("attributes", None)
    return cleaned, warnings


def validate_extracted_event(e: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if not isinstance(e, dict):
        return {}, ["event 不是 dict"]
    cleaned = {k: v for k, v in e.items() if k in EV_ALLOWED}
    name = (cleaned.get("name") or "").strip()
    if not name:
        return {}, ["event 缺 name, 丢弃"]
    cleaned["name"] = name
    if not (cleaned.get("entity_id") or "").strip():
        cleaned["entity_id"] = f"evt_{(hash(name) & 0xFFFF):03d}"
    cleaned["importance"] = _coerce_int(
        cleaned.get("importance"), 3, *EV_IMPORTANCE_RANGE
    )
    attrs = cleaned.get("attributes")
    if attrs is not None and not isinstance(attrs, dict):
        warnings.append(f"event {name} 的 attributes 不是 dict, 已丢弃")
        cleaned.pop("attributes", None)
    return cleaned, warnings


def validate_extracted_location(l: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if not isinstance(l, dict):
        return {}, ["location 不是 dict"]
    cleaned = {k: v for k, v in l.items() if k in LOC_ALLOWED}
    name = (cleaned.get("name") or "").strip()
    if not name:
        return {}, ["location 缺 name, 丢弃"]
    cleaned["name"] = name
    if not (cleaned.get("entity_id") or "").strip():
        cleaned["entity_id"] = f"loc_{(hash(name) & 0xFFFF):03d}"
    if "location_type" in cleaned:
        cleaned["location_type"] = _coerce_enum(cleaned["location_type"], LOC_ALLOWED_TYPES)
    attrs = cleaned.get("attributes")
    if attrs is not None and not isinstance(attrs, dict):
        warnings.append(f"location {name} 的 attributes 不是 dict, 已丢弃")
        cleaned.pop("attributes", None)
    return cleaned, warnings


def validate_extracted_relation(r: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    warnings: List[str] = []
    if not isinstance(r, dict):
        return {}, ["relation 不是 dict"]
    cleaned = {k: v for k, v in r.items() if k in REL_ALLOWED}
    s = (cleaned.get("source") or cleaned.get("source_entity_id") or "").strip()
    t = (cleaned.get("target") or cleaned.get("target_entity_id") or "").strip()
    if not s or not t:
        return {}, ["relation 缺 source 或 target, 丢弃"]
    cleaned["source_entity_id"] = s
    cleaned["target_entity_id"] = t
    if "relation_type" in cleaned:
        cleaned["relation_type"] = _coerce_enum(cleaned["relation_type"], RELATION_TYPES)
    return cleaned, warnings


# ---------------------------------------------------------------------------
# ④⑥ EntityExtractor v2 — 含 locations + 结构化字段 + schema 校验
# ---------------------------------------------------------------------------


@dataclass
class ExtractedKG:
    characters: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    locations: List[Dict[str, Any]] = field(default_factory=list)
    character_event_relations: List[Dict[str, Any]] = field(default_factory=list)
    character_relations: List[Dict[str, Any]] = field(default_factory=list)
    event_relations: List[Dict[str, Any]] = field(default_factory=list)
    conflicts_in_text: List[Dict[str, Any]] = field(default_factory=list)
    raw: str = ""
    warnings: List[str] = field(default_factory=list)


class EntityExtractor:
    """v2 实体抽取: 人物 + 事件 + 地点 + 3 类关系 + 冲突标注.

    - 使用 v2 提示词 (含 locations + 结构化字段 + conflicts_in_text)
    - 调用前先附上 KG 已知冲突, 让 LLM 在本次抽取中「主动对齐」
    - 入库前对所有实体跑 schema 校验, 丢弃非法项, 收集 warnings
    """

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        chapter_text: str,
        chapter_no: int = 0,
        kg_warnings: str = "(无)",
    ) -> ExtractedKG:
        vars_payload = {
            "chapter_text": chapter_text[:8000],
            "chapter_no": str(chapter_no),
            "kg_warnings": kg_warnings or "(无)",
        }
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.extractor.entity_v2",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("extractor v2 LLM failed: %s", exc)
            return ExtractedKG(raw=str(exc), warnings=[str(exc)])
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return ExtractedKG(raw=raw, warnings=["extractor 未返回 JSON"])
        out = ExtractedKG(raw=raw)
        for c in (parsed.get("characters") or []):
            cleaned, warns = validate_extracted_character(c)
            if cleaned:
                out.characters.append(cleaned)
            out.warnings.extend(warns)
        for e in (parsed.get("events") or []):
            cleaned, warns = validate_extracted_event(e)
            if cleaned:
                out.events.append(cleaned)
            out.warnings.extend(warns)
        for l in (parsed.get("locations") or []):
            cleaned, warns = validate_extracted_location(l)
            if cleaned:
                out.locations.append(cleaned)
            out.warnings.extend(warns)
        for r in (parsed.get("character_event_relations") or []):
            cleaned, warns = validate_extracted_relation(r)
            if cleaned:
                out.character_event_relations.append(cleaned)
            out.warnings.extend(warns)
        for r in (parsed.get("character_relations") or []):
            cleaned, warns = validate_extracted_relation(r)
            if cleaned:
                out.character_relations.append(cleaned)
            out.warnings.extend(warns)
        for r in (parsed.get("event_relations") or []):
            cleaned, warns = validate_extracted_relation(r)
            if cleaned:
                out.event_relations.append(cleaned)
            out.warnings.extend(warns)
        for c in (parsed.get("conflicts_in_text") or []):
            if isinstance(c, dict):
                out.conflicts_in_text.append({k: str(v) for k, v in c.items()})
        return out


# ---------------------------------------------------------------------------
# ⑤ ThreadExtractor — 伏笔/剧情线索抽取
# ---------------------------------------------------------------------------


@dataclass
class ThreadAction:
    thread_id: str
    action: str  # create | update | resolve | drop
    title: str = ""
    thread_type: str = ""
    status: str = "open"
    priority: int = 3
    related_entity_ids: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class ThreadsOutput:
    threads: List[ThreadAction] = field(default_factory=list)
    raw: str = ""


class ThreadExtractor:
    """从已确认的章节正文中识别 / 更新 / 回收 / 放弃 剧情线索."""

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        chapter_content: str,
        chapter_no: int,
        open_threads: List[Dict[str, Any]],
    ) -> ThreadsOutput:
        # 把 open threads 序列化成简洁的 prompt 输入
        open_lines = []
        for t in open_threads[:30]:
            open_lines.append(
                f"- {t.get('thread_id', '?')}: {t.get('title', '?')} "
                f"[{t.get('status', '?')}, p={t.get('priority', '?')}, "
                f"type={t.get('thread_type', '?')}]"
            )
        open_threads_text = "\n".join(open_lines) or "(无已知未结线索)"

        vars_payload = {
            "chapter_content": chapter_content[:8000],
            "chapter_no": str(chapter_no),
            "open_threads": open_threads_text,
        }
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.extractor.plot_thread",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("thread_extractor LLM failed: %s", exc)
            return ThreadsOutput(raw=str(exc))
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return ThreadsOutput(raw=raw)
        out = ThreadsOutput(raw=raw)
        for t in (parsed.get("threads") or []):
            if not isinstance(t, dict):
                continue
            ta = ThreadAction(
                thread_id=str(t.get("thread_id") or f"thread_{(hash(str(t.get('title'))) & 0xFFFF):03d}"),
                action=str(t.get("action") or "create"),
                title=str(t.get("title") or ""),
                thread_type=str(t.get("thread_type") or ""),
                status=str(t.get("status") or "open"),
                priority=_coerce_int(t.get("priority"), 3, 1, 5),
                related_entity_ids=[
                    str(x) for x in (t.get("related_entity_ids") or [])
                    if isinstance(x, (str, int))
                ],
                notes=str(t.get("notes") or ""),
            )
            if ta.action not in {"create", "update", "resolve", "drop"}:
                ta.action = "create"
            out.threads.append(ta)
        return out


# ---------------------------------------------------------------------------
# ⑦ CompassAgent — 偏离度检测
# ---------------------------------------------------------------------------


@dataclass
class CompassOutput:
    scores: Dict[str, float] = field(default_factory=dict)
    overall: float = 0.0
    summary: str = ""
    warnings: List[Dict[str, str]] = field(default_factory=list)
    raw: str = ""


class CompassAgent:
    """在 confirm_chapter 前调用: 5 维评估是否偏离."""

    DEFAULT_SCORES = {
        "theme_deviation": 8.0,
        "outline_deviation": 8.0,
        "character_consistency": 8.0,
        "foreshadowing_progress": 8.0,
        "style_consistency": 8.0,
    }

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        project: Dict[str, Any],
        chapter: Dict[str, Any],
        chapter_content: str,
        open_threads: List[Dict[str, Any]],
        kg_warnings: str = "(无)",
    ) -> CompassOutput:
        # 根设定
        settings_lines = [
            f"标题: {project.get('title', '')}",
            f"类型: {project.get('genre', '')}",
            f"世界观: {project.get('worldview', '')}",
            f"文风偏好: {json.dumps(project.get('style_pref') or {}, ensure_ascii=False)}",
        ]
        root_settings = "\n".join(settings_lines)
        # 已知未结线索
        threads_lines = []
        for t in open_threads[:20]:
            threads_lines.append(
                f"- [{t.get('thread_id', '?')}] {t.get('title', '?')} "
                f"({t.get('thread_type', '?')}, {t.get('status', '?')}, p={t.get('priority', '?')})"
            )
        open_threads_text = "\n".join(threads_lines) or "(无)"

        vars_payload = {
            "root_settings": root_settings,
            "outline": project.get("outline", ""),
            "chapter_title": chapter.get("title", ""),
            "chapter_content": chapter_content[:6000],
            "chapter_no": str(chapter.get("chapter_no", "")),
            "open_threads": open_threads_text,
            "kg_warnings": kg_warnings or "(无)",
        }
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.compass.deviation",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("compass LLM failed: %s", exc)
            return CompassOutput(
                scores=dict(self.DEFAULT_SCORES),
                overall=sum(self.DEFAULT_SCORES.values()) / 5,
                summary=f"Compass 调用失败: {exc}",
                raw=str(exc),
            )
        return self._parse_compass(raw)

    @classmethod
    def _parse_compass(cls, raw: str) -> CompassOutput:
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return CompassOutput(
                scores=dict(cls.DEFAULT_SCORES),
                overall=sum(cls.DEFAULT_SCORES.values()) / 5,
                summary="Compass 未返回 JSON, 已采用兜底评分",
                raw=raw,
            )
        scores_in = parsed.get("scores") or {}
        scores: Dict[str, float] = {}
        for k, default in cls.DEFAULT_SCORES.items():
            try:
                v = float(scores_in.get(k, default))
            except (TypeError, ValueError):
                v = default
            scores[k] = max(0.0, min(10.0, v))
        try:
            overall = float(parsed.get("overall", 0))
        except (TypeError, ValueError):
            overall = 0.0
        if overall <= 0:
            overall = sum(scores.values()) / max(1, len(scores))
        overall = max(0.0, min(10.0, overall))
        warnings = []
        for w in (parsed.get("warnings") or []):
            if isinstance(w, dict):
                warnings.append({k: str(v) for k, v in w.items()})
        return CompassOutput(
            scores=scores,
            overall=overall,
            summary=str(parsed.get("summary") or ""),
            warnings=warnings,
            raw=raw,
        )


# ---------------------------------------------------------------------------
# ⑧ BridgeAgent — 跨章接缝检测
# ---------------------------------------------------------------------------


@dataclass
class BridgeOutput:
    bridge_score: float = 8.0
    conflicts: List[str] = field(default_factory=list)
    open_hook_suggestions: List[str] = field(default_factory=list)
    raw: str = ""


class BridgeAgent:
    """生成第 N+1 章时调用: 检测上一章末尾 → 本章方向 的衔接质量 + 推荐开头钩子."""

    async def run(
        self,
        *,
        model_cfg: Dict[str, Any],
        prev_tail: str,
        direction: PlannerDirection,
        kg_warnings: str = "(无)",
    ) -> BridgeOutput:
        vars_payload = {
            "prev_tail": prev_tail[:1500],
            "direction_title": direction.title,
            "direction_synopsis": direction.synopsis,
            "direction_entities": ", ".join(direction.key_entities) or "(无)",
            "direction_foreshadowing": "; ".join(direction.foreshadowing) or "(无)",
            "direction_key_event": direction.key_event,
            "kg_warnings": kg_warnings or "(无)",
        }
        try:
            raw = await _call_llm(
                model_cfg=model_cfg,
                prompt_key="creation.bridge.transition",
                template_vars=vars_payload,
            )
        except AgentCallError as exc:
            logger.warning("bridge LLM failed: %s", exc)
            return BridgeOutput(raw=str(exc))
        parsed = _extract_json(raw)
        if not isinstance(parsed, dict):
            return BridgeOutput(raw=raw)
        try:
            score = float(parsed.get("bridge_score", 8.0))
        except (TypeError, ValueError):
            score = 8.0
        return BridgeOutput(
            bridge_score=max(0.0, min(10.0, score)),
            conflicts=[str(x) for x in (parsed.get("conflicts") or [])],
            open_hook_suggestions=[
                str(x) for x in (parsed.get("open_hook_suggestions") or [])
            ],
            raw=raw,
        )


# ---------------------------------------------------------------------------
# ⑤ Threads 序列化 — 给 Planner/Writer 列出未结线索
# ---------------------------------------------------------------------------

THREAD_STATUSES = {"open", "hinting", "resolving", "resolved", "dropped"}


def serialize_threads_for_prompt(
    threads: List[Dict[str, Any]],
    *,
    only_active: bool = True,
) -> str:
    """把当前 KG 中的 plot_threads 序列化为 prompt 文本.

    only_active=True 时只列 open/hinting (Writer 视角, 提示推进).
    """
    if not threads:
        return ""
    parts: List[str] = []
    open_count = 0
    resolved_count = 0
    for t in threads:
        status = t.get("status") or "open"
        if status in ("resolved", "dropped"):
            resolved_count += 1
            if only_active:
                continue
        else:
            open_count += 1
        thread_id = t.get("thread_id") or "?"
        title = t.get("title") or "(无标题)"
        ttype = t.get("thread_type") or ""
        priority = t.get("priority") or 3
        notes = (t.get("notes") or "").strip()
        line = f"- [{thread_id}] **{title}**"
        meta = []
        if ttype:
            meta.append(ttype)
        meta.append(f"p={priority}")
        meta.append(f"状态={status}")
        line += f" 〔{'; '.join(meta)}〕"
        if notes:
            line += f"\n  备注: {notes[:80]}{'…' if len(notes) > 80 else ''}"
        parts.append(line)
    summary = (
        f"当前未结线索 {open_count} 条, 已回收 {resolved_count} 条. "
        f"主线 (p≥4) 必须在本章推进/回收至少 1 条."
    )
    return summary + ("\n" + "\n".join(parts) if parts else "")


# ---------------------------------------------------------------------------
# ⑨ Themes 序列化 — 主题进度
# ---------------------------------------------------------------------------


def serialize_themes_for_prompt(
    themes_progress: Optional[List[Dict[str, Any]]],
    *,
    current_themes: Optional[List[str]] = None,
) -> str:
    """把项目级 themes_progress 序列化为 Writer 提示词中的「主题进度」片段."""
    if not themes_progress and not current_themes:
        return ""
    parts: List[str] = []
    if themes_progress:
        for t in themes_progress:
            name = t.get("theme") or "?"
            progress = t.get("progress", 0)
            stage = t.get("stage", "铺垫")
            bar_len = 10
            filled = round(min(1.0, max(0.0, progress)) * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            parts.append(f"- {name}  {bar}  {int(progress*100)}% 〔{stage}〕")
    if current_themes:
        parts.append("本章要触碰的主题: " + " / ".join(current_themes))
    return "\n".join(parts)


