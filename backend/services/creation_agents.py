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
    user_prompt: str,
    fallback_user_prompt: str = "",
) -> str:
    """统一 LLM 调用: 解析 prompt → 调 ai_service → 返回 content 字符串."""
    tmpl = await _resolve_prompt(prompt_key)
    system_prompt = tmpl.get("system_prompt", "") or ""
    raw_user_tmpl = tmpl.get("user_prompt_template", "") or fallback_user_prompt
    try:
        temperature = float(tmpl.get("temperature") or 0.5)
    except (TypeError, ValueError):
        temperature = 0.5
    try:
        max_tokens = int(tmpl.get("max_tokens") or 2400)
    except (TypeError, ValueError):
        max_tokens = 2400
    if raw_user_tmpl and "{" in raw_user_tmpl:
        try:
            user_prompt_resolved = raw_user_tmpl.format_map(_SafeDict(user_prompt))
        except Exception as exc:  # noqa: BLE001
            logger.warning("prompt.format failed for %s: %s", prompt_key, exc)
            user_prompt_resolved = raw_user_tmpl
    else:
        # 没有模板时, 直接把 user_prompt 作为整段输入
        user_prompt_resolved = user_prompt

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
                user_prompt=prompt_str,
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
    ) -> WriterOutput:
        vars_payload = {
            "project_title": project.get("title", ""),
            "genre": project.get("genre", ""),
            "worldview": project.get("worldview", ""),
            "style_pref": json.dumps(
                project.get("style_pref") or {}, ensure_ascii=False
            ),
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
                user_prompt=prompt_str,
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
                user_prompt=prompt_str,
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
                user_prompt=prompt_str,
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


def serialize_kg_for_prompt(kg: Dict[str, List[Dict[str, Any]]]) -> str:
    """把项目级 KG 压缩成 Planner/Writer 友好的简短文本."""
    chars = kg.get("characters") or []
    events = kg.get("events") or []
    char_rels = kg.get("character_relations") or []
    char_event_rels = kg.get("character_event_relations") or []
    event_rels = kg.get("event_relations") or []

    parts: List[str] = []
    if chars:
        parts.append("## 已知人物")
        for c in chars[:20]:
            name = c.get("name") or c.get("entity_id", "")
            attrs = c.get("attributes") or {}
            attr_str = "; ".join(f"{k}={v}" for k, v in attrs.items()) if attrs else ""
            line = f"- {name}"
            if attr_str:
                line += f" ({attr_str})"
            parts.append(line)
    if events:
        parts.append("\n## 关键事件")
        for e in events[:15]:
            name = e.get("name") or e.get("entity_id", "")
            attrs = e.get("attributes") or {}
            attr_str = "; ".join(f"{k}={v}" for k, v in attrs.items()) if attrs else ""
            line = f"- {name}"
            if attr_str:
                line += f" ({attr_str})"
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
            parts.append(
                f"- {r.get('source_entity_id', '')} --[{r.get('relation', '')}]--> {r.get('target_entity_id', '')}"
            )
    if not parts:
        return ""
    return "\n".join(parts).strip()
