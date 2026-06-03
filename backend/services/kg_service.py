"""Knowledge graph extraction service.

Implements a chunked, multi-phase extraction pipeline that follows the
modeling baseline:

  * 人物 / 事件  均为独立实体
  * 内在属性 = 实体自身的标量特征 (存为节点字段)
  * 关系边连接实体, 不允许把跨实体属性塞进字段

The pipeline runs five prompts sequentially across the novel's chunks:

  Phase 1: extract character entities + their internal attributes
  Phase 2: extract event entities + their internal attributes
  Phase 3: extract character-event participation edges
  Phase 4: extract long-term character-character edges
  Phase 5: extract event-event edges (containment / causality)

Each phase consumes the global entity lists produced by the previous
phases so that the LLM can reference stable entity IDs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from database import (
    get_config_by_id,
    get_enabled_configs,
    get_knowledge_graph,
    replace_knowledge_graph,
)
from services import ai_service, file_service, prompt_service
from services.novel_service import get_novel_detail

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt lookups (delegated to prompt_service so the values can be
# customised from the settings UI and persisted in the database)
# ---------------------------------------------------------------------------

PROMPT_KEYS = {
    "character": "kg.character",
    "event": "kg.event",
    "participation": "kg.participation",
    "char_relation": "kg.char_relation",
    "event_relation": "kg.event_relation",
}


def _resolve_prompt(phase: str) -> Dict[str, Any]:
    """Return the active template for ``phase`` (or the bundled default)."""
    key = PROMPT_KEYS[phase]

    async def _load() -> Optional[Dict[str, Any]]:
        try:
            return await prompt_service.get_active_prompt_by_key(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to load prompt %s: %s", key, exc)
            return None

    # ``_resolve_prompt`` is called from a sync context inside build_*
    # helpers. We resolve via a per-event cache so multiple coroutines can
    # share the result without re-querying the DB.
    cached = _resolve_prompt.__dict__.setdefault("_cache", {})
    if key in cached:
        return cached[key]
    # The caller is in an event loop; fall back to the bundled default so the
    # extraction never blocks waiting on the database. The async loader is
    # still exposed through ``resolve_prompts_async`` for callers that
    # want to wait for DB-backed values.
    default = prompt_service.get_default_prompt(key)
    if default is None:
        default = {
            "system_prompt": "",
            "user_prompt_template": "",
            "temperature": 0.3,
            "max_tokens": 2400,
        }
    cached[key] = default
    return default


async def resolve_prompts_async() -> Dict[str, Dict[str, Any]]:
    """Resolve all KG prompt keys against the DB, with default fallback."""
    resolved: Dict[str, Dict[str, Any]] = {}
    for phase, key in PROMPT_KEYS.items():
        try:
            tmpl = await prompt_service.get_active_prompt_by_key(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("DB prompt lookup failed for %s: %s", key, exc)
            tmpl = None
        if not tmpl:
            tmpl = prompt_service.get_default_prompt(key) or {}
        resolved[phase] = tmpl
    return resolved


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def build_character_prompt(chunk_text: str) -> str:
    tmpl = _resolve_prompt("character").get("user_prompt_template", "")
    return tmpl.format(chunk_text=chunk_text)


def build_event_prompt(chunk_text: str, character_list_json: str) -> str:
    tmpl = _resolve_prompt("event").get("user_prompt_template", "")
    return tmpl.format(
        chunk_text=chunk_text, character_list_json=character_list_json
    )


def build_participation_prompt(
    chunk_text: str, character_list_json: str, event_list_json: str
) -> str:
    tmpl = _resolve_prompt("participation").get("user_prompt_template", "")
    return tmpl.format(
        chunk_text=chunk_text,
        character_list_json=character_list_json,
        event_list_json=event_list_json,
    )


def build_char_relation_prompt(chunk_text: str, character_list_json: str) -> str:
    tmpl = _resolve_prompt("char_relation").get("user_prompt_template", "")
    return tmpl.format(
        chunk_text=chunk_text, character_list_json=character_list_json
    )


def build_event_relation_prompt(chunk_text: str, event_list_json: str) -> str:
    tmpl = _resolve_prompt("event_relation").get("user_prompt_template", "")
    return tmpl.format(
        chunk_text=chunk_text, event_list_json=event_list_json
    )


# ---------------------------------------------------------------------------
# Robust JSON parsing (handles both array and object payloads)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)
_ARRAY_BLOCK_RE = re.compile(r"\[[\s\S]*\]")


def parse_json_value(raw: str) -> Any:
    """Parse a JSON object or array from a raw LLM response.

    Strips Markdown code fences, then tries a full parse; if that fails,
    falls back to extracting the first JSON object/array block.
    """
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = _FENCE_RE.sub("", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Object attempt
    obj = ai_service.parse_json_object(cleaned)
    if obj is not None:
        return obj

    # Array attempt
    match = _ARRAY_BLOCK_RE.search(cleaned)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _as_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        # Some prompts wrap arrays inside a key; try common keys.
        for key in ("characters", "events", "relations", "data", "items"):
            inner = value.get(key)
            if isinstance(inner, list):
                return [v for v in inner if isinstance(v, dict)]
    return []


# ---------------------------------------------------------------------------
# Per-phase payload cleaning
# ---------------------------------------------------------------------------

_TRIPLE_QUOTES = ('"""', "'''")


