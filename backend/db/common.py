from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

def _safe_remove(path: Optional[str]) -> None:
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError as exc:
        logger.warning("Failed to remove file %s: %s", path, exc)


def _decode_attributes(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _encode_attributes(value: Any) -> str:
    if not value:
        return ""
    return json.dumps(value, ensure_ascii=False)


def _encode_extras(value: Any) -> str:
    """extras 列的 JSON 编码, 与 _encode_attributes 一致但语义独立, 便于将来拆分."""
    if not value:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _decode_extras(raw: Any) -> Dict[str, Any]:
    """extras 列的 JSON 解码, 兼容旧库 (无该列 / 字段为空) 情况."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _build_entity_extras(obj: Dict[str, Any]) -> Dict[str, Any]:
    """从 LLM 抽出的实体 dict 抽取 evidence / confidence / chunk_id.

    支持:
    * obj["extras"] 已经是 dict (优先)
    * obj["evidence"] 是 str 或 List[dict] (EvidenceSpan 列表)
    * obj["confidence"] 是数字
    * obj["chunk_id"] 字符串
    """
    extras: Dict[str, Any] = {}
    if "extras" in obj and isinstance(obj["extras"], dict):
        extras.update(obj["extras"])
    ev = obj.get("evidence")
    if ev:
        if isinstance(ev, str):
            extras["evidence"] = [{
                "quote": ev, "chunk_id": obj.get("chunk_id", ""),
                "start": None, "end": None, "strategy": "fallback",
            }]
        elif isinstance(ev, list):
            extras["evidence"] = ev
    if "confidence" in obj:
        extras["confidence"] = obj.get("confidence")
    if obj.get("chunk_id"):
        extras.setdefault("chunk_id", obj["chunk_id"])
    return extras


def _build_relation_extras(obj: Dict[str, Any]) -> Dict[str, Any]:
    """关系类的 extras 构造: 同上, 但 evidence 既可来自单条 span,
    也可来自两个端点的 span 合并(由 orchestrator 负责)."""
    return _build_entity_extras(obj)


# RAG-lite 改进: 别名 + description 的归一化与合并工具
_ALIAS_ATTR_KEYS = ("别名", "alias", "aliases", "字号", "绰号")


def _extract_aliases_from_obj(obj: Dict[str, Any]) -> List[str]:
    """从 LLM 抽出的实体 dict 抽 aliases: 顶层 aliases + attributes.别名/字号 等."""
    out: List[str] = []
    top = obj.get("aliases")
    if isinstance(top, list):
        for x in top:
            v = str(x or "").strip()
            if v:
                out.append(v)
    elif isinstance(top, str) and top.strip():
        out.append(top.strip())
    attrs = obj.get("attributes") or {}
    if isinstance(attrs, dict):
        for k in _ALIAS_ATTR_KEYS:
            v = attrs.get(k)
            if isinstance(v, list):
                for x in v:
                    s = str(x or "").strip()
                    if s:
                        out.append(s)
            elif isinstance(v, str) and v.strip():
                out.append(v.strip())
    # 去重 + 排除空 + 限制长度
    seen: Set[str] = set()
    deduped: List[str] = []
    for a in out:
        if 1 <= len(a) <= 30 and a not in seen:
            deduped.append(a)
            seen.add(a)
    return deduped[:10]  # 最多 10 个


def _merge_aliases(old: List[str], new: List[str]) -> List[str]:
    """合并新旧 aliases, 保留前 10 个. old 优先 (历史称呼不应被覆盖)."""
    seen: Set[str] = set()
    merged: List[str] = []
    for src in (old, new):
        for a in src:
            if a and a not in seen:
                merged.append(a)
                seen.add(a)
    return merged[:10]


def _aliases_from_db(raw: Optional[str]) -> List[str]:
    """从 DB 读出的 aliases 字符串解析回 list[str]. 兼容 legacy (空 / 非 JSON)."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _aliases_to_db(aliases: List[str]) -> str:
    """将 list[str] 序列化为 DB JSON 字符串."""
    return json.dumps(aliases, ensure_ascii=False)
