import logging
from typing import Any, Dict, List, Optional

from database import (
    get_characters_by_novel,
    get_config_by_id,
    get_enabled_configs,
    replace_characters,
)
from services import ai_service, file_service
from services.novel_service import get_novel_detail

logger = logging.getLogger(__name__)


CHARACTER_SYSTEM_PROMPT = (
    "你是一名专业的中文文学编辑，擅长从长篇小说片段中识别关键人物。"
    "请仅根据提供的文本判断人物，不要杜撰。优先识别有名有姓、有明确行为或对白的角色。"
    "请只输出严格的 JSON 对象，不要输出解释、注释或 Markdown 代码块。"
)


def build_character_prompt(
    novel_title: str,
    author: str,
    sample_text: str,
    max_characters: int,
) -> str:
    return (
        f"小说标题: {novel_title}\n"
        f"作者: {author or '未知'}\n"
        f"以下为该小说开头约 {len(sample_text)} 个字符的节选，请从中识别最多 {max_characters} 位主要人物。\n"
        "输出格式 (必须是合法 JSON，键名固定):\n"
        "{\n"
        '  "characters": [\n'
        '    {\n'
        '      "name": "人物姓名",\n'
        '      "role": "角色定位，例如主角/配角/反派/叙述者",\n'
        '      "aliases": ["别名/绰号/称呼"],\n'
        '      "description": "一段话描述人物身份、性格或与情节的关系",\n'
        '      "first_appearance": 首次出现的章节编号（若未知可省略或填 null）\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "要求:\n"
        "1. 严格使用 JSON 输出，不要添加额外字段；\n"
        "2. 人物姓名应保持原文写法；\n"
        "3. 若无明显人物，可返回 {\"characters\": []}；\n"
        "4. 描述应简洁，不超过 80 字。\n\n"
        "=== 文本节选开始 ===\n"
        f"{sample_text}\n"
        "=== 文本节选结束 ==="
    )


def parse_character_payload(payload: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not payload:
        return []
    raw_list = payload.get("characters") or []
    if not isinstance(raw_list, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    seen: set = set()
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        aliases = item.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [a.strip() for a in aliases.replace("、", ",").split(",") if a.strip()]
        if not isinstance(aliases, list):
            aliases = []
        first_appearance = item.get("first_appearance")
        try:
            if first_appearance is not None:
                first_appearance = int(first_appearance)
        except (TypeError, ValueError):
            first_appearance = None
        cleaned.append(
            {
                "name": name,
                "role": (item.get("role") or "").strip() or None,
                "aliases": [str(a).strip() for a in aliases if str(a).strip()],
                "description": (item.get("description") or "").strip() or None,
                "first_appearance": first_appearance,
            }
        )
    return cleaned


def _prepare_sample_text(content: str, max_chars: int) -> str:
    cleaned = (content or "").strip()
    if len(cleaned) <= max_chars:
        return cleaned
    head = cleaned[: int(max_chars * 0.6)]
    tail = cleaned[-int(max_chars * 0.3) :]
    return f"{head}\n\n…\n\n{tail}"


async def _resolve_model_config(model_config_id: Optional[int]) -> Dict[str, Any]:
    if model_config_id:
        cfg = await get_config_by_id(model_config_id)
        if not cfg:
            raise ValueError("指定的模型配置不存在")
        return cfg
    enabled = await get_enabled_configs()
    if not enabled:
        raise ValueError("未找到可用的模型，请先在系统设置中启用至少一个模型")
    return enabled[0]


async def extract_characters(
    novel_id: int,
    *,
    model_config_id: Optional[int] = None,
    max_chars: int = 8000,
    max_characters: int = 20,
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
    sample = _prepare_sample_text(content, max_chars)
    user_prompt = build_character_prompt(
        novel["title"], novel.get("author") or "", sample, max_characters
    )

    raw = await ai_service.chat_completion(
        provider=model_cfg["provider"],
        model_url=model_cfg["model_url"],
        api_key=model_cfg["api_key"],
        model_name=model_cfg["model_name"],
        system_prompt=CHARACTER_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        temperature=0.3,
        max_tokens=2048,
    )
    payload = ai_service.parse_json_object(raw)
    if not payload or "characters" not in payload:
        logger.warning("AI 响应未包含 characters 字段: %s", raw[:200])
        raise ValueError("AI 返回结果格式不正确，请重试或更换模型")

    characters = parse_character_payload(payload)
    stored = await replace_characters(novel_id, characters, model_cfg.get("id"))
    return {
        "model": model_cfg.get("name") or model_cfg.get("model_name"),
        "characters": stored,
    }


async def list_characters(novel_id: int) -> List[Dict[str, Any]]:
    return await get_characters_by_novel(novel_id)
