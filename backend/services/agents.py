"""Multi-agent knowledge graph extraction.

Two cooperating agents:

* ``ExtractorAgent``  — runs the 5 extraction phases and attaches
  ``evidence`` (a snippet of the source chunk) and ``confidence`` to every
  emitted item, so the validator can cross-check against the original text.

* ``MergeValidatorAgent`` — runs hard-rule normalization (whitespace in
  attribute keys, parens in names, reference integrity, coverage stats)
  plus optional LLM soft checks (dedup of likely-duplicate characters,
  completeness scan of the original chunks).

The two agents are stateless across calls. The orchestrator
(``kg_service``) owns model config + prompt templates and wires the agents
together. The validator returns a ``ValidatedKG`` plus a list of
``ValidationIssue`` entries; the orchestrator decides whether to trigger a
feedback re-extract.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from services import ai_service
from services.kg_service import (
    build_character_prompt,
    build_event_prompt,
    build_participation_prompt,
    build_char_relation_prompt,
    build_event_relation_prompt,
    parse_character_payload,
    parse_event_payload,
    parse_participation_payload,
    parse_char_relation_payload,
    parse_event_relation_payload,
    DEFAULT_CHUNK_SIZE,
    MAX_CONCURRENCY,
)
from services.prompt_service import get_active_prompt_by_key, get_default_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class EvidenceSpan:
    """可定位的原文证据片段, 支持前端跳转 + 高亮.

    Attributes:
        chunk_id:   该 span 所在 chunk 的 ID(对应 chunk_novel 输出).
        quote:      原文片段, 通常 30~200 字符.
        start:      quote 在 chunk 文本内的字符 offset (Python str index).
                    若 chunk 文本在 evidence 落库后才被改写、quote 找不到,
                    ``start`` 留空, 前端回退到 ``quote.find`` 兜底.
        end:        ``start + len(quote)``.
        strategy:   "anchor" 表示基于实体名/属性锚点定位; "head" 是段首兜底;
                    "fallback" 表示 quote 没法在原文找到, 只作为提示.
        sentence_idx: 该 span 所在句子的索引(以 chunk 文本为单位的分句).
                      可选, 用于前端"跳到第 N 句"级别的快速跳转.
    """

    chunk_id: str = ""
    quote: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    strategy: str = "anchor"  # anchor | head | fallback
    sentence_idx: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "quote": self.quote,
            "start": self.start,
            "end": self.end,
            "strategy": self.strategy,
            "sentence_idx": self.sentence_idx,
        }


def _find_offsets(
    chunk_text: str, quote: str
) -> Tuple[Optional[int], Optional[int]]:
    """在 chunk_text 中找 quote 的字符级 offset. 找不到返回 (None, None).

    容许 80% 长度前缀匹配, 处理 LLM 截断/末尾标点差异.
    """
    if not chunk_text or not quote:
        return None, None
    idx = chunk_text.find(quote)
    if idx >= 0:
        return idx, idx + len(quote)
    # 退化: 去掉末尾标点再找
    trimmed = quote.rstrip("。.!?！？,，;；:：\"'""''")
    if trimmed and trimmed != quote:
        idx = chunk_text.find(trimmed)
        if idx >= 0:
            return idx, idx + len(trimmed)
    # 退化: 用 quote 头部 80% 找
    head = quote[: max(8, int(len(quote) * 0.8))]
    idx = chunk_text.find(head)
    if idx >= 0:
        return idx, idx + len(head)
    return None, None


def _split_sentences(text: str) -> List[str]:
    """极简中英文分句: 以 。.!?,;!?; \n 切."""
    if not text:
        return []
    pattern = re.compile(r"[。.!?！？\n]+")
    return [s for s in pattern.split(text) if s.strip()]


def _sentence_index_of(text: str, offset: int) -> Optional[int]:
    """给定字符 offset, 返回该 offset 所在句子的索引 (0-based)."""
    if not text or offset is None or offset < 0:
        return None
    sentences = _split_sentences(text)
    cursor = 0
    for i, s in enumerate(sentences):
        # 句子真实末尾 = cursor + len(sentence) + 分句符长度
        end = cursor + len(s)
        if cursor <= offset <= end:
            return i
        # 跨过分句符前进
        cursor = end + 1
        if cursor > offset:
            return i
    return len(sentences) - 1 if sentences else None


@dataclass
class ExtractedItem:
    """One entity/relation extracted by the ExtractorAgent."""

    kind: str  # character | event | participation | char_relation | event_relation
    data: Dict[str, Any]
    chunk_id: str = ""
    # 升级为 List[EvidenceSpan] 支持原文跳转 + 高亮
    evidence: List[EvidenceSpan] = field(default_factory=list)
    confidence: float = 0.5   # LLM 自评 0~1, 缺省 0.5

    def primary_evidence(self) -> str:
        """取首条 evidence 的 quote, 兼容旧代码."""
        return self.evidence[0].quote if self.evidence else ""


@dataclass
class PhaseOutput:
    """Result of a single extraction phase."""

    phase: str
    items: List[ExtractedItem] = field(default_factory=list)
    raw_text_by_chunk: Dict[str, str] = field(default_factory=dict)

    def dicts_by_chunk(self) -> List[List[Dict[str, Any]]]:
        """Re-group ``items`` into per-chunk lists of dicts (for merge_*)."""
        out: List[List[Dict[str, Any]]] = []
        idx: Dict[str, int] = {}
        for it in self.items:
            cid = it.chunk_id
            if cid not in idx:
                idx[cid] = len(out)
                out.append([])
            out[idx[cid]].append(it.data)
        return out


@dataclass
class ValidationIssue:
    """A problem detected by the MergeValidatorAgent."""

    severity: str  # "warn" | "error"
    code: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidatedKG:
    """The validated knowledge graph, ready for persistence."""

    characters: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    participations: List[Dict[str, Any]]
    char_relations: List[Dict[str, Any]]
    event_relations: List[Dict[str, Any]]
    issues: List[ValidationIssue] = field(default_factory=list)
    dedup_log: List[Dict[str, Any]] = field(default_factory=list)
    coverage: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phase dispatch (centralised prompt builder for all 5 phases)
# ---------------------------------------------------------------------------


def build_phase_prompt(
    phase: str,
    chunk: Dict[str, Any],
    prompts: Dict[str, Dict[str, Any]],
    *,
    character_list_json: str = "[]",
    event_list_json: str = "[]",
) -> str:
    """Dispatch a single chunk through the right prompt builder.

    The ``prompts`` argument is the DB-loaded dict produced by
    ``kg_service.resolve_prompts_async``. Passing it through explicitly
    is what makes the user-edited ``user_prompt_template`` from the
    settings UI actually reach the LLM (the previous design relied on
    a process-local cache that only ever held the bundled default).

    Replaces the original ``_run_phase`` callsite that passed chunk dicts
    directly to ``build_character_prompt`` (a string-typed function),
    which silently substituted the dict's repr into the prompt.
    """
    text = (chunk.get("content") or "") if isinstance(chunk, dict) else str(chunk)
    if phase == "character":
        return build_character_prompt(text, prompts)
    if phase == "event":
        return build_event_prompt(text, character_list_json, prompts)
    if phase == "participation":
        return build_participation_prompt(
            text, character_list_json, event_list_json, prompts
        )
    if phase == "char_relation":
        return build_char_relation_prompt(text, character_list_json, prompts)
    if phase == "event_relation":
        return build_event_relation_prompt(text, event_list_json, prompts)
    raise ValueError(f"unknown phase: {phase}")


# ---------------------------------------------------------------------------
# ExtractorAgent
# ---------------------------------------------------------------------------


class ExtractorAgent:
    """5-phase extraction. Attaches evidence + confidence to every item.

    Stateless across calls. The orchestrator owns the model config and
    the active prompt templates (resolved from the DB by
    ``kg_service.resolve_prompts_async``).
    """

    def __init__(
        self,
        model_cfg: Dict[str, Any],
        prompts: Dict[str, Dict[str, Any]],
        *,
        max_concurrency: int = MAX_CONCURRENCY,
    ) -> None:
        self.model_cfg = model_cfg
        self.prompts = prompts
        self.concurrency = max(1, max_concurrency)

    async def run_phase(
        self,
        phase: str,
        chunks: List[Dict[str, Any]],
        *,
        character_list_json: str = "[]",
        event_list_json: str = "[]",
    ) -> PhaseOutput:
        tmpl = self.prompts[phase]
        parser = self._parser_for(phase)
        sem = asyncio.Semaphore(self.concurrency)
        raw_by_chunk: Dict[str, str] = {}

        async def _one(chunk: Dict[str, Any]) -> List[ExtractedItem]:
            async with sem:
                user_prompt = build_phase_prompt(
                    phase, chunk, self.prompts,
                    character_list_json=character_list_json,
                    event_list_json=event_list_json,
                )
                try:
                    raw = await ai_service.chat_completion(
                        provider=self.model_cfg["provider"],
                        model_url=self.model_cfg["model_url"],
                        api_key=self.model_cfg["api_key"],
                        model_name=self.model_cfg["model_name"],
                        system_prompt=tmpl.get("system_prompt", ""),
                        user_prompt=user_prompt,
                        temperature=float(tmpl.get("temperature") or 0.3),
                        max_tokens=int(tmpl.get("max_tokens") or 2400),
                        retries=2,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "extractor %s chunk %s failed: %s",
                        phase, chunk.get("id"), exc,
                    )
                    return []
                raw_by_chunk[str(chunk.get("id", ""))] = raw
                try:
                    parsed = parser(raw)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("extractor %s parse failed: %s", phase, exc)
                    return []
                text = chunk.get("content", "") or ""
                cid = str(chunk.get("id", ""))
                out: List[ExtractedItem] = []
                for obj in parsed:
                    out.append(
                        ExtractedItem(
                            kind=phase,
                            data=obj,
                            chunk_id=cid,
                            evidence=self._make_evidence(obj, text, chunk_id=cid),
                            confidence=self._read_confidence(obj),
                        )
                    )
                return out

        results = await asyncio.gather(*[_one(c) for c in chunks])
        items: List[ExtractedItem] = []
        for batch in results:
            items.extend(batch)
        return PhaseOutput(phase=phase, items=items, raw_text_by_chunk=raw_by_chunk)

    # --- helpers ----------------------------------------------------------

    @staticmethod
    def _parser_for(phase: str) -> Callable[[str], List[Dict[str, Any]]]:
        return {
            "character": parse_character_payload,
            "event": parse_event_payload,
            "participation": parse_participation_payload,
            "char_relation": parse_char_relation_payload,
            "event_relation": parse_event_relation_payload,
        }[phase]

    @staticmethod
    def _make_evidence(
        obj: Dict[str, Any],
        chunk_text: str,
        chunk_id: str = "",
        *,
        span: int = 120,
    ) -> List[EvidenceSpan]:
        """Pick a representative evidence snippet from chunk_text.

        返回带 offset 的 EvidenceSpan 列表(目前 1 条), 支持前端跳转 + 高亮.
        """
        if not chunk_text:
            return []
        anchor = ""
        if isinstance(obj, dict):
            name = obj.get("name")
            if isinstance(name, str) and name:
                anchor = name
            else:
                # 关系类的 evidence 用 source/target 拼接作锚点
                src = obj.get("source")
                tgt = obj.get("target")
                if src and tgt:
                    anchor = f"{src}"
                else:
                    for v in (obj.get("attributes") or {}).values():
                        if isinstance(v, str) and len(v) > len(anchor):
                            anchor = v[:20]
        if not anchor:
            quote = chunk_text[:span]
            start, end = 0, len(quote)
            return [EvidenceSpan(
                chunk_id=chunk_id, quote=quote, start=start, end=end,
                strategy="head", sentence_idx=0,
            )]
        idx = chunk_text.find(anchor)
        if idx < 0 and isinstance(obj, dict):
            # 关系类二次尝试: 用 action / role / relation 文案做锚点
            for k in ("action", "role", "relation"):
                v = obj.get(k)
                if isinstance(v, str) and v and v not in {
                    "PARTICIPATES_IN", "关联", "相关"
                } and len(v) >= 2:
                    idx2 = chunk_text.find(v)
                    if idx2 >= 0:
                        idx = idx2
                        break
        if idx < 0:
            # 锚点找不到: 退化为段首 + fallback 标记
            quote = chunk_text[:span]
            return [EvidenceSpan(
                chunk_id=chunk_id, quote=quote, start=0, end=len(quote),
                strategy="head", sentence_idx=0,
            )]
        start = max(0, idx - 20)
        quote = chunk_text[start : start + span]
        s, e = _find_offsets(chunk_text, quote)
        sent_idx = _sentence_index_of(chunk_text, s) if s is not None else None
        return [EvidenceSpan(
            chunk_id=chunk_id, quote=quote, start=s, end=e,
            strategy="anchor", sentence_idx=sent_idx,
        )]

    @staticmethod
    def _read_confidence(obj: Dict[str, Any]) -> float:
        if not isinstance(obj, dict):
            return 0.5
        for k in ("confidence", "_confidence", "置信度"):
            v = obj.get(k)
            if isinstance(v, (int, float)):
                return max(0.0, min(1.0, float(v)))
        return 0.5


# ---------------------------------------------------------------------------
# MergeValidatorAgent
# ---------------------------------------------------------------------------


class MergeValidatorAgent:
    """Hard-rule normalization + reference integrity + coverage stats +
    optional LLM dedup / completeness scan.
    """

    # ---- hard rules ----------------------------------------------------

    @staticmethod
    def _normalize_attr_keys(
        attrs: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Collapse internal whitespace in attribute keys (e.g. ' 结果' -> '结果').

        Returns the new dict and a list of rename operations performed.
        On collision (different original keys normalising to the same new
        key), the first occurrence wins.
        """
        if not isinstance(attrs, dict):
            return {}, []
        renamed: List[str] = []
        out: Dict[str, Any] = {}
        for k, v in attrs.items():
            new_k = re.sub(r"\s+", "", str(k)).strip()
            if not new_k or new_k in out:
                continue
            if new_k != k:
                renamed.append(f"{k} -> {new_k}")
            out[new_k] = v
        return out, renamed

    @staticmethod
    def _strip_name_parens(name: str) -> str:
        """Remove parenthetical notes, e.g. '我(叙述者)' -> '我'."""
        if not name:
            return name
        return re.sub(r"[（(][^)）]*[)）]", "", str(name)).strip()

    def normalize_entities(
        self,
        characters: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[ValidationIssue]]:
        issues: List[ValidationIssue] = []
        new_chars: List[Dict[str, Any]] = []
        for c in characters:
            attrs = c.get("attributes") or {}
            new_attrs, renamed = self._normalize_attr_keys(attrs)
            name = self._strip_name_parens(c.get("name", ""))
            if name != c.get("name", ""):
                issues.append(
                    ValidationIssue(
                        severity="warn",
                        code="name_parens_stripped",
                        message=(
                            f"人物 {c.get('id')} 名字去除括号注释: "
                            f"{c.get('name')!r} -> {name!r}"
                        ),
                        payload={"id": c.get("id"), "before": c.get("name"), "after": name},
                    )
                )
            for r in renamed:
                issues.append(
                    ValidationIssue(
                        severity="warn",
                        code="attr_key_whitespace",
                        message=f"人物 {c.get('id')} 属性键归一化: {r}",
                        payload={"id": c.get("id"), "rename": r},
                    )
                )
            new_chars.append({**c, "name": name, "attributes": new_attrs})

        new_evts: List[Dict[str, Any]] = []
        for e in events:
            attrs = e.get("attributes") or {}
            new_attrs, renamed = self._normalize_attr_keys(attrs)
            for r in renamed:
                issues.append(
                    ValidationIssue(
                        severity="warn",
                        code="attr_key_whitespace",
                        message=f"事件 {e.get('id')} 属性键归一化: {r}",
                        payload={"id": e.get("id"), "rename": r},
                    )
                )
            new_evts.append({**e, "attributes": new_attrs})
        return new_chars, new_evts, issues

    @staticmethod
    def validate_references(
        characters: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        participations: List[Dict[str, Any]],
        char_relations: List[Dict[str, Any]],
        event_relations: List[Dict[str, Any]],
    ) -> List[ValidationIssue]:
        """Ensure every relation's source/target points to a known entity."""
        char_ids = {c.get("id") for c in characters}
        evt_ids = {e.get("id") for e in events}
        issues: List[ValidationIssue] = []
        for r in participations:
            if r.get("source") not in char_ids or r.get("target") not in evt_ids:
                issues.append(ValidationIssue(
                    "error", "orphan_participation",
                    f"参与关系孤儿: {r.get('source')} -> {r.get('target')}",
                    r,
                ))
        for r in char_relations:
            if r.get("source") not in char_ids or r.get("target") not in char_ids:
                issues.append(ValidationIssue(
                    "error", "orphan_char_relation",
                    f"人物关系孤儿: {r.get('source')} -> {r.get('target')}",
                    r,
                ))
        for r in event_relations:
            if r.get("source") not in evt_ids or r.get("target") not in evt_ids:
                issues.append(ValidationIssue(
                    "error", "orphan_event_relation",
                    f"事件关系孤儿: {r.get('source')} -> {r.get('target')}",
                    r,
                ))
        return issues

    @staticmethod
    def coverage_check(
        characters: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        participations: List[Dict[str, Any]],
        *,
        min_participants: int = 1,
    ) -> Tuple[Dict[str, Any], List[ValidationIssue]]:
        """Per-event participant count + events without participants."""
        char_ids = {c.get("id") for c in characters}
        evt_ids = {e.get("id") for e in events}
        per_event: Dict[str, int] = {eid: 0 for eid in evt_ids}
        for r in participations:
            tgt = r.get("target")
            if tgt in per_event:
                per_event[tgt] += 1
        orphans = [eid for eid, cnt in per_event.items() if cnt < min_participants]
        issues = [
            ValidationIssue(
                "warn", "missing_participation",
                f"事件 {eid} 参与数 < {min_participants}",
                {"event": eid, "count": per_event[eid]},
            )
            for eid in orphans
        ]
        report = {
            "characters": len(characters),
            "events": len(events),
            "participations": len(participations),
            "per_event_participant_count": per_event,
            "events_without_participant": orphans,
            "unused_characters": sorted(
                char_ids - {r.get("source") for r in participations}
            ),
        }
        return report, issues

    # ---- LLM soft checks ------------------------------------------------

    async def llm_dedup(
        self,
        characters: List[Dict[str, Any]],
        evidence_by_id: Dict[str, str],
        model_cfg: Dict[str, Any],
        tmpl: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Greedy cluster + LLM confirm.

        Iteratively picks a seed character and asks the LLM whether every
        remaining character is the same person; those confirmed are folded
        into the cluster. Returns the merged list (re-id'd char_001..N)
        and a dedup log.
        """
        if len(characters) < 2:
            return characters, []
        tmpl = tmpl or get_default_prompt("kg.validator.dedup") or {}
        remaining = list(characters)
        clusters: List[List[Dict[str, Any]]] = []
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            rest: List[Dict[str, Any]] = []
            for c in remaining:
                same = await self._ask_dedup(seed, c, evidence_by_id, model_cfg, tmpl)
                if same:
                    cluster.append(c)
                else:
                    rest.append(c)
            clusters.append(cluster)
            remaining = rest

        merged: List[Dict[str, Any]] = []
        log: List[Dict[str, Any]] = []
        for cluster in clusters:
            if len(cluster) == 1:
                merged.append(cluster[0])
                continue
            base = dict(cluster[0])
            for other in cluster[1:]:
                base["attributes"] = {
                    **(base.get("attributes") or {}),
                    **(other.get("attributes") or {}),
                }
            base["name"] = max(
                (c.get("name", "") for c in cluster),
                key=lambda n: (len(self._strip_name_parens(n)), n),
            )
            merged.append(base)
            log.append({
                "kept": base.get("id"),
                "merged_from": [c.get("id") for c in cluster],
                "names": [c.get("name", "") for c in cluster],
            })
        for i, c in enumerate(merged, start=1):
            c["id"] = f"char_{i:03d}"
        return merged, log

    async def _ask_dedup(
        self,
        a: Dict[str, Any],
        b: Dict[str, Any],
        evidence_by_id: Dict[str, str],
        model_cfg: Dict[str, Any],
        tmpl: Dict[str, Any],
    ) -> bool:
        evidence = (
            a.get("evidence") or b.get("evidence")
            or evidence_by_id.get(a.get("chunk_id", ""), "")
            or evidence_by_id.get(b.get("chunk_id", ""), "")
        )[:400]
        user_prompt = tmpl.get("user_prompt_template", "").format(
            a_json=json.dumps(
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "attributes": a.get("attributes") or {},
                },
                ensure_ascii=False,
            ),
            b_json=json.dumps(
                {
                    "id": b.get("id"),
                    "name": b.get("name"),
                    "attributes": b.get("attributes") or {},
                },
                ensure_ascii=False,
            ),
            evidence=evidence,
        )
        try:
            raw = await ai_service.chat_completion(
                provider=model_cfg["provider"],
                model_url=model_cfg["model_url"],
                api_key=model_cfg["api_key"],
                model_name=model_cfg["model_name"],
                system_prompt=tmpl.get("system_prompt", ""),
                user_prompt=user_prompt,
                temperature=float(tmpl.get("temperature") or 0.1),
                max_tokens=int(tmpl.get("max_tokens") or 800),
                retries=2,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("dedup llm call failed: %s", exc)
            return False
        parsed = ai_service.parse_json_object(raw) or {}
        return bool(parsed.get("is_same"))

    async def llm_completeness(
        self,
        characters: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        participations: List[Dict[str, Any]],
        chunks: List[Dict[str, Any]],
        model_cfg: Dict[str, Any],
        tmpl: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """For each chunk, ask the LLM whether anything obvious was missed.

        Returns a dict with keys ``missing_characters``, ``missing_events``,
        ``missing_participations``.
        """
        tmpl = tmpl or get_default_prompt("kg.validator.completeness") or {}
        report: Dict[str, Any] = {
            "missing_characters": [],
            "missing_events": [],
            "missing_participations": [],
        }
        char_json = json.dumps(
            [{"id": c.get("id"), "name": c.get("name")} for c in characters],
            ensure_ascii=False,
        )
        evt_json = json.dumps(
            [{"id": e.get("id"), "name": e.get("name")} for e in events],
            ensure_ascii=False,
        )
        part_json = json.dumps(
            [
                {"source": r.get("source"), "target": r.get("target")}
                for r in participations
            ],
            ensure_ascii=False,
        )
        for chunk in chunks:
            user_prompt = tmpl.get("user_prompt_template", "").format(
                chunk_text=(chunk.get("content", "") or "")[:4000],
                character_list_json=char_json,
                event_list_json=evt_json,
                participation_list_json=part_json,
            )
            try:
                raw = await ai_service.chat_completion(
                    provider=model_cfg["provider"],
                    model_url=model_cfg["model_url"],
                    api_key=model_cfg["api_key"],
                    model_name=model_cfg["model_name"],
                    system_prompt=tmpl.get("system_prompt", ""),
                    user_prompt=user_prompt,
                    temperature=float(tmpl.get("temperature") or 0.2),
                    max_tokens=int(tmpl.get("max_tokens") or 2000),
                    retries=2,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("completeness llm call failed: %s", exc)
                continue
            parsed = ai_service.parse_json_object(raw) or {}
            for k in ("missing_characters", "missing_events", "missing_participations"):
                items = parsed.get(k)
                if isinstance(items, list):
                    report[k].extend(items)
        return report

    # ---- P1: 关系二次确认 + 反馈重抽 --------------------------------

    async def confirm_low_confidence_relations(
        self,
        relations: List[Dict[str, Any]],
        entity_pool_json: str,
        evidence_by_chunk: Dict[str, str],
        model_cfg: Dict[str, Any],
        tmpl: Optional[Dict[str, Any]] = None,
        *,
        threshold: float = 0.7,
        max_confirm: int = 50,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """对 confidence < threshold 的边再问一次 LLM 做"是/否"确认.

        返回 (kept, dropped) 两个列表; dropped 含被 LLM 判否的边, 供 orchestrator
        决定是否写入 issues(便于溯源).
        """
        if not relations:
            return relations, []
        tmpl = tmpl or get_default_prompt("kg.validator.relation_confirm") or {}
        if not tmpl:
            # 没有 prompt 模板就直接放行
            return relations, []
        kept: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []
        confirmed_count = 0
        for r in relations:
            conf = r.get("confidence")
            if conf is None:
                kept.append(r)
                continue
            try:
                cf = float(conf)
            except (TypeError, ValueError):
                kept.append(r)
                continue
            if cf >= threshold or confirmed_count >= max_confirm:
                kept.append(r)
                continue
            confirmed_count += 1
            evidence = evidence_by_chunk.get(
                r.get("chunk_id", ""), r.get("evidence") or ""
            )[:400]
            user_prompt = tmpl.get("user_prompt_template", "").format(
                relation_json=json.dumps(
                    {
                        "source": r.get("source"),
                        "target": r.get("target"),
                        "relation": r.get("relation"),
                        "role": r.get("role"),
                        "action": r.get("action"),
                        "confidence": cf,
                    },
                    ensure_ascii=False,
                ),
                entity_pool_json=entity_pool_json,
                evidence=evidence,
            )
            try:
                raw = await ai_service.chat_completion(
                    provider=model_cfg["provider"],
                    model_url=model_cfg["model_url"],
                    api_key=model_cfg["api_key"],
                    model_name=model_cfg["model_name"],
                    system_prompt=tmpl.get("system_prompt", ""),
                    user_prompt=user_prompt,
                    temperature=float(tmpl.get("temperature") or 0.1),
                    max_tokens=int(tmpl.get("max_tokens") or 400),
                    retries=1,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("relation confirm llm call failed: %s", exc)
                kept.append(r)
                continue
            parsed = ai_service.parse_json_object(raw) or {}
            if bool(parsed.get("is_valid", True)):
                # 提升 confidence
                r = {**r, "confidence": max(cf, 0.75)}
                kept.append(r)
            else:
                r = {**r, "confidence": cf, "rejected": True}
                dropped.append(r)
        return kept, dropped

    async def feedback_re_extract(
        self,
        extractor: "ExtractorAgent",
        chunks: List[Dict[str, Any]],
        target_chunk_ids: List[str],
        phase: str,
        *,
        character_list_json: str = "[]",
        event_list_json: str = "[]",
    ) -> "PhaseOutput":
        """对 validator 报错涉及的 chunk 定点重跑某个 phase.

        重抽结果会带 confidence 标记 _feedback_pass=True, 便于 orchestrator
        合并时区分新旧结果.
        """
        target_set = {str(c) for c in target_chunk_ids}
        subset = [c for c in chunks if str(c.get("id", "")) in target_set]
        if not subset:
            return PhaseOutput(phase=phase)
        out = await extractor.run_phase(
            phase,
            subset,
            character_list_json=character_list_json,
            event_list_json=event_list_json,
        )
        for it in out.items:
            # 标记为反馈重抽产物
            it.data = {**(it.data or {}), "_feedback_pass": True}
        return out

    # ---- entry ----------------------------------------------------------

    async def validate(
        self,
        *,
        characters: List[Dict[str, Any]],
        events: List[Dict[str, Any]],
        participations: List[Dict[str, Any]],
        char_relations: List[Dict[str, Any]],
        event_relations: List[Dict[str, Any]],
        chunks: Optional[List[Dict[str, Any]]] = None,
        evidence_by_id: Optional[Dict[str, str]] = None,
        model_cfg: Optional[Dict[str, Any]] = None,
        prompts: Optional[Dict[str, Dict[str, Any]]] = None,
        run_llm_dedup: bool = True,
        run_llm_completeness: bool = False,
    ) -> ValidatedKG:
        """Run all checks and return a ``ValidatedKG`` plus issues.

        The orchestrator (kg_service) decides what to do with the issues:
        warn-and-accept, reject the run, or trigger a feedback re-extract.

        ``prompts`` is the DB-loaded dict from
        ``kg_service.resolve_prompts_async``. We look up the validator
        templates (kg.validator.dedup / kg.validator.completeness) from
        it so user edits in the settings UI flow through. When ``prompts``
        is None we fall back to the in-memory bundled defaults, which
        preserves the previous behaviour for callers that don't pass it.
        """
        chunks = chunks or []
        evidence_by_id = evidence_by_id or {}
        issues: List[ValidationIssue] = []

        chars, evts, norm_issues = self.normalize_entities(characters, events)
        issues.extend(norm_issues)

        issues.extend(
            self.validate_references(
                chars, evts, participations, char_relations, event_relations
            )
        )
        coverage, cov_issues = self.coverage_check(chars, evts, participations)
        issues.extend(cov_issues)

        # Resolve validator prompts once and reuse for dedup + completeness.
        # ``prompts`` is keyed by the raw prompt key (kg.*), unlike the
        # phase-keyed dict the extractor uses. We accept either shape to
        # stay backwards-compatible.
        async def _load_validator_tmpl(key: str) -> Optional[Dict[str, Any]]:
            try:
                return await get_active_prompt_by_key(key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DB prompt lookup failed for %s: %s", key, exc)
                return None

        def _pick_validator_tmpl(key: str) -> Optional[Dict[str, Any]]:
            if not prompts:
                return None
            # Direct key match first.
            if key in prompts:
                return prompts[key]
            # The extractor dict is phase-keyed ("character", "event", ...);
            # for validator prompts there's no phase mapping, so callers
            # should pass the raw key. Keep this lookup as a courtesy.
            return None

        dedup_tmpl = _pick_validator_tmpl("kg.validator.dedup")
        if dedup_tmpl is None and prompts is not None:
            # Phase-keyed dict: validator keys are absent. Best-effort
            # fall back to async DB read so customisation is honoured
            # even when the orchestrator passed phase-keyed prompts only.
            dedup_tmpl = await _load_validator_tmpl("kg.validator.dedup")

        completeness_tmpl = _pick_validator_tmpl("kg.validator.completeness")
        if completeness_tmpl is None and prompts is not None:
            completeness_tmpl = await _load_validator_tmpl(
                "kg.validator.completeness"
            )

        dedup_log: List[Dict[str, Any]] = []
        if run_llm_dedup and model_cfg is not None and len(chars) >= 2:
            try:
                chars, dedup_log = await self.llm_dedup(
                    chars, evidence_by_id, model_cfg, tmpl=dedup_tmpl
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("dedup skipped: %s", exc)

        coverage_report = dict(coverage)
        if run_llm_completeness and model_cfg is not None and chunks:
            try:
                coverage_report["completeness"] = await self.llm_completeness(
                    chars,
                    evts,
                    participations,
                    chunks,
                    model_cfg,
                    tmpl=completeness_tmpl,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("completeness skipped: %s", exc)

        return ValidatedKG(
            characters=chars,
            events=evts,
            participations=participations,
            char_relations=char_relations,
            event_relations=event_relations,
            issues=issues,
            dedup_log=dedup_log,
            coverage=coverage_report,
        )
