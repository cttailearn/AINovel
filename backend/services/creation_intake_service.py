"""AI 小说创作 — 新建项目引导式问答 (Intake wizard) 服务.

两条核心流程:
* ``generate_next_question``: 根据用户前面的回答, 让 LLM 动态生成下一道题 + 4~8 个
  差异化选项. LLM 不可用时退化为基于历史的本地启发式题目.
* ``synthesize_project``: 把完整的问答历史交给 LLM, 综合为可一键建项的项目草稿.
  LLM 不可用 / 输出非 JSON 时, 退化为本地拼装.

两条路径都共享: 模型解析 / 提示词加载 / JSON 解析 / 本地兜底.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from schemas import (
    AiIntakeHistoryItem,
    AiIntakeNextRequest,
    AiIntakeNextResponse,
    AiIntakeSynthesizeRequest,
    AiIntakeSynthesizeResponse,
)
from services import ai_service, prompt_service

logger = logging.getLogger(__name__)


SYNTH_PROMPT_KEY = "creation.intake.synthesize"
NEXT_PROMPT_KEY = "creation.intake.next_question"

# 上限, 防止 AI 无限出题
MAX_DYNAMIC_STEPS = 8
# 推荐总步数 (用于在 NEXT prompt 中提示 LLM)
RECOMMENDED_TOTAL_STEPS = (4, 7)


class IntakeError(RuntimeError):
    """Intake wizard 不可恢复的致命错误 (例如无可用模型且兜底失败)."""


# ---------------------------------------------------------------------------
# 模型解析 (与 creation_service._resolve_model_cfg 行为一致)
# ---------------------------------------------------------------------------


async def _resolve_model_cfg(model_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """修复 #8: 转调 ai_service.resolve_chat_model 公共实现, 与
    creation_service 行为一致.
    """
    from services import ai_service

    return await ai_service.resolve_chat_model(model_id)


# ---------------------------------------------------------------------------
# 提示词加载
# ---------------------------------------------------------------------------


def _resolve_prompt(key: str) -> Dict[str, Any]:
    try:
        default = prompt_service.get_default_prompt(key) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to read default intake prompt %s: %s", key, exc)
        default = {}
    return default or {}


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return ""


def _format_user_prompt(tmpl: str, vars_: Dict[str, str]) -> str:
    if not tmpl or "{" not in tmpl:
        return tmpl
    try:
        return tmpl.format_map(_SafeDict(vars_))
    except Exception as exc:  # noqa: BLE001
        logger.warning("intake prompt format failed: %s", exc)
        return tmpl


# ---------------------------------------------------------------------------
# 历史 → 文本块 (喂给 LLM)
# ---------------------------------------------------------------------------


def _stringify_choice(value: Any) -> str:
    if value is None or value == "":
        return "(跳过)"
    if isinstance(value, list):
        return " / ".join(str(v) for v in value) if value else "(跳过)"
    return str(value)


def _build_history_block(items: List[AiIntakeHistoryItem]) -> str:
    """把问答历史拼成 LLM 友好的 Markdown 文本块."""
    if not items:
        return "(无 — 这是第一个问题)"
    lines: List[str] = []
    for i, it in enumerate(items, start=1):
        opts = "、".join(it.options) if it.options else "(无候选)"
        choice = _stringify_choice(it.choice)
        extra = (it.custom_text or "").strip()
        seed_mark = " [种子题]" if it.is_seed else ""
        lines.append(f"### 第 {i} 步{seed_mark}")
        lines.append(f"问题: {it.question}")
        lines.append(f"候选: {opts}")
        if extra:
            lines.append(f"用户选择: {choice}  ·  补充: {extra}")
        else:
            lines.append(f"用户选择: {choice}")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# JSON 解析 (容错: 支持 ```json 围栏 / 抓最外层 { })
# ---------------------------------------------------------------------------


_JSON_OBJ_RE = re.compile(r"\{[\s\S]*\}")


def _try_parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    # 1) 整段就是 JSON
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    # 2) 抓最外层 {...}
    m = _JSON_OBJ_RE.search(cleaned)
    if m:
        try:
            obj = json.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            return None
    return None


# ---------------------------------------------------------------------------
# 通用 LLM 调用
# ---------------------------------------------------------------------------


async def _call_llm_for(
    *,
    model_cfg: Dict[str, Any],
    prompt_key: str,
    vars_: Dict[str, str],
    fallback_user_prompt: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> str:
    tmpl = _resolve_prompt(prompt_key)
    system_prompt = (tmpl.get("system_prompt") or "").strip()
    raw_user_tmpl = tmpl.get("user_prompt_template") or fallback_user_prompt
    user_prompt = _format_user_prompt(raw_user_tmpl, vars_) or _format_user_prompt(
        fallback_user_prompt, vars_
    )
    # 调用方覆盖 > prompt 模板默认
    if temperature is None:
        try:
            temperature = float(tmpl.get("temperature") or 0.6)
        except (TypeError, ValueError):
            temperature = 0.6
    if max_tokens is None:
        try:
            max_tokens = int(tmpl.get("max_tokens") or 1500)
        except (TypeError, ValueError):
            max_tokens = 1500

    return await ai_service.chat_completion(
        provider=model_cfg["provider"],
        model_url=model_cfg["model_url"],
        api_key=model_cfg["api_key"],
        model_name=model_cfg["model_name"],
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        retries=1,
    )


# ---------------------------------------------------------------------------
# 答案归一化
# ---------------------------------------------------------------------------


def _coerce_options(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    seen = set()
    for v in raw:
        s = str(v).strip() if v is not None else ""
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


# ---------------------------------------------------------------------------
# 本地兜底 — 下一题
# ---------------------------------------------------------------------------


# 兜底题库. 每条: (key, question, description, options, multiple, allow_custom)
# 这些题目在 LLM 完全不可用时按顺序出, 保证流程不会卡住.
_FALLBACK_QUESTIONS: List[Dict[str, Any]] = [
    {
        "key": "genre",
        "question": "你想写什么类型的故事?",
        "description": "可多选; AI 会综合成复合类型标签, 例如 「玄幻/修仙」",
        "options": [
            "玄幻", "都市", "悬疑", "科幻", "历史",
            "武侠", "言情", "军事", "游戏", "末世", "由 AI 决定",
        ],
        "multiple": True,
        "allow_custom": True,
    },
    {
        "key": "era",
        "question": "故事发生在什么时代 / 世界?",
        "description": "决定世界观与力量体系基调",
        "options": [
            "古代东方", "古代西方", "架空异世界", "民国乱世",
            "现代都市", "近未来", "未来科幻", "末日废土", "由 AI 决定",
        ],
        "multiple": False,
        "allow_custom": True,
    },
    {
        "key": "protagonist",
        "question": "你心中的主角更接近哪一类?",
        "description": "",
        "options": [
            "少年英雄", "失意复仇者", "隐世高手", "普通人逆袭",
            "冷面杀手", "天才型主角", "反派视角主角", "由 AI 决定",
        ],
        "multiple": False,
        "allow_custom": True,
    },
    {
        "key": "tone",
        "question": "你希望的整体故事基调?",
        "description": "可多选",
        "options": [
            "热血", "轻松", "严肃", "黑暗", "浪漫",
            "悬疑", "幽默", "文艺", "史诗", "由 AI 决定",
        ],
        "multiple": True,
        "allow_custom": True,
    },
    {
        "key": "pov",
        "question": "叙述视角?",
        "description": "",
        "options": [
            "第一人称", "第三人称", "全知视角", "多视角切换", "由 AI 决定",
        ],
        "multiple": False,
        "allow_custom": True,
    },
    {
        "key": "length",
        "question": "大致的目标篇幅?",
        "description": "影响总章节数与每章信息密度",
        "options": [
            "短篇 (1~3 章)", "中短篇 (4~10 章)",
            "中长篇 (10~30 章)", "长篇 (30+ 章)", "由 AI 决定",
        ],
        "multiple": False,
        "allow_custom": True,
    },
    {
        "key": "free",
        "question": "还想补充什么?",
        "description": "可写主角名字 / 关键情节 / 任何灵感, AI 会融入草稿. 不写也行.",
        "options": [],
        "multiple": False,
        "allow_custom": True,
    },
]


def _local_next_question(
    items: List[AiIntakeHistoryItem], model_name: Optional[str]
) -> AiIntakeNextResponse:
    """当 LLM 不可用时, 从兜底题库按顺序出题.

    去重策略: 比较题目文本, 避免重复出题. AI 动态生成的题因题目文本不命中
    兜底题库, 自然不会与兜底题库冲突, 但会被识别为「已经答过种子题」后的新题.
    """
    answered_questions = {it.question for it in items}
    for spec in _FALLBACK_QUESTIONS:
        if spec["question"] in answered_questions:
            continue
        return AiIntakeNextResponse(
            question=spec["question"],
            description=spec.get("description", ""),
            options=list(spec["options"]),
            multiple=bool(spec.get("multiple")),
            allow_custom=bool(spec.get("allow_custom", True)),
            done=False,
            model_name=model_name,
            raw=None,
        )
    # 题库都答完了 → done
    return AiIntakeNextResponse(
        question="",
        description="",
        options=[],
        multiple=False,
        allow_custom=True,
        done=True,
        model_name=model_name,
        raw=None,
    )


# ---------------------------------------------------------------------------
# 公共: 生成下一题
# ---------------------------------------------------------------------------


async def generate_next_question(
    payload: AiIntakeNextRequest,
) -> AiIntakeNextResponse:
    """根据历史 items 生成下一题; 模型缺失/失败时本地兜底."""
    items = payload.items or []
    model_cfg = await _resolve_model_cfg(payload.model_id)

    # 硬上限: 已达上限直接 done
    if len(items) >= MAX_DYNAMIC_STEPS:
        return AiIntakeNextResponse(
            done=True,
            model_name=(model_cfg or {}).get("name"),
            raw=None,
        )

    if not model_cfg:
        logger.warning("intake.next: no available chat model, falling back to local")
        return _local_next_question(items, None)

    history_block = _build_history_block(items)
    step_no = len(items) + 1
    low, high = RECOMMENDED_TOTAL_STEPS
    vars_ = {
        "history_block": history_block,
        "step_no": str(step_no),
        "answered_count": str(len(items)),
        "recommended_low": str(low),
        "recommended_high": str(high),
    }
    try:
        raw_text = await _call_llm_for(
            model_cfg=model_cfg,
            prompt_key=NEXT_PROMPT_KEY,
            vars_=vars_,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("intake.next LLM call failed, falling back to local: %s", exc)
        fb = _local_next_question(items, model_cfg.get("name"))
        fb.raw = f"LLM 调用失败: {exc}"
        return fb

    obj = _try_parse_json_object(raw_text)
    if not obj:
        logger.warning("intake.next LLM output invalid JSON, falling back to local")
        fb = _local_next_question(items, model_cfg.get("name"))
        fb.raw = raw_text
        return fb

    options = _coerce_options(obj.get("options"))
    # 兜底: AI 忘了加「由 AI 决定」就手动补一个
    if options and "由 AI 决定" not in options:
        options.append("由 AI 决定")

    done = bool(obj.get("done"))
    # 安全网: 达到 MAX_DYNAMIC_STEPS-1 时强制 done, 防止 LLM 一直出题
    if len(items) + 1 >= MAX_DYNAMIC_STEPS:
        done = True

    return AiIntakeNextResponse(
        question=str(obj.get("question") or "").strip()[:500],
        description=str(obj.get("description") or "").strip()[:1000],
        options=options,
        multiple=bool(obj.get("multiple")),
        allow_custom=bool(obj.get("allow_custom", True)),
        done=done,
        model_name=model_cfg.get("name"),
        raw=raw_text,
    )


# ---------------------------------------------------------------------------
# 公共: 综合项目草稿
# ---------------------------------------------------------------------------


def _coerce_initial_concepts(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("entity_id") or "").strip()
        if not name:
            continue
        attrs = item.get("attributes")
        if not isinstance(attrs, dict):
            attrs = {}
        clean: Dict[str, Any] = {}
        for k, v in attrs.items():
            if isinstance(v, (str, int, float, bool)):
                if isinstance(v, str):
                    if not v.strip():
                        continue
                    clean[str(k)] = v.strip()
                else:
                    clean[str(k)] = v
        out.append({"name": name, "attributes": clean})
    return out


def _coerce_style_pref(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in value.items():
        if isinstance(v, (str, int, float, bool)):
            if isinstance(v, str) and not v.strip():
                continue
            out[str(k)] = v
    return out


def _local_synthesize(
    items: List[AiIntakeHistoryItem], model_cfg: Optional[Dict[str, Any]]
) -> AiIntakeSynthesizeResponse:
    """当 LLM 不可用 / 输出非 JSON 时, 用本地拼装给一份兜底草稿."""
    by_index = {i: it for i, it in enumerate(items)}
    # 抽几个关键维度 (用 question 文本粗匹配, 仅作兜底)
    def _find(needle: str) -> Optional[AiIntakeHistoryItem]:
        for it in items:
            if needle in (it.question or ""):
                return it
        return None

    era_it = _find("时代") or _find("世界")
    theme_it = _find("主题") or _find("基调")
    prota_it = _find("主角")
    pov_it = _find("视角")
    tone_it = _find("基调")
    free_it = _find("补充")

    era = _stringify_choice(era_it.choice) if era_it else "(未指定)"
    theme = _stringify_choice(theme_it.choice) if theme_it else "(未指定)"
    prota = _stringify_choice(prota_it.choice) if prota_it else "(未指定)"
    pov = _stringify_choice(pov_it.choice) if pov_it else "第三人称"
    tone = _stringify_choice(tone_it.choice) if tone_it else "(未指定)"
    free = (free_it.custom_text or "").strip() if free_it else ""

    title_seed = f"{era}{theme}录"[:200]
    worldview = (
        f"时代: {era}; 核心主题: {theme}; 主角设定: {prota}; "
        f"基调: {tone}; 补充: {free}".strip()[:20_000]
    )
    outline = (
        f"主角(类型: {prota})在 {era} 时代背景下, 因为 {theme} 的核心冲突, "
        f"踏上多章节的故事旅程. 整体基调 {tone}, 围绕用户提供的补充描述"
        f"({free or '无'})展开."[:50_000]
    )
    initial = [
        {"name": "主角", "attributes": {"设定": prota or "未指定"}},
        {"name": "搭档", "attributes": {"定位": "与主角同行"}},
    ]
    style = {"视角": pov or "第三人称", "语气": tone or "未指定"}
    return AiIntakeSynthesizeResponse(
        title=title_seed,
        genre=(theme or "通用")[:200],
        worldview=worldview,
        outline=outline,
        initial_concepts=initial,
        style_pref=style,
        model_id=(model_cfg or {}).get("id"),
        model_name=(model_cfg or {}).get("name"),
        raw=None,
    )


def _build_synth_response_from_obj(
    obj: Dict[str, Any], model_cfg: Optional[Dict[str, Any]]
) -> AiIntakeSynthesizeResponse:
    return AiIntakeSynthesizeResponse(
        title=str(obj.get("title") or "").strip()[:200],
        genre=str(obj.get("genre") or "").strip()[:200],
        worldview=str(obj.get("worldview") or "").strip()[:20_000],
        outline=str(obj.get("outline") or "").strip()[:50_000],
        initial_concepts=_coerce_initial_concepts(obj.get("initial_concepts")),
        style_pref=_coerce_style_pref(obj.get("style_pref")),
        model_id=(model_cfg or {}).get("id"),
        model_name=(model_cfg or {}).get("name"),
    )


async def synthesize_project(
    payload: AiIntakeSynthesizeRequest,
) -> AiIntakeSynthesizeResponse:
    """综合问答历史, 返回可一键建项的项目草稿."""
    items = payload.items or []
    if not items:
        raise IntakeError("items 不能为空")

    model_cfg = await _resolve_model_cfg(payload.model_id)
    if not model_cfg:
        logger.warning("intake.synth: no available chat model, falling back to local")
        return _local_synthesize(items, None)

    history_block = _build_history_block(items)
    vars_ = {"history_block": history_block}
    raw_text = ""
    try:
        raw_text = await _call_llm_for(
            model_cfg=model_cfg,
            prompt_key=SYNTH_PROMPT_KEY,
            vars_=vars_,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("intake.synth LLM call failed, falling back to local: %s", exc)
        fb = _local_synthesize(items, model_cfg)
        fb.raw = f"LLM 调用失败: {exc}"
        return fb

    obj = _try_parse_json_object(raw_text)
    if not obj:
        logger.warning("intake.synth LLM output invalid JSON, falling back to local")
        fb = _local_synthesize(items, model_cfg)
        fb.raw = raw_text
        return fb

    resp = _build_synth_response_from_obj(obj, model_cfg)
    resp.raw = raw_text
    return resp