def _strip_text(value: str) -> str:
    cleaned = (value or "").strip()
    for q in _TRIPLE_QUOTES:
        if cleaned.startswith(q) and cleaned.endswith(q) and len(cleaned) >= 2 * len(q):
            cleaned = cleaned[len(q):-len(q)].strip()
    return cleaned


def _normalize_attr_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, list):
        items = [_strip_text(str(v)) for v in value if _strip_text(str(v))]
        return items
    if isinstance(value, str):
        # If a list-like value is encoded as a string, try splitting.
        text = _strip_text(value)
        if any(sep in text for sep in ("、", ",", "，", "/")):
            pieces = [_strip_text(p) for p in re.split(r"[、，,/\n]+", text)]
            pieces = [p for p in pieces if p]
            if len(pieces) > 1:
                return pieces
        return text
    return value


def _clean_attributes(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        k = _strip_text(str(key))
        if not k:
            continue
        v = _normalize_attr_value(value)
        if v in (None, "", [], {}):
            continue
        out[k] = v
    return out


def parse_character_payload(raw: str) -> List[Dict[str, Any]]:
    items = _as_list(parse_json_value(raw))
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        eid = _strip_text(str(item.get("id") or item.get("entity_id") or ""))
        name = _strip_text(str(item.get("name") or ""))
        if not name:
            continue
        if not eid:
            eid = f"char_{len(cleaned) + 1:03d}"
        else:
            eid = eid if eid.startswith("char_") else f"char_{eid}"
        cleaned.append(
            {
                "id": eid,
                "name": name,
                "attributes": _clean_attributes(item.get("attributes")),
            }
        )
    return cleaned


def parse_event_payload(raw: str) -> List[Dict[str, Any]]:
    items = _as_list(parse_json_value(raw))
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        eid = _strip_text(str(item.get("id") or item.get("entity_id") or ""))
        name = _strip_text(str(item.get("name") or ""))
        if not name:
            continue
        if not eid:
            eid = f"evt_{len(cleaned) + 1:03d}"
        else:
            eid = eid if eid.startswith("evt_") else f"evt_{eid}"
        attrs = _clean_attributes(item.get("attributes"))
        cleaned.append(
            {
                "id": eid,
                "name": name,
                "attributes": attrs,
            }
        )
    return cleaned


def parse_participation_payload(raw: str) -> List[Dict[str, Any]]:
    items = _as_list(parse_json_value(raw))
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        source = _strip_text(str(item.get("source") or ""))
        target = _strip_text(str(item.get("target") or ""))
        if not source or not target:
            continue
        properties = item.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        role = properties.get("角色") or properties.get("role")
        action = properties.get("具体行为") or properties.get("action")
        cleaned.append(
            {
                "source": source,
                "relation": _strip_text(str(item.get("relation") or "PARTICIPATES_IN"))
                or "PARTICIPATES_IN",
                "target": target,
                "role": _strip_text(str(role)) if role else None,
                "action": _strip_text(str(action)) if action else None,
            }
        )
    return cleaned


def parse_char_relation_payload(raw: str) -> List[Dict[str, Any]]:
    items = _as_list(parse_json_value(raw))
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        source = _strip_text(str(item.get("source") or ""))
        target = _strip_text(str(item.get("target") or ""))
        relation = _strip_text(str(item.get("relation") or ""))
        if not source or not target or not relation:
            continue
        properties = item.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        cleaned.append(
            {
                "source": source,
                "relation": relation,
                "target": target,
                "properties": properties,
            }
        )
    return cleaned


def parse_event_relation_payload(raw: str) -> List[Dict[str, Any]]:
    items = _as_list(parse_json_value(raw))
    cleaned: List[Dict[str, Any]] = []
    for item in items:
        source = _strip_text(str(item.get("source") or ""))
        target = _strip_text(str(item.get("target") or ""))
        relation = _strip_text(str(item.get("relation") or ""))
        if not source or not target or not relation:
            continue
        if relation not in ("包含", "导致"):
            relation = "关联"
        properties = item.get("properties")
        if not isinstance(properties, dict):
            properties = {}
        cleaned.append(
            {
                "source": source,
                "relation": relation,
                "target": target,
                "properties": properties,
            }
        )
    return cleaned


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

DEFAULT_CHUNK_SIZE = 8000
MAX_CONCURRENCY = 3


def _build_chapter_chunks(
    content: str, chapters: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    chunks: List[Dict[str, Any]] = []
    total = len(content)
    for c in chapters:
        start = max(0, int(c.get("start_position") or 0))
        end = min(total, int(c.get("end_position") or start))
        if end <= start:
            continue
        text = content[start:end].strip()
        if not text:
            continue
        chunks.append(
            {
                "id": f"chapter_{c.get('chapter_number', len(chunks) + 1)}",
                "title": c.get("title") or f"第 {c.get('chapter_number', '?')} 章",
                "chapter_number": c.get("chapter_number"),
                "content": text,
            }
        )
    return chunks


def _build_fallback_chunks(
    content: str, chunk_size: int
) -> List[Dict[str, Any]]:
    text = (content or "").strip()
    if not text:
        return []
    from services.novel_service import smart_chunk_content

    raw_chunks = smart_chunk_content(text, chunk_size)
    chunks: List[Dict[str, Any]] = []
    for idx, c in enumerate(raw_chunks, start=1):
        body = (c.get("content") or "").strip()
        if not body:
            continue
        chunks.append(
            {
                "id": f"chunk_{idx:03d}",
                "title": c.get("title") or f"片段 {idx}",
                "chapter_number": None,
                "content": body,
            }
        )
    return chunks


def chunk_novel(
    content: str,
    chapters: Sequence[Dict[str, Any]],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> List[Dict[str, Any]]:
    chapters = chapters or []
    chunks = _build_chapter_chunks(content, chapters)
    if chunks:
        return chunks
    return _build_fallback_chunks(content, chunk_size)


# ---------------------------------------------------------------------------
# Aggregation / entity alignment
# ---------------------------------------------------------------------------

_ALIAS_ATTR_KEYS = ("别名", "alias", "aliases", "字号")


def _alias_keys(attributes: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    for k in _ALIAS_ATTR_KEYS:
        if k in attributes:
            v = attributes[k]
            if isinstance(v, list):
                keys.extend(_strip_text(str(x)) for x in v if _strip_text(str(x)))
            elif isinstance(v, str) and v.strip():
                keys.append(v.strip())
    return keys


def _merge_attr_dict(
    base: Dict[str, Any], extra: Dict[str, Any]
) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in (extra or {}).items():
        if value in (None, "", [], {}):
            continue
        existing = merged.get(key)
        if existing is None:
            merged[key] = value
        elif isinstance(existing, list) and isinstance(value, list):
            seen = {_strip_text(str(x)).lower() for x in existing if _strip_text(str(x))}
            for v in value:
                vs = _strip_text(str(v))
                if vs and vs.lower() not in seen:
                    existing.append(vs)
                    seen.add(vs.lower())
        elif isinstance(existing, list):
            if isinstance(value, str):
                vs = _strip_text(value)
                if vs and vs.lower() not in {str(x).lower() for x in existing}:
                    existing.append(vs)
        elif isinstance(value, list):
            merged[key] = [_strip_text(str(x)) for x in value if _strip_text(str(x))]
        else:
            # Keep longer / non-empty string.
            if isinstance(value, str) and isinstance(existing, str):
                if len(value.strip()) > len(existing.strip()):
                    merged[key] = value
            else:
                merged[key] = value
    return merged


def merge_characters(chunk_results: Sequence[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Merge character lists across chunks.

    Strategy:
      1. Trust LLM-generated `id` (e.g. char_001) as primary key.
      2. Fall back to `name` for entities without a recognized id prefix.
      3. Merge attributes by union, de-duplicating list values.
    """
    by_id: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, str] = {}  # normalized name -> entity_id
    by_alias: Dict[str, str] = {}  # alias -> entity_id

    for chunk in chunk_results:
        for c in chunk:
            eid = _strip_text(str(c.get("id") or ""))
            name = _strip_text(str(c.get("name") or ""))
            if not name:
                continue
            if not eid or not eid.startswith("char_"):
                eid = f"char_{len(by_id) + 1:03d}"

            existing_id = by_name.get(name.lower()) or by_alias.get(name.lower())
            if existing_id and existing_id in by_id and existing_id != eid:
                target = by_id[existing_id]
                target["attributes"] = _merge_attr_dict(
                    target.get("attributes") or {}, c.get("attributes") or {}
                )
                eid = target["id"]
            else:
                target = by_id.get(eid)
                if target is None:
                    target = {
                        "id": eid,
                        "name": name,
                        "attributes": c.get("attributes") or {},
                    }
                    by_id[eid] = target
                else:
                    target["attributes"] = _merge_attr_dict(
                        target["attributes"], c.get("attributes") or {}
                    )

            # Index name and aliases for future lookups.
            by_name.setdefault(name.lower(), eid)
            for alias in _alias_keys(target["attributes"]):
                by_alias.setdefault(alias.lower(), eid)

    # Renumber sequentially to make IDs stable/dense.
    sorted_chars = sorted(by_id.values(), key=lambda x: x["name"])
    for idx, c in enumerate(sorted_chars, start=1):
        c["id"] = f"char_{idx:03d}"
    return sorted_chars


def merge_events(chunk_results: Sequence[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    by_name: Dict[str, str] = {}

    for chunk in chunk_results:
        for e in chunk:
            eid = _strip_text(str(e.get("id") or ""))
            name = _strip_text(str(e.get("name") or ""))
            if not name:
                continue
            if not eid or not eid.startswith("evt_"):
                eid = f"evt_{len(by_id) + 1:03d}"

            existing_id = by_name.get(name.lower())
            if existing_id and existing_id in by_id and existing_id != eid:
                target = by_id[existing_id]
                target["attributes"] = _merge_attr_dict(
                    target.get("attributes") or {}, e.get("attributes") or {}
                )
            else:
                target = by_id.get(eid)
                if target is None:
                    target = {
                        "id": eid,
                        "name": name,
                        "attributes": e.get("attributes") or {},
                    }
                    by_id[eid] = target
                else:
                    target["attributes"] = _merge_attr_dict(
                        target["attributes"], e.get("attributes") or {}
                    )
            by_name.setdefault(name.lower(), target["id"])

    sorted_events = sorted(by_id.values(), key=lambda x: x["name"])
    for idx, e in enumerate(sorted_events, start=1):
        e["id"] = f"evt_{idx:03d}"
    return sorted_events


def _normalize_rel_key(
    source: str, relation: str, target: str
) -> Tuple[str, str, str]:
    return (
        _strip_text(source).lower(),
        _strip_text(relation).lower(),
        _strip_text(target).lower(),
    )


def merge_relations(
    chunk_results: Sequence[List[Dict[str, Any]]],
    *,
    valid_sources: Optional[set] = None,
    valid_targets: Optional[set] = None,
) -> List[Dict[str, Any]]:
    seen: set = set()
    merged: List[Dict[str, Any]] = []
    for chunk in chunk_results:
        for r in chunk:
            source = _strip_text(str(r.get("source") or ""))
            target = _strip_text(str(r.get("target") or ""))
            relation = _strip_text(str(r.get("relation") or ""))
            if not source or not target or not relation:
                continue
            if valid_sources is not None and source not in valid_sources:
                continue
            if valid_targets is not None and target not in valid_targets:
                continue
            key = _normalize_rel_key(source, relation, target)
            if key in seen:
                continue
            seen.add(key)
            entry = {
                "source": source,
                "relation": relation,
                "target": target,
            }
            if "role" in r or "action" in r:
                entry["role"] = r.get("role")
                entry["action"] = r.get("action")
            merged.append(entry)
    return merged


# ---------------------------------------------------------------------------
# Phase execution
# ---------------------------------------------------------------------------

Parser = Callable[[str], List[Dict[str, Any]]]


async def _run_phase(
    model_cfg: Dict[str, Any],
    chunks: List[Dict[str, Any]],
    *,
    system_prompt: str,
    prompt_builder: Callable[[Dict[str, Any]], str],
    parser: Parser,
    label: str,
    temperature: float = 0.3,
    max_tokens: int = 2400,
    concurrency: int = MAX_CONCURRENCY,
    on_chunk_done: Optional[Callable[[int, int, List[Dict[str, Any]]], None]] = None,
) -> List[List[Dict[str, Any]]]:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    total = len(chunks)
    done = 0

    async def process_one(chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        nonlocal done
        async with semaphore:
            user_prompt = prompt_builder(chunk)
            try:
                raw = await ai_service.chat_completion(
                    provider=model_cfg["provider"],
                    model_url=model_cfg["model_url"],
                    api_key=model_cfg["api_key"],
                    model_name=model_cfg["model_name"],
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "%s: chunk %s failed (%s)", label, chunk.get("id"), exc
                )
                result: List[Dict[str, Any]] = []
            else:
                try:
                    result = parser(raw)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "%s: chunk %s parse failed (%s): %s",
                        label,
                        chunk.get("id"),
                        exc,
                        (raw or "")[:120],
                    )
                    result = []
            done += 1
            if on_chunk_done is not None:
                try:
                    on_chunk_done(done, total, result)
                except Exception:  # noqa: BLE001
                    logger.exception("on_chunk_done callback raised")
            return result

    tasks = [process_one(c) for c in chunks]
    return await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


async def _resolve_model_config(
    model_config_id: Optional[int],
) -> Dict[str, Any]:
    if model_config_id:
        cfg = await get_config_by_id(model_config_id)
        if not cfg:
            raise ValueError("指定的模型配置不存在")
        return cfg
    enabled = await get_enabled_configs()
    if not enabled:
        raise ValueError("未找到可用的模型，请先在系统设置中启用至少一个模型")
    return enabled[0]


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


async def extract_knowledge_graph(
    novel_id: int,
    *,
    model_config_id: Optional[int] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_concurrency: int = MAX_CONCURRENCY,
) -> Dict[str, Any]:
    novel = await get_novel_detail(novel_id)
    if not novel:
        raise ValueError("小说不存在")
    file_path = novel.get("file_path")
    if not file_path:
        raise ValueError("文件路径缺失")

    content = await file_service.read_text_file(file_path)
    if not (content or "").strip():
        raise ValueError("小说内容为空")

    model_cfg = await _resolve_model_config(model_config_id)
    concurrency = max(1, max_concurrency)
    prompts = await resolve_prompts_async()

    chunks = chunk_novel(content, novel.get("chapters") or [], chunk_size)
    if not chunks:
        raise ValueError("无法切分文本，请先解析章节或调整分块大小")

    char_tmpl = prompts["character"]
    event_tmpl = prompts["event"]
    participation_tmpl = prompts["participation"]
    char_rel_tmpl = prompts["char_relation"]
    event_rel_tmpl = prompts["event_relation"]

    # Phase 1: characters
    char_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=char_tmpl.get("system_prompt", ""),
        prompt_builder=build_character_prompt,
        parser=parse_character_payload,
        label="character",
        temperature=float(char_tmpl.get("temperature") or 0.3),
        max_tokens=int(char_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
    )
    global_characters = merge_characters(char_results)
    logger.info("Phase 1 done: %d characters", len(global_characters))

    character_list_json = json.dumps(
        [
            {"id": c["id"], "name": c["name"]}
            for c in global_characters
        ],
        ensure_ascii=False,
    )

    # Phase 2: events
    event_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=event_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_event_prompt(c["content"], character_list_json),
        parser=parse_event_payload,
        label="event",
        temperature=float(event_tmpl.get("temperature") or 0.3),
        max_tokens=int(event_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
    )
    global_events = merge_events(event_results)
    logger.info("Phase 2 done: %d events", len(global_events))

    event_list_json = json.dumps(
        [
            {"id": e["id"], "name": e["name"]}
            for e in global_events
        ],
        ensure_ascii=False,
    )

    char_ids = {c["id"] for c in global_characters}
    event_ids = {e["id"] for e in global_events}

    # Phase 3: character-event participations
    participation_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=participation_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_participation_prompt(
            c["content"], character_list_json, event_list_json
        ),
        parser=parse_participation_payload,
        label="participation",
        temperature=float(participation_tmpl.get("temperature") or 0.3),
        max_tokens=int(participation_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
    )
    global_participations = merge_relations(
        participation_results,
        valid_sources=char_ids,
        valid_targets=event_ids,
    )
    logger.info(
        "Phase 3 done: %d participations", len(global_participations)
    )

    # Phase 4: character-character relations
    char_rel_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=char_rel_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_char_relation_prompt(c["content"], character_list_json),
        parser=parse_char_relation_payload,
        label="char_relation",
        temperature=float(char_rel_tmpl.get("temperature") or 0.3),
        max_tokens=int(char_rel_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
    )
    global_char_rels = merge_relations(
        char_rel_results,
        valid_sources=char_ids,
        valid_targets=char_ids,
    )
    logger.info(
        "Phase 4 done: %d character relations", len(global_char_rels)
    )

    # Phase 5: event-event relations
    event_rel_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=event_rel_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_event_relation_prompt(c["content"], event_list_json),
        parser=parse_event_relation_payload,
        label="event_relation",
        temperature=float(event_rel_tmpl.get("temperature") or 0.3),
        max_tokens=int(event_rel_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
    )
    global_event_rels = merge_relations(
        event_rel_results,
        valid_sources=event_ids,
        valid_targets=event_ids,
    )
    logger.info(
        "Phase 5 done: %d event relations", len(global_event_rels)
    )

    stored = await replace_knowledge_graph(
        novel_id,
        characters=global_characters,
        events=global_events,
        character_event_relations=global_participations,
        character_relations=global_char_rels,
        event_relations=global_event_rels,
        model_id=model_cfg.get("id"),
    )

    return {
        "model": model_cfg.get("name") or model_cfg.get("model_name"),
        "chunks_processed": len(chunks),
        "characters": stored["characters"],
        "events": stored["events"],
        "character_event_relations": stored["character_event_relations"],
        "character_relations": stored["character_relations"],
        "event_relations": stored["event_relations"],
        "stats": {
            "characters": len(stored["characters"]),
            "events": len(stored["events"]),
            "participations": len(stored["character_event_relations"]),
            "character_relations": len(stored["character_relations"]),
            "event_relations": len(stored["event_relations"]),
            "chunks_processed": len(chunks),
        },
    }


async def list_knowledge_graph(novel_id: int) -> Dict[str, Any]:
    return await get_knowledge_graph(novel_id)


# ---------------------------------------------------------------------------
# Streaming extraction (with per-phase / per-chunk progress callbacks)
# ---------------------------------------------------------------------------


PHASE_LABELS = {
    "characters": "抽取人物实体",
    "events": "抽取事件实体",
    "participations": "识别人物-事件关系",
    "char_relations": "识别人物间关系",
    "event_relations": "识别事件间关系",
}

PHASE_WEIGHTS = {
    "characters": 0.30,
    "events": 0.25,
    "participations": 0.20,
    "char_relations": 0.15,
    "event_relations": 0.10,
}


async def extract_knowledge_graph_streaming(
    novel_id: int,
    *,
    model_config_id: Optional[int] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    max_concurrency: int = MAX_CONCURRENCY,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    on_partial: Optional[
        Callable[[str, List[Dict[str, Any]]], None]
    ] = None,
) -> Dict[str, Any]:
    """Run the full extraction pipeline and emit progress / partial results.

    `on_progress` is called with a payload dict describing the current state
    (event type, message, percent, counters). `on_partial` is called once
    per phase with the freshly merged entities/relations for that phase so
    the caller can stream them out to the UI.
    """
    if on_progress is None:
        on_progress = lambda _p: None  # noqa: E731
    if on_partial is None:
        on_partial = lambda _k, _v: None  # noqa: E731

    novel = await get_novel_detail(novel_id)
    if not novel:
        raise ValueError("小说不存在")
    file_path = novel.get("file_path")
    if not file_path:
        raise ValueError("文件路径缺失")

    on_progress({
        "event": "start",
        "message": "开始加载小说内容",
        "percent": 0,
    })

    content = await file_service.read_text_file(file_path)
    if not (content or "").strip():
        raise ValueError("小说内容为空")

    model_cfg = await _resolve_model_config(model_config_id)
    concurrency = max(1, max_concurrency)
    prompts = await resolve_prompts_async()
    char_tmpl = prompts["character"]
    event_tmpl = prompts["event"]
    participation_tmpl = prompts["participation"]
    char_rel_tmpl = prompts["char_relation"]
    event_rel_tmpl = prompts["event_relation"]

    chunks = chunk_novel(content, novel.get("chapters") or [], chunk_size)
    if not chunks:
        raise ValueError("无法切分文本，请先解析章节或调整分块大小")

    on_progress({
        "event": "ready",
        "message": f"共切分为 {len(chunks)} 个片段",
        "percent": 2,
        "chunks": len(chunks),
        "model": model_cfg.get("name") or model_cfg.get("model_name"),
    })

    accumulated = 0.0
    phase_progress: Dict[str, float] = {}

    def _make_chunker(phase_key: str) -> Callable[[int, int, List[Dict[str, Any]]], None]:
        weight = PHASE_WEIGHTS.get(phase_key, 0.10)

        def _cb(done: int, total: int, partial: List[Dict[str, Any]]) -> None:
            pct_in_phase = (done / total) if total else 1.0
            local = pct_in_phase * weight * 100
            phase_progress[phase_key] = local
            total_pct = min(
                99.0,
                2.0 + sum(phase_progress.values()),
            )
            on_progress({
                "event": "phase_progress",
                "phase": phase_key,
                "phase_label": PHASE_LABELS.get(phase_key, phase_key),
                "done": done,
                "total": total,
                "percent": round(total_pct, 1),
                "partial_count": len(partial),
                "message": (
                    f"{PHASE_LABELS.get(phase_key, phase_key)}: "
                    f"{done}/{total} 片段完成"
                ),
            })
            on_partial(phase_key, partial)

        return _cb

    # Phase 1: characters
    char_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=char_tmpl.get("system_prompt", ""),
        prompt_builder=build_character_prompt,
        parser=parse_character_payload,
        label="character",
        temperature=float(char_tmpl.get("temperature") or 0.3),
        max_tokens=int(char_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
        on_chunk_done=_make_chunker("characters"),
    )
    global_characters = merge_characters(char_results)
    accumulated += PHASE_WEIGHTS["characters"] * 100
    on_progress({
        "event": "phase_done",
        "phase": "characters",
        "phase_label": PHASE_LABELS["characters"],
        "count": len(global_characters),
        "percent": round(2.0 + accumulated, 1),
        "message": f"人物抽取完成，共 {len(global_characters)} 位",
    })
    on_partial("characters", global_characters)

    character_list_json = json.dumps(
        [{"id": c["id"], "name": c["name"]} for c in global_characters],
        ensure_ascii=False,
    )

    # Phase 2: events
    event_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=event_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_event_prompt(c["content"], character_list_json),
        parser=parse_event_payload,
        label="event",
        temperature=float(event_tmpl.get("temperature") or 0.3),
        max_tokens=int(event_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
        on_chunk_done=_make_chunker("events"),
    )
    global_events = merge_events(event_results)
    accumulated += PHASE_WEIGHTS["events"] * 100
    on_progress({
        "event": "phase_done",
        "phase": "events",
        "phase_label": PHASE_LABELS["events"],
        "count": len(global_events),
        "percent": round(2.0 + accumulated, 1),
        "message": f"事件抽取完成，共 {len(global_events)} 个",
    })
    on_partial("events", global_events)

    event_list_json = json.dumps(
        [{"id": e["id"], "name": e["name"]} for e in global_events],
        ensure_ascii=False,
    )

    char_ids = {c["id"] for c in global_characters}
    event_ids = {e["id"] for e in global_events}

    # Phase 3: participations
    participation_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=participation_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_participation_prompt(
            c["content"], character_list_json, event_list_json
        ),
        parser=parse_participation_payload,
        label="participation",
        temperature=float(participation_tmpl.get("temperature") or 0.3),
        max_tokens=int(participation_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
        on_chunk_done=_make_chunker("participations"),
    )
    global_participations = merge_relations(
        participation_results,
        valid_sources=char_ids,
        valid_targets=event_ids,
    )
    accumulated += PHASE_WEIGHTS["participations"] * 100
    on_progress({
        "event": "phase_done",
        "phase": "participations",
        "phase_label": PHASE_LABELS["participations"],
        "count": len(global_participations),
        "percent": round(2.0 + accumulated, 1),
        "message": f"人物-事件关系完成，共 {len(global_participations)} 条",
    })
    on_partial("participations", global_participations)

    # Phase 4: character-character relations
    char_rel_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=char_rel_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_char_relation_prompt(c["content"], character_list_json),
        parser=parse_char_relation_payload,
        label="char_relation",
        temperature=float(char_rel_tmpl.get("temperature") or 0.3),
        max_tokens=int(char_rel_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
        on_chunk_done=_make_chunker("char_relations"),
    )
    global_char_rels = merge_relations(
        char_rel_results,
        valid_sources=char_ids,
        valid_targets=char_ids,
    )
    accumulated += PHASE_WEIGHTS["char_relations"] * 100
    on_progress({
        "event": "phase_done",
        "phase": "char_relations",
        "phase_label": PHASE_LABELS["char_relations"],
        "count": len(global_char_rels),
        "percent": round(2.0 + accumulated, 1),
        "message": f"人物间关系完成，共 {len(global_char_rels)} 条",
    })
    on_partial("char_relations", global_char_rels)

    # Phase 5: event-event relations
    event_rel_results = await _run_phase(
        model_cfg,
        chunks,
        system_prompt=event_rel_tmpl.get("system_prompt", ""),
        prompt_builder=lambda c: build_event_relation_prompt(c["content"], event_list_json),
        parser=parse_event_relation_payload,
        label="event_relation",
        temperature=float(event_rel_tmpl.get("temperature") or 0.3),
        max_tokens=int(event_rel_tmpl.get("max_tokens") or 2400),
        concurrency=concurrency,
        on_chunk_done=_make_chunker("event_relations"),
    )
    global_event_rels = merge_relations(
        event_rel_results,
        valid_sources=event_ids,
        valid_targets=event_ids,
    )
    accumulated += PHASE_WEIGHTS["event_relations"] * 100
    on_progress({
        "event": "phase_done",
        "phase": "event_relations",
        "phase_label": PHASE_LABELS["event_relations"],
        "count": len(global_event_rels),
        "percent": round(2.0 + accumulated, 1),
        "message": f"事件间关系完成，共 {len(global_event_rels)} 条",
    })
    on_partial("event_relations", global_event_rels)

    stored = await replace_knowledge_graph(
        novel_id,
        characters=global_characters,
        events=global_events,
        character_event_relations=global_participations,
        character_relations=global_char_rels,
        event_relations=global_event_rels,
        model_id=model_cfg.get("id"),
    )

    return {
        "model": model_cfg.get("name") or model_cfg.get("model_name"),
        "chunks_processed": len(chunks),
        "characters": stored["characters"],
        "events": stored["events"],
        "character_event_relations": stored["character_event_relations"],
        "character_relations": stored["character_relations"],
        "event_relations": stored["event_relations"],
        "stats": {
            "characters": len(stored["characters"]),
            "events": len(stored["events"]),
            "participations": len(stored["character_event_relations"]),
            "character_relations": len(stored["character_relations"]),
            "event_relations": len(stored["event_relations"]),
            "chunks_processed": len(chunks),
        },
    }
