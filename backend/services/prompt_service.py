"""AI prompt template management service.

Centralises every prompt that the application sends to the LLM, exposing
CRUD endpoints so users can view and customise them from the UI.

Each prompt template is keyed by a stable string identifier (e.g.
``kg.character``) so the rest of the codebase can fetch the active
template by key. The defaults are seeded on first run.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiosqlite

from database import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default prompt templates
# ---------------------------------------------------------------------------

# NOTE: These defaults must stay aligned with the historical hard-coded
# behaviour so users get a familiar experience out of the box. Variables
# inside ``user_prompt_template`` are referenced through ``str.format``
# with explicit ``{{`` / ``}}`` escaping (since the prompts themselves
# contain JSON examples with braces).

PROMPT_CATEGORIES = [
    {
        "key": "connection",
        "label": "连接测试",
        "description": "用于测试模型连通性、检验模型凭证是否有效的轻量提示词。",
    },
    {
        "key": "kg",
        "label": "知识图谱抽取",
        "description": "在构建人物 / 事件 / 关系知识图谱时使用的五段式提示词。",
    },
    {
        "key": "enrichment",
        "label": "小说加料",
        "description": "章节摘要、登场人物/关键事件识别、场景分类与改写规则的提示词。",
    },
    {
        "key": "rewrite_general",
        "label": "改写规则·通用",
        "description": "改写步骤中作为「通用指导」拼接的规则子模板。",
    },
    {
        "key": "rewrite_scene",
        "label": "改写规则·场景",
        "description": "改写步骤中按场景命中的规则子模板（如高燃战斗 / 情感爆发 / 推理悬疑）。",
    },
    {
        "key": "creation",
        "label": "AI 小说创作",
        "description": "AI 小说创作工作流的 Agent 提示词: 决策 / 撰写 / 审核 / 单章实体抽取。",
    },
]


DEFAULT_PROMPTS: List[Dict[str, Any]] = [
    # ---- connection test ---------------------------------------------------
    {
        "key": "connection.test",
        "category": "connection",
        "name": "连接测试提示词",
        "description": "用于向模型发送最小请求以验证连接与凭证。max_tokens 固定为 1。",
        "system_prompt": "",
        "user_prompt_template": "hi",
        "temperature": 0.0,
        "max_tokens": 1,
    },
    # ---- knowledge graph ---------------------------------------------------
    {
        "key": "kg.character",
        "category": "kg",
        "name": "人物实体抽取",
        "description": "Phase 1: 从小说片段中抽取人物实体及其内在属性。",
        "system_prompt": (
            "你是一名小说知识图谱构建专家，擅长从中文长篇小说片段中识别关键人物实体，"
            "并仅记录描述人物自身特征的内在属性（标量信息），不涉及与其他人物/事件的关系。"
            "请严格输出 JSON 数组（不要包裹在对象里），不要输出解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """你是小说知识图谱构建专家。请从以下小说文本中提取所有**人物实体**，并仅提取其**内在属性**（即描述人物自身特征的标量信息，不涉及人物间关系）。

输入文本：
{chunk_text}

任务要求：
1. 为每个人物赋予唯一ID（如 `char_001`，同一人物在不同片段尽量复用同一ID；无法确认则新建）。
2. 仅关注**本片段**明确出现的人物；不要把无关人物也罗列进来。无法确认的宁可省略，也不要猜测。
3. 提取以下内在属性（如果文中出现；未出现则省略该字段，不要编造）：
   - 别名/字号
   - 性别
   - 身份/职位/地位（如「荣国府嫡孙」）
   - 性格标签
   - 外貌特征
   - 籍贯
   - 家族 / 所属组织
   - 阵营 / 立场
   - 婚姻状况
   - 首次出场位置（如「第3回」或「第三章」）
   - 能力/特长（列表）
   - 代表台词（一句话，最有代表性的对白或口头禅）
4. 严禁将人物与其他人物、地点、组织的关系混入属性。例如「丫鬟是袭人」不能作为字段，因为袭人是另一个人物实体。
5. 如果同一人物在不同段落出现，尽量合并，使用同一ID。

参考示例（仅作格式参考，不代表必须输出这些字段）：
[
  {{
    "id": "char_001",
    "name": "贾宝玉",
    "attributes": {{
      "别名": ["怡红公子", "绛洞花主"],
      "性别": "男",
      "身份": "贾府嫡孙",
      "性格": ["叛逆", "多情"],
      "外貌": "面如中秋之月",
      "籍贯": "金陵",
      "家族": "贾府",
      "阵营": "贾府",
      "婚姻状况": "未婚",
      "首次出场位置": "第三回",
      "能力/特长": ["诗才", "机敏"],
      "代表台词": "女儿是水做的骨肉"
    }}
  }}
]

如果没有提取到任何人物，返回空数组 []。""",
        "temperature": 0.3,
        "max_tokens": 2400,
    },
    {
        "key": "kg.event",
        "category": "kg",
        "name": "事件实体抽取",
        "description": "Phase 2: 从片段中识别事件实体（情节单元）。",
        "system_prompt": (
            "你是一名小说知识图谱构建专家，擅长从中文长篇小说片段中识别事件实体（情节单元），"
            "并仅记录事件自身的内在属性（时间/地点/章回/摘要/起因/结果），不参与人物关系建模。"
            "请严格输出 JSON 数组，不要输出解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """你是小说知识图谱构建专家。请从以下文本中提取所有**事件实体**（情节单元），并提取其内在属性。

输入文本：
{chunk_text}

已知人物列表（供参考；不要将事件与人物的关系作为事件属性）：
{character_list_json}

任务要求：
1. 为每个事件赋予唯一ID（如 `evt_001`）。
2. 仅关注**本片段**明确出现的事件；不要编造未发生的事件。
3. 提取以下内在属性（如果文中明确；未出现则省略该字段）：
   - 时间（精确或相对时间，如「芒种节」「三月初三」）
   - 地点（如「大观园沁芳闸桥边」）
   - 章回
   - 摘要（一两句话概括事件过程）
   - 起因
   - 结果
   - 重要性（"高" / "中" / "低"，依据对主线/人物的影响）
   - 情绪基调（如「悲伤压抑」「激烈冲突」）
   - 关键物品（列表，如「通灵宝玉」「花锄」）
   - 冲突类型（如「内心冲突」「外部冲突」「误会」）
   - 结果影响（对人物关系或主线的推进）
4. 事件参与人物不放在属性里，后续由关系边处理。
5. 事件粒度：以「情节转折点或人物交互的完整片段」为最小单元。单独一个动作（如「宝玉喝了口茶」）不必独立成事件；至少需包含「意图 + 行为 + 反映/结果」之一。

参考示例（仅作格式参考，不代表必须输出这些字段）：
[
  {{
    "id": "evt_001",
    "name": "黛玉葬花",
    "attributes": {{
      "时间": "芒种节",
      "地点": "大观园沁芳闸桥边",
      "章回": "第27回",
      "摘要": "黛玉在花冢前哭泣，吟诵葬花词，宝玉听后感慨。",
      "起因": "黛玉误会宝玉不见她",
      "结果": "二人感情更深",
      "重要性": "高",
      "情绪基调": "悲伤",
      "关键物品": ["花锄", "花冢"],
      "冲突类型": "内心冲突",
      "结果影响": "深化宝黛情感线"
    }}
  }}
]
无事件则输出 []。""",
        "temperature": 0.3,
        "max_tokens": 2400,
    },
    {
        "key": "kg.participation",
        "category": "kg",
        "name": "人物-事件参与关系",
        "description": "Phase 3: 提取人物参与事件的关系边，附角色与具体行为。",
        "system_prompt": (
            "你是一名小说知识图谱构建专家，根据文本中已经识别出的人物与事件实体，"
            "提取「人物参与事件」的关系边，并附上参与的角色与具体行为。"
            "事件本身的时间/地点等属性不放在边上。"
            "请严格输出 JSON 数组，不要输出解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """你是小说知识图谱构建专家。请根据文本，提取**人物参与事件**的关系，并给出参与的具体角色和行为。

输入文本：
{chunk_text}

已抽取人物实体：
{character_list_json}

已抽取事件实体：
{event_list_json}

任务要求：
1. 仅识别本片段中**明确出现**的人物与事件之间的参与关系，不要推断未明示的关系。
2. 关系固定为 `PARTICIPATES_IN`。
3. 在关系的 `properties` 字段中可附加以下键（未出现则省略该键，不要编造）：
   - 角色（如「发起者」「受害者」「见证者」「协助者」）
   - 具体行为（一句话概括该人物在此事件中的动作）
   - 时间（参与时间点或时间范围）
   - 地点（参与地点）
   - 情绪（当时情绪，如「愤怒」「悲伤」「喜悦」）
   - 动机（参与动机，如「为朋友复仇」「被迫」）
4. 多人参与同一事件，每个参与关系单独输出一条。
5. 不得将事件的时间、地点等内在属性（属于事件自身）作为关系属性（除非该时间/地点特指该人物的参与）。

输出格式：严格输出 JSON 数组，每条关系一个对象：
[
  {{
    "source": "char_001",
    "relation": "PARTICIPATES_IN",
    "target": "evt_001",
    "properties": {{
      "角色": "发起者",
      "具体行为": "吟诵葬花词",
      "情绪": "悲伤",
      "动机": "自伤自怜"
    }}
  }}
]
无关系则输出 []。""",
        "temperature": 0.3,
        "max_tokens": 2400,
    },
    {
        "key": "kg.char_relation",
        "category": "kg",
        "name": "人物间长期关系",
        "description": "Phase 4: 抽取不依赖单一事件的人物长期关系。",
        "system_prompt": (
            "你是一名小说知识图谱构建专家，提取不依赖于单一事件的人物间长期关系"
            "（亲属、社交、情感、敌对、主仆等）。这些关系是直接连接两个人物实体的边。"
            "请严格输出 JSON 数组，不要输出解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """你是小说知识图谱构建专家。请提取**不依赖于单一事件**的人物间长期关系（亲属、社交、情感等）。这些关系直接连接人物实体。

输入文本：
{chunk_text}

已知人物列表：
{character_list_json}

任务要求：
1. 仅基于本片段明确陈述的人物关系抽取，不要凭人物背景常识补充。
2. 识别人物之间的长期关系，例如：
   - 亲属：父亲、母亲、哥哥、表妹等
   - 社交：朋友、同僚、恩人
   - 情感：恋人、倾慕、厌恶
   - 社会关系：主子与仆从、师生等
3. 关系标签使用简洁的动词或名词（如 `父亲`、`丫鬟`、`倾慕`）。
4. 一条关系只涉及两个人物，方向从主动到被动或从长辈到晚辈，需保持一致。
5. 可在 `properties` 中附加以下键（未出现则省略）：
   - 亲疏程度（如「亲密」「疏远」「敌对」）
   - 关系确立时间（如「第3回」）
   - 关系状态（如「稳定」「破裂中」「暗恋中」）

输出格式：严格输出 JSON 数组，每条关系一个对象：
[
  {{
    "source": "char_003",
    "relation": "父亲",
    "target": "char_001",
    "properties": {{
      "亲疏程度": "亲密",
      "关系状态": "稳定"
    }}
  }},
  {{
    "source": "char_005",
    "relation": "表妹",
    "target": "char_001",
    "properties": {{
      "亲疏程度": "亲密",
      "关系状态": "暗恋中"
    }}
  }}
]
无关系则输出 []。""",
        "temperature": 0.3,
        "max_tokens": 2400,
    },
    {
        "key": "kg.event_relation",
        "category": "kg",
        "name": "事件间包含 / 因果关系",
        "description": "Phase 5: 抽取事件之间的「包含」或「导致」关系。",
        "system_prompt": (
            "你是一名小说知识图谱构建专家，根据已知事件列表，识别事件之间的「包含」或「导致」关系。"
            "大事件指向子事件用「包含」；原因事件指向结果事件用「导致」。"
            "请严格输出 JSON 数组，不要输出解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """你是小说知识图谱构建专家。请根据文本，识别事件之间的**包含**或**因果**关系。

输入文本：
{chunk_text}

已知事件列表：
{event_list_json}

任务要求：
1. 仅基于本片段明确陈述的关联抽取，不要跨片段推测。
2. 若一个事件是另一个事件的子事件（如「抄检大观园」包含「司棋被逐」），使用关系 `包含`。
3. 若一个事件直接导致另一个事件，使用关系 `导致`。
4. 方向严格遵循：大事件指向小事件为 `包含`，因事件指向果事件为 `导致`。
5. 可在 `properties` 中附加以下键（未出现则省略）：
   - 因果强度（"强" / "中" / "弱"，依据情节关联紧密度）
   - 时间距离（如「同一场景」「间隔数月」）
   - 备注（必要时给出一句说明）

输出格式：严格输出 JSON 数组，每条关系一个对象：
[
  {{
    "source": "evt_010",
    "relation": "包含",
    "target": "evt_011",
    "properties": {{
      "因果强度": "强",
      "时间距离": "同一场景"
    }}
  }}
]
无则 []。""",
        "temperature": 0.3,
        "max_tokens": 2400,
    },
    # ---- knowledge graph: validator prompts (used by MergeValidatorAgent) ---
    {
        "key": "kg.validator.dedup",
        "category": "kg",
        "name": "实体同义合并校验",
        "description": "Validator 阶段: 给定候选人物/事件对, 判断是否同义, 若是返回合并结果。",
        "system_prompt": (
            "你是一名严谨的知识图谱质量审查员, 擅长判断两个实体是否指向同一个人物/事件。"
            "只输出 JSON, 不要解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """判断以下两个实体是否指向同一个人物(若是人物)或同一个事件(若是事件)。

候选 A: {a_json}
候选 B: {b_json}
原文片段: {evidence}

要求:
1. 仅在能确定指向同一对象时返回 is_same=true; 若只有较弱关联则返回 false。
2. 若 A、B 实为同一对象, merged 字段返回合并后的实体(保留更具体、属性更完整的那一方, 属性取并集并去重)。
3. 若 A、B 是不同对象, merged 字段省略。

输出 JSON:
{{
  "is_same": true,
  "merged": {{
    "id": "char_xxx 或 evt_xxx",
    "name": "...",
    "attributes": {{...}}
  }}
}}
无则 {{"is_same": false}}。""",
        "temperature": 0.1,
        "max_tokens": 800,
    },
    {
        "key": "kg.validator.completeness",
        "category": "kg",
        "name": "覆盖度核查",
        "description": "Validator 阶段: 对已抽取的人物/事件/关系, 核查是否存在漏抽取。",
        "system_prompt": (
            "你是一名严谨的知识图谱审查员, 找出抽取结果中可能漏掉的人物、事件、关系。"
            "只输出 JSON, 不要解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """对照原文,核查以下抽取结果是否完整。

已知人物: {character_list_json}
已知事件: {event_list_json}
已知人物-事件参与: {participation_list_json}
原文片段: {chunk_text}

任务:
1. missing_characters: 列出原文中有名字/称谓/有对白, 但未出现在已知人物列表的可疑人物(给候选名和证据)。
2. missing_events: 列出原文中有明确情节转折或交互, 但未出现在已知事件的可疑事件(给候选名和证据)。
3. missing_participations: 对每个已知事件, 列出"明显应当参与"但未在已知参与关系中的人物(给 character_id, event_id, 角色, 证据)。

输出 JSON:
{{
  "missing_characters": [{{"name": "...", "evidence": "..."}}],
  "missing_events": [{{"name": "...", "evidence": "..."}}],
  "missing_participations": [
    {{"character": "char_xxx", "event": "evt_xxx", "role": "...", "evidence": "..."}}
  ]
}}
若无缺失, 对应数组输出 []。""",
        "temperature": 0.2,
        "max_tokens": 2000,
    },
    {
        "key": "kg.validator.re_extract",
        "category": "kg",
        "name": "补漏重抽",
        "description": "Validator 反馈环: 针对覆盖度核查标记的缺失项, 定向补抽。",
        "system_prompt": (
            "你是一名严谨的知识图谱构建员, 只针对列出的缺失项进行补抽, 不要重复输出已存在的实体。"
            "只输出 JSON 数组, 不要解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """已知实体: {existing_list_json}
待补抽缺失项: {missing_json}
原文片段: {chunk_text}

针对每个缺失项, 输出一个对象, 用 type 区分:
- "character": {{"type": "character", "id": "char_xxx", "name": "...", "attributes": {{...}}}}
- "event":    {{"type": "event",    "id": "evt_xxx",  "name": "...", "attributes": {{...}}}}
- "participation": {{"type": "participation", "source": "char_xxx", "target": "evt_xxx",
                       "relation": "PARTICIPATES_IN",
                       "role": "...", "action": "..."}}

输出严格 JSON 数组, 元素只能是以上三种之一。""",
        "temperature": 0.2,
        "max_tokens": 2000,
    },
    # ---- novel enrichment ------------------------------------------------
    {
        "key": "enrichment.summary",
        "category": "enrichment",
        "name": "章节内容摘要",
        "description": "Step 1: 单章 100~200 字内容总结, 为后续识别/改写提供上下文。",
        "system_prompt": (
            "你是一名中文长篇小说编辑, 擅长用简洁准确的语言概括章节内容。"
            "请严格输出纯文本, 不要使用 Markdown / JSON / 编号 / 列表。"
        ),
        "user_prompt_template": """请为以下小说章节写一段【内容摘要】, 100~200 字, 覆盖以下要点:

1. 本章主要发生了什么事 (主线情节)
2. 关键人物是谁, 各自做了什么
3. 场景在哪里 (时间/地点)
4. 留下了什么悬念 / 转折 / 情绪

章节标题: {chapter_title}

章节正文:
{chapter_text}

【要求】
- 100~200 字, 不超过 250 字
- 第三人称, 不出现「本文/本章」等元叙述
- 不要照抄原句, 概括即可
- 不要使用 Markdown 或列表符号""",
        "temperature": 0.3,
        "max_tokens": 600,
    },
    {
        "key": "enrichment.recognition",
        "category": "enrichment",
        "name": "登场人物 / 关键事件 / 场景识别",
        "description": "Step 2: 抽取登场人物 + 关键事件 + 场景标签, 输出 JSON 对象。",
        "system_prompt": (
            "你是一名小说文本分析专家, 从章节中精确识别登场人物、关键事件与场景类型。"
            "只输出严格 JSON 对象, 不要解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """请从以下小说章节中识别:
1. 【登场人物】本章明确出场/有台词/有动作的角色 (不含只被提名的背景人物)
2. 【关键事件】本章推动主线或有戏剧张力的 2~5 个事件
3. 【场景标签】本章的主要场景类型 (1~2 个, 用简短中文标签, 如「高燃战斗场景」「情感爆发时刻」「日常铺垫」「推理悬疑」)

章节标题: {chapter_title}

章节正文:
{chapter_text}

【输出 JSON 格式, 不要任何其他内容】
{{
  "characters": [
    {{"name": "角色名", "description": "本章内表现/状态/动作的一句话描述"}}
  ],
  "events": [
    {{"name": "事件短名", "description": "事件的一句话描述"}}
  ],
  "scene_tag": "场景标签"
}}""",
        "temperature": 0.2,
        "max_tokens": 1200,
    },
    {
        "key": "enrichment.rewrite",
        "category": "enrichment",
        "name": "AI 改写",
        "description": "Step 3: 结合 summary + 人物事件 + 改写规则 + 用户加料需求, 重写章节正文。",
        "system_prompt": (
            "你是一名擅长小说加料改写的写作助手。"
            "改写目标是: 在保留原章节主线和关键事件的前提下, 增强画面感、对话张力、动作细节与情绪渲染, "
            "避免偏离原作设定与人设。"
            "用户会在「加料需求」中明确给出本次加料的方向, 请优先按用户意图展开, "
            "若未给出则按通用规则均衡增强。"
            "输出仅包含改写后的正文, 不要解释、注释、Markdown 或章节标题。"
        ),
        "user_prompt_template": """请改写以下章节。

【章节标题】{chapter_title}
【章节摘要】{summary}
【登场人物 / 关键事件】{recognition_json}
【场景标签】{scene_tag}

【通用改写规则】
{general_rule}

【场景特定改写规则】
{scene_rule}

【用户加料需求】(可空, 优先遵循)
{enrichment_intent}

【原文】
{chapter_text}

【改写要求】
1. 保留主要人物、事件顺序与核心设定, 不要改变主线走向
2. 在以下方面做加料:
   - 心理活动 / 情绪渲染 (2~3 处)
   - 对话张力 / 动作细节 (1~2 处)
   - 场景氛围 / 感官描写 (1~2 处)
3. 不要生造新角色 / 新支线
4. 字数控制在原文的 1.0~1.5 倍, 不要无限膨胀
5. 仅输出改写后的正文, 不含章节标题 / 元注释""",
        "temperature": 0.5,
        "max_tokens": 4000,
    },
    {
        "key": "enrichment.scene_classify",
        "category": "enrichment",
        "name": "场景分类",
        "description": "可选步骤: 给定章节正文, 给出 1~2 个场景标签, 供改写时按场景选规则。",
        "system_prompt": (
            "你是一名小说文本分析专家, 擅长为章节打场景标签。"
            "只输出严格 JSON 数组, 不要解释、注释或 Markdown 代码块。"
        ),
        "user_prompt_template": """请从下列【场景候选】中为当前章节选择 1~2 个最匹配的标签, 按匹配度从高到低排序:

场景候选: 高燃战斗场景, 情感爆发时刻, 日常铺垫, 推理悬疑, 政治权谋, 轻松搞笑, 恐怖惊悚, 浪漫言情, 离别重逢, 修炼突破

章节标题: {chapter_title}
章节正文:
{chapter_text}

【输出严格 JSON 数组】""",
        "temperature": 0.1,
        "max_tokens": 200,
    },
    # ---- rewrite rules 通用 + 场景特定 默认占位 ------------------------
    {
        "key": "enrichment.rewrite_rule.general",
        "category": "rewrite_general",
        "name": "默认通用改写规则",
        "description": "改写步骤会自动拼接本模板到 `enrichment.rewrite` 的「通用改写规则」位置。",
        "system_prompt": "",
        "user_prompt_template": """- 保留原章节的主要情节, 不偏离主线
- 在保留人设的前提下增加 2~3 处心理活动 / 情绪渲染
- 增强对话张力, 让关键对话更带感
- 加入 1~2 处感官描写 (视 / 听 / 嗅 / 触 / 味)
- 不创造新角色 / 新支线
- 篇幅控制在原文 1.0~1.5 倍""",
        "temperature": 0.4,
        "max_tokens": 2400,
    },
    {
        "key": "enrichment.rewrite_rule.scene_battle",
        "category": "rewrite_scene",
        "name": "高燃战斗场景改写",
        "description": "按场景标签「高燃战斗场景」命中, 自动拼接到改写 prompt。",
        "system_prompt": "",
        "user_prompt_template": """- 强化动作动词, 短句切割, 提高阅读节奏
- 增加打击感 (声音 / 震动 / 光影 / 余波)
- 用内心独白或微表情呈现高手对决的张力
- 招数不必换名, 但要让每次出招都有画面感""",
        "temperature": 0.4,
        "max_tokens": 2400,
    },
    {
        "key": "enrichment.rewrite_rule.scene_emotion",
        "category": "rewrite_scene",
        "name": "情感爆发时刻改写",
        "description": "按场景标签「情感爆发时刻」命中, 自动拼接到改写 prompt。",
        "system_prompt": "",
        "user_prompt_template": """- 强化对话节奏与潜台词, 用停顿 / 沉默传达情绪
- 描写微表情 / 肢体语言 / 视线变化
- 心理活动要克制, 让读者自己感受
- 避免直白的「她很伤心」, 用细节代替""",
        "temperature": 0.4,
        "max_tokens": 2400,
    },
    # ============================================================
    # AI 小说创作 (三 Agent + 单章抽取)
    # ============================================================
    {
        "key": "creation.planner.direction",
        "category": "creation",
        "name": "决策 Agent (Planner)",
        "description": "根据大纲、已有剧情摘要、当前知识图谱与用户意图, 生成 3 个差异化分叉方向.",
        "system_prompt": (
            "你是一名长篇小说总编剧. 你的任务是结合创作大纲、上一章摘要、当前"
            "知识图谱(人物 / 地点 / 未完结事件 / 未回收伏笔) 与用户本轮意图,"
            "为下一章设计 3 个**真正不同**的剧情分叉方向."
            "每个方向必须包含: 标题, 一句话梗概, 必须出场的关键实体, 必须推进/回收的伏笔,"
            "情绪基调, 与已有设定的硬约束 (不要让角色做违反人设的事)."
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 项目设定
- 标题: {project_title}
- 类型: {genre}
- 世界观: {worldview}
- 大纲: {outline}
- 文风偏好: {style_pref}

# 知识图谱 (主角 / 关键人物 / 未完结事件 / 未回收伏笔)
{kg_context}

# 上一章摘要 (用于衔接文风与情节)
{last_chapter_summary}

# 用户本轮意图 / 偏好
{user_intent}

# 任务
为第 {chapter_no} 章生成 3 个**相互差异化**的分叉方向:
1. 一个偏动作 / 冲突驱动
2. 一个偏心理 / 情感驱动
3. 一个偏意外 / 反转或世界观展开

【严格 JSON 输出】格式:
{{
  "directions": [
    {{
      "index": 0,
      "title": "方向标题 (≤15 字)",
      "synopsis": "一句话梗概 (≤80 字)",
      "focus": "动作 | 心理 | 意外",
      "key_entities": ["实体 1", "实体 2"],
      "foreshadowing": ["要推进的伏笔 1", "要回收的伏笔 2"],
      "themes": ["本章要触碰的主题 1", "主题 2"],
      "tone": "紧张 | 温馨 | 悲壮 | 悬疑 | 热血",
      "hard_constraints": ["禁止冲突: ...", "角色限制: ..."],
      "key_event": "本章核心事件 (1-2 句)"
    }},
    ... 共 3 个
  ]
}}""",
        "temperature": 0.5,
        "max_tokens": 2400,
    },
    {
        "key": "creation.writer.chapter",
        "category": "creation",
        "name": "执行 Agent (Writer)",
        "description": "按 Planner 给定的方向 + 知识图谱上下文, 撰写完整章节正文 (2500-3500 字). 严格遵守世界观/总纲/文风/已有角色与事件.",
        "system_prompt": (
            "你是一名长篇小说作者. 你将根据决策 Agent 给定的方向, "
            "结合知识图谱(项目设定 / 已知人物 / 关键事件 / 关系) 撰写一个完整章节.\n"
            "硬性要求:\n"
            "1. 字数 2500-3500 字 (按非空白字符计, 不可少于此下限);\n"
            "2. 严格遵守 #项目设定 中的世界观、总纲、文风偏好, 不偏离;\n"
            "3. 涉及知识图谱中已有的人物时, 其姓名 / 身份 / 性格 / 与其他角色关系 "
            "必须与图谱一致, 不得擅自改名或改变已建立的关系;\n"
            "4. 涉及 #决策方向 给定的关键实体 / 硬约束 / 核心事件时, 必须落地;\n"
            "5. 文风与上一章末尾自然衔接, 不要复读上一章;\n"
            "6. 只输出章节正文 (可含小标题), 不要章节元信息 / 注释 / Markdown 代码块.\n"
            "展开技巧: 场景描写 + 对话 + 心理活动 + 动作细节 + 伏笔/钩子, "
            "每段至少 3-5 句, 不要一句话就跳到下一段."
        ),
        "user_prompt_template": """# 项目设定 (来自 ai_projects 表, 整本小说必须严格遵守)
- 标题: {project_title}
- 类型: {genre}
- 世界观: {worldview}
- 大纲 (故事走向): {outline}
- 文风偏好: {style_pref}

# 本章标题 (综合 3 方向提炼的章节级标题)
{chapter_title}

# 上一章末尾段落 (用于衔接文风, 避免重复)
{last_chapter_tail}

# 知识图谱上下文 (项目级设定 + 主角 / 出场人物 / 关键地点 / 未完结事件)
{kg_context}

# 决策 Agent 给定的方向 (本章主线)
- 标题: {direction_title}
- 梗概: {direction_synopsis}
- 侧重点: {direction_focus}
- 关键实体: {direction_entities}
- 必须推进 / 回收的伏笔: {direction_foreshadowing}
- 情绪基调: {direction_tone}
- 硬约束: {direction_constraints}
- 本章核心事件: {direction_key_event}

# 用户本轮意图
{user_intent}

# 任务
撰写第 {chapter_no} 章完整正文. 不要生造新角色 / 新支线.
字数控制在 2500-3500 字 (这是硬性要求, 不要少于 2500). 输出格式:
- 第 1 段: 直接进入正文, 不要章节标题 / 引子
- 中间: 完整情节展开 (含场景描写 / 对话 / 心理活动 / 动作细节)
- 末段: 自然收尾, 为下一章留 1-2 处钩子

写作约束:
- 涉及已知角色时, 严格沿用 #项目设定 与 #知识图谱 中的姓名 / 身份 / 关系
- 涉及方向给定的关键实体时, 必须让其在章节中真正出场并推进
- 不要与 #大纲 的故事走向矛盾""",
        "temperature": 0.7,
        "max_tokens": 8000,
    },
    {
        "key": "creation.writer.chapter_title",
        "category": "creation",
        "name": "章节标题生成",
        "description": "用户没填章节标题时, 基于 Planner 给定的 3 个方向 (title/synopsis/key_event) 提炼一个能代表本章核心的章节级标题 (≤18 字).",
        "system_prompt": (
            "你是一名长篇小说总编剧. Planner 刚为第 N 章生成了 3 个差异化分叉方向 (动作 / 心理 / 意外).\n"
            "你的任务: 综合 3 个方向的标题 / 梗概 / 核心事件, 提炼一个能代表**本章核心**的章节级标题.\n"
            "要求:\n"
            "1. 字数 ≤ 18 字 (中文), 简洁有力, 引人入胜;\n"
            "2. 标题应反映本章主线的核心冲突或转折, 而不是某个具体方向的标题;\n"
            "3. 不要使用「第N章」「Chapter N」之类的前缀;\n"
            "4. 与项目标题区分开来, 这是**单章**标题;\n"
            "5. 直接输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 项目名
{project_title}

# 第 {chapter_no} 章 — Planner 给定的 3 个差异化方向
{directions_block}

# 用户本轮意图
{user_intent}

# 任务
综合以上 3 个方向, 提炼一个能代表本章核心的章节级标题 (≤18 字).
标题应能反映本章的**核心冲突 / 转折 / 主题**, 让读者一眼能看出本章讲什么.

【严格 JSON 输出】格式:
{{
  "title": "..."
}}""",
        "temperature": 0.4,
        "max_tokens": 200,
    },
    {
        "key": "creation.critic.review",
        "category": "creation",
        "name": "审核 Agent (Critic)",
        "description": "对单个候选章节做多维度审核, 输出评分 + 优缺点 + 修改建议.",
        "system_prompt": (
            "你是一名长篇小说审稿编辑. 你将根据一致性 / 逻辑 / 伏笔 / 文笔 / 差异化 5 个维度,"
            "对单个候选章节做严格审核, 并给出 0-10 分的综合评分 + 优缺点 + 具体修改建议."
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 章节正文 (待审核)
{chapter_content}

# 项目设定
- 标题: {project_title}
- 类型: {genre}
- 世界观: {worldview}

# 知识图谱 (用于一致性核查)
{kg_context}

# 上一章摘要 (用于衔接核查)
{last_chapter_summary}

# 决策方向 (与本候选匹配)
- 方向: {direction_title} ({direction_focus})
- 硬约束: {direction_constraints}

# 任务
按以下 5 个维度 0-10 打分, 并指出具体问题:
1. 一致性: 与知识图谱是否冲突 (人物关系 / 设定 / 时间线)
2. 逻辑性: 情节是否合理, 人物行为是否符合性格
3. 伏笔: 是否遗漏必须回收 / 推进的伏笔
4. 文笔: 行文流畅度 / 节奏感 / 对话自然度
5. 差异化: 本版本与同章其他候选的差异度 (自评)

【严格 JSON 输出】格式:
{{
  "scores": {{"consistency": 8, "logic": 7, "foreshadowing": 6, "style": 9, "differentiation": 7}},
  "overall": 7.4,
  "strengths": ["亮点 1", "亮点 2"],
  "issues": ["问题 1", "问题 2"],
  "modifications": ["具体修改建议 1", "具体修改建议 2"],
  "kg_conflicts": [
    {{"entity": "实体名", "claim": "章节中的陈述", "kg_fact": "图谱中的事实", "severity": "warn|error"}}
  ]
}}""",
        "temperature": 0.3,
        "max_tokens": 1600,
    },
    {
        "key": "creation.intake.synthesize",
        "category": "creation",
        "name": "新建项目引导式问答综合",
        "description": "根据用户在 AI 引导式问答中(由 LLM 动态出题)的回答, 综合成一个完整可建项的项目设定.",
        "system_prompt": (
            "你是一名长篇小说创作助手. 用户已经通过 AI 引导式问答提供了若干信息, "
            "你的任务是综合这些选择, 输出一个可一键创建的完整项目草稿: 标题, 类型, "
            "世界观, 总纲, 初始人物列表, 文风偏好."
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# AI 引导式问答历史
按时间顺序, 每一步包含: 问题 / 候选选项 / 用户的最终选择(从选项选 + 自由补充)

{history_block}

# 任务
综合以上所有问答, 为用户生成一个**可一键创建**的 AI 创作项目草稿.
要求:
1. 标题: 富有吸引力, 8 字以内为宜, 不要包含「小说」「故事」等冗余词.
2. 类型: 用斜杠分隔的复合标签, 例如「玄幻/修仙」, 不要使用单个英文 tag.
3. 世界观: 80~200 字, 把时代背景/地理/力量体系/势力格局讲清楚. 优先用具体名词, 避免空泛形容词.
4. 总纲: 120~300 字, 主线 + 主角起点 + 主要冲突 + 故事走向. 必须能让 Planner 据此拆分章节.
5. 初始人物: 3~5 位, 每位包含 name 与 attributes (如 性别/身份/性格/与主角关系 等键值对). 主角必须出现.
6. 文风偏好: 从用户选项中提取, 用键值对表示. 至少包含 视角 / 语气 两个键, 可补充 节奏 / 文学性 等.
7. 如果用户的某项选择为「由 AI 决定」或留空, 自行合理推断.
8. 直接输出 JSON, 不要说「好的」「以下是」之类客套.

【严格 JSON 输出】格式:
{{
  "title": "...",
  "genre": "...",
  "worldview": "...",
  "outline": "...",
  "initial_concepts": [
    {{"name": "...", "attributes": {{"性别": "男", "身份": "...", "性格": "..."}}}}
  ],
  "style_pref": {{
    "视角": "...",
    "语气": "...",
    "节奏": "...",
    "文学性": "..."
  }}
}}""",
        "temperature": 0.6,
        "max_tokens": 2400,
    },
    {
        "key": "creation.intake.next_question",
        "category": "creation",
        "name": "新建项目引导式问答—下一题",
        "description": "根据用户前面的所有回答, 动态生成下一道题和 4~8 个覆盖多种可能性的选项.",
        "system_prompt": (
            "你是一名长篇小说创作助手, 正在通过引导式问答帮用户勾勒新项目."
            "你的任务是根据用户前面的所有回答, 动态出下一道题 + 4~8 个差异化的选项."
            "题目要紧扣前面答案, 引导用户逐步缩小范围; 选项要尽量覆盖多种可能性, "
            "包括对立/邻接/混搭等方向, 让用户一眼能看到'还有别的玩法'."
            "中文输出, 每项选项 ≤ 18 字, 末尾必须包含「由 AI 决定」一项以便用户交还决策权."
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 已有问答历史
按时间顺序, 每一步: 问题 / 候选选项 / 用户的选择(选项值 + 自由补充)

{history_block}

# 当前是第 {step_no} 步 (从 1 计数)
# 已结束步骤数: {answered_count}
# 推荐总步数: 4~7 步 (每步都应有信息增量)

# 任务
1. 综合上面的所有信息, 提出**下一个最值得问**的问题. 题目要承前启后, 不要重复已经问过的.
2. 给出 4~8 个差异化的选项, 覆盖:
   - 至少 1 个「保守主流」选项
   - 至少 1 个「反差/反转」选项
   - 至少 1 个「混搭/跨界」选项
3. 末尾必须追加「由 AI 决定」作为兜底选项.
4. 决定是否已经收集足够信息可以生成项目草稿:
   - 如果用户已经回答了 ≥ 5 步 且 关键维度(类型/时代/主角/基调/视角)都有覆盖 → 返回 done=true, 不再出题.
   - 如果用户的关键输入仍非常少(例如所有 free_text 都为空) → 继续出题, 优先追问用户画像.
   - 其它情况 → 自由判断, done 可为 true 也可为 false.
5. 自由发挥一个问题描述 (description), 解释这道题的目的; 若觉得没必要可返回空串.

【严格 JSON 输出】格式:
{{
  "question": "...",
  "description": "...",
  "options": ["选项 1", "选项 2", "...", "由 AI 决定"],
  "multiple": false,
  "allow_custom": true,
  "done": false
}}
""",
        "temperature": 0.7,
        "max_tokens": 800,
    },
    {
        "key": "creation.extractor.entity",
        "category": "creation",
        "name": "单章实体抽取",
        "description": "章节确认后, 从正文抽取人物 / 事件 / 关系, 入项目级知识图谱.",
        "system_prompt": (
            "你是一名小说知识图谱构建专家. 从给定的章节正文中抽取:"
            "1) 人物实体 (含姓名 + 内在属性);"
            "2) 事件实体 (含事件名 + 内在属性);"
            "3) 人物-事件 参与关系 (含 role / action);"
            "4) 人物-人物 关系 (含 relation);"
            "5) 事件-事件 关系 (含 relation, 如因果 / 包含 / 顺序)."
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 章节正文
{chapter_text}

# 任务
抽取本章中**本章节首次登场**或**本章发生显著状态变化**的实体和关系.
对延续已知图谱的实体, 仅记录**新属性**与**新关系**, 避免重复入库.
注意:
- entity_id 用 `char_NNN` / `evt_NNN` 形式, 复用上文已出现的同名 ID.
- attributes 只记录标量属性 (姓名 / 性别 / 外貌 / 性格 / 身份 / 当前状态 等).

【严格 JSON 输出】格式:
{{
  "characters": [
    {{"entity_id": "char_001", "name": "张三", "attributes": {{"性别": "男", "身份": "剑客", "当前状态": "负伤"}}}}
  ],
  "events": [
    {{"entity_id": "evt_001", "name": "张三夜探幽冥谷", "attributes": {{"时间": "深夜", "地点": "幽冥谷", "重要性": "高"}}}}
  ],
  "character_event_relations": [
    {{"source": "char_001", "target": "evt_001", "relation": "PARTICIPATES_IN", "role": "主角", "action": "探索"}}
  ],
  "character_relations": [
    {{"source": "char_001", "target": "char_002", "relation": "师徒", "properties": {{"亲疏": "亲近"}}}}
  ],
  "event_relations": [
    {{"source": "evt_001", "target": "evt_002", "relation": "导致", "properties": {{"因果强度": "强"}}}}
  ]
}}""",
        "temperature": 0.2,
        "max_tokens": 3000,
    },
    # ============================================================
    # v0.3.x 新增: 实体抽取 v2 (含 locations + 结构化字段)
    # ============================================================
    {
        "key": "creation.extractor.entity_v2",
        "category": "creation",
        "name": "单章实体抽取 v2 (含地点 + 结构化字段)",
        "description": "升级版抽取: 抽出人物 / 事件 / 地点 + 关键结构化字段 (role/faction/status/importance/time_label).",
        "system_prompt": (
            "你是一名小说知识图谱构建专家. 从给定章节正文中抽取 4 类实体 + 3 类关系:\n"
            "1) 人物: 含 name 与结构化字段 role(主角/配角/路人/反派) / faction(所属势力) / status(存活/失踪/死亡/转生) / importance(1-5)\n"
            "2) 事件: 含 name 与结构化字段 in_story_time(故事内时间, 如「第3年暮春」) / chapter_time_label(章内时间标签, 如「第3章 夜」) / importance(1-5)\n"
            "3) 地点 (locations): 含 name + location_type(城市/建筑/秘境/区域/异空间) + attributes(坐标/气候/控制势力/禁制/描述)\n"
            "4) 关系: char→char, char→event, event→event(causal/temporal/spatial), char→location\n"
            "5) 冲突标注 (conflicts_in_text): 如本章陈述与已知图谱冲突, 明确指出 [{{entity, claim, kg_fact, severity}}].\n"
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 章节正文
{chapter_text}

# 当前章号
{chapter_no}

# 任务
抽取本章中**本章节首次登场**或**本章发生显著状态变化**的实体和关系.
延续已知图谱的实体, 仅记录**新属性**与**新关系**, 避免重复入库.
- entity_id 形式: char_NNN / evt_NNN / loc_NNN. 复用上文已出现的同名 ID.
- importance 必填 (1-5, 5=主线), 不可省略.
- 若章节与下方「已知冲突」冲突, 必须在 conflicts_in_text 列出, 便于下一章避开.

# 已知冲突 (来自知识图谱, 必须回填/避开)
{kg_warnings}

【严格 JSON 输出】格式:
{{
  "characters": [
    {{"entity_id": "char_001", "name": "张三", "role": "主角", "faction": "武林盟", "status": "存活",
     "importance": 5,
     "attributes": {{"性别": "男", "身份": "剑客", "年龄": 28, "性格": "沉默寡言", "当前状态": "负伤"}}}}
  ],
  "events": [
    {{"entity_id": "evt_001", "name": "张三夜探幽冥谷", "in_story_time": "第3年 暮春", "chapter_time_label": "第3章 夜",
     "importance": 5,
     "attributes": {{"地点": "幽冥谷", "结果": "触发密室机关"}}}}
  ],
  "locations": [
    {{"entity_id": "loc_001", "name": "幽冥谷", "location_type": "秘境",
     "attributes": {{"控制势力": "幽冥教", "禁制": "夜半禁入", "气候": "常年阴雨"}}}}
  ],
  "character_event_relations": [
    {{"source": "char_001", "target": "evt_001", "relation": "PARTICIPATES_IN", "role": "主角", "action": "探索"}}
  ],
  "character_relations": [
    {{"source": "char_001", "target": "char_002", "relation": "师徒", "properties": {{"亲疏": "亲近"}}}}
  ],
  "event_relations": [
    {{"source": "evt_001", "target": "evt_002", "relation": "导致", "relation_type": "causal",
     "properties": {{"因果强度": "强"}}}}
  ],
  "conflicts_in_text": [
    {{"entity": "林渊", "claim": "章节中说他已经会御剑", "kg_fact": "第1章 KG 中他还没入门",
     "severity": "error"}}
  ]
}}""",
        "temperature": 0.2,
        "max_tokens": 4000,
    },
    {
        "key": "creation.extractor.plot_thread",
        "category": "creation",
        "name": "伏笔线索抽取",
        "description": "从已确认章节抽取/更新 plot_threads (伏笔/阴谋/角色弧/主题弧/承诺), 含 status (open/hinting/resolving/resolved/dropped) 和 priority (1-5).",
        "system_prompt": (
            "你是一名长篇小说结构分析专家. 你的任务是从章节正文中识别和更新『剧情线索』(plot threads):\n"
            "1) 伏笔 (foreshadowing): 早期埋下的暗示, 等待后续章节回收;\n"
            "2) 阴谋 (scheme): 角色或势力的意图计划;\n"
            "3) 角色弧 (character_arc): 角色从 A 状态到 B 状态的成长线;\n"
            "4) 主题弧 (theme_arc): 故事核心主题的演变;\n"
            "5) 承诺 (promise): 对读者承诺的事件『会发生在某个时刻』.\n"
            "为每条线索输出: thread_id, action(create|update|resolve|drop), status, priority.\n"
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 已确认章节正文
{chapter_content}

# 当前章号
{chapter_no}

# 当前已知的 open / hinting 线索 (用于 update/resolve)
{open_threads}

# 任务
1) 识别本章新引入的线索 (action: create, status: open 或 hinting)
2) 识别本章推进/回收/放弃的旧线索 (action: update/resolve/drop)
3) 给出每条线索的 priority (1-5, 5=主线) 与 thread_type

【严格 JSON 输出】格式:
{{
  "threads": [
    {{
      "thread_id": "thread_001",          // 复用上表 thread_id
      "action": "create|update|resolve|drop",
      "title": "张三的真正身世",
      "thread_type": "伏笔|阴谋|角色弧|主题弧|承诺",
      "status": "open|hinting|resolving|resolved|dropped",
      "priority": 5,
      "related_entity_ids": ["char_001", "char_002"],
      "notes": "本章通过母亲的遗物暗示他不是张家人"
    }}
  ]
}}""",
        "temperature": 0.3,
        "max_tokens": 1800,
    },
    {
        "key": "creation.compass.deviation",
        "category": "creation",
        "name": "CompassAgent 偏离度检测",
        "description": "每章 confirm 前, 5 维评估章节是否偏离大纲/根设定/伏笔/文风/主题, 输出 0-10 分与警示.",
        "system_prompt": (
            "你是一名长篇小说结构审计编辑. 你的任务是检测本章是否偏离了作者的原意与已建立的世界, "
            "并给用户清晰的『该不该保留』的判断.\n"
            "按以下 5 维 0-10 打分, 同时给出每维的『是否需要回炉』建议:\n"
            "1) 主题偏离: 本章是否在推进故事核心主题, 还是跑题/灌水\n"
            "2) 大纲偏离: 本章是否在按项目设定的大纲方向走, 有没有出现与设定冲突的转折\n"
            "3) 人物一致性: 人物的行为 / 性格 / 关系是否与图谱中已建立的一致\n"
            "4) 伏笔进度: 本章是否推进/回收了应该推进的伏笔, 是否有新埋伏\n"
            "5) 文风一致: 文风/视角/语气是否与前文保持一致\n"
            "≥3 维 < 6 分时给出 1~3 条具体 warning, 提示用户是否需要回滚/重写.\n"
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 项目根设定
{root_settings}

# 大纲
{outline}

# 本章标题
{chapter_title}

# 本章正文
{chapter_content}

# 当前章号
{chapter_no}

# 已知未结线索
{open_threads}

# 已知冲突 (KG 已记录)
{kg_warnings}

# 任务
按 5 维 0-10 打分. 若任何一维 < 6, 给一条 user-readable warning (≤30 字), 写明具体哪里偏离.

【严格 JSON 输出】格式:
{{
  "scores": {{
    "theme_deviation": 8,
    "outline_deviation": 7,
    "character_consistency": 6,
    "foreshadowing_progress": 5,
    "style_consistency": 9
  }},
  "overall": 7.0,
  "summary": "本章推进主线, 人物性格一致, 但遗留 2 处伏笔未推进.",
  "warnings": [
    {{"dim": "foreshadowing_progress", "text": "第3章埋的'黑衣客'伏笔, 本章没出现"}}
  ]
}}""",
        "temperature": 0.3,
        "max_tokens": 1400,
    },
    {
        "key": "creation.bridge.transition",
        "category": "creation",
        "name": "BridgeAgent 接缝检测",
        "description": "在生成第 N+1 章前调用: 检测章节 N 末尾到 N+1 开头的衔接质量, 给出冲突点和推荐的开头钩子.",
        "system_prompt": (
            "你是一名长篇小说结构编辑. 你的任务是检测两章之间的衔接质量, "
            "告诉 Writer 下一章该从哪句话开始承接, 怎么避开冲突, 怎么埋新钩子.\n"
            "只输出严格 JSON, 不要解释、注释或 Markdown 代码块."
        ),
        "user_prompt_template": """# 上一章末尾 (800 字)
{prev_tail}

# 本章 Planner 给定的方向
- 标题: {direction_title}
- 梗概: {direction_synopsis}
- 关键实体: {direction_entities}
- 必须推进的伏笔: {direction_foreshadowing}
- 本章核心事件: {direction_key_event}

# 当前 KG 已知冲突
{kg_warnings}

# 任务
1) 接缝质量: 0~10, 解释是否断崖 / 跳时间 / 跳人物
2) 冲突点: 上一章末尾与本章方向 / KG 是否有冲突
3) 开头钩子推荐: 2~3 个供 Writer 选 (开篇头 50 字内)

【严格 JSON 输出】格式:
{{
  "bridge_score": 8,
  "conflicts": ["上一章张三在长安, 本章方向说他在塞外, 缺过渡"],
  "open_hook_suggestions": [
    "张三在塞外客栈听到『黑衣人』, 接续第3章伏笔",
    "周伯意外出现, 揭示他早已在塞外布下暗手"
  ]
}}""",
        "temperature": 0.4,
        "max_tokens": 800,
    },
]


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

# Markers in the bundled user_prompt_template that did NOT exist in
# earlier schema versions. If any of these markers is missing from the
# stored template, the row is considered stale and will be refreshed to
# the bundled default on next startup.
_PROMPT_VERSION_MARKERS: Dict[str, str] = {
    "kg.character": "籍贯",
    "kg.event": "重要性",
    "kg.participation": "动机",
    "kg.char_relation": "亲疏程度",
    "kg.event_relation": "因果强度",
    "enrichment.rewrite": "【用户加料需求】",
}


async def _reset_stale_builtin_prompts(db: aiosqlite.Connection) -> int:
    """Refresh built-in templates whose user_prompt_template lacks a
    version marker. Returns the number of rows updated.
    """
    updated = 0
    for default in DEFAULT_PROMPTS:
        marker = _PROMPT_VERSION_MARKERS.get(default["key"])
        if not marker:
            continue
        cur = await db.execute(
            """
            SELECT id, user_prompt_template FROM prompt_templates
            WHERE key = ? AND is_builtin = 1
            """,
            (default["key"],),
        )
        row = await cur.fetchone()
        if not row:
            continue
        stored_template = row[1] or ""
        if marker in stored_template:
            continue
        await db.execute(
            """
            UPDATE prompt_templates SET
                name = ?,
                description = ?,
                system_prompt = ?,
                user_prompt_template = ?,
                temperature = ?,
                max_tokens = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                default["name"],
                default.get("description") or "",
                default.get("system_prompt", ""),
                default.get("user_prompt_template", ""),
                float(default.get("temperature", 0.3)),
                int(default.get("max_tokens", 2400)),
                row[0],
            ),
        )
        updated += 1
        logger.info(
            "Refreshed stale built-in prompt %s (missing marker %r)",
            default["key"],
            marker,
        )
    return updated


async def seed_default_prompts() -> None:
    """Insert default templates that are missing, on every startup.

    Behaviour:
    * If the table is empty (first run) — insert every default.
    * If the table already has rows — for each default that is **not
      present**, insert it. This covers the case where new default
      categories (e.g. ``enrichment.*``) are added in a later code
      release and need to be back-filled for existing installations.
    * Then refresh any built-in whose bundled content changed
      (detected via per-key version markers). User-customised prompts
      are left untouched.
    """
    async with get_db() as db:
        cur = await db.execute("SELECT COUNT(*) AS c FROM prompt_templates")
        row = await cur.fetchone()
        existing = row[0] if row else 0

        # 1) Collect keys that already exist
        cur = await db.execute("SELECT key FROM prompt_templates")
        existing_keys = {r[0] for r in await cur.fetchall()}

        # 2) Insert every default whose key is missing
        missing = [t for t in DEFAULT_PROMPTS if t["key"] not in existing_keys]
        for tmpl in missing:
            await db.execute(
                """
                INSERT INTO prompt_templates
                    (key, name, category, description, system_prompt,
                     user_prompt_template, temperature, max_tokens,
                     is_builtin, is_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                """,
                (
                    tmpl["key"],
                    tmpl["name"],
                    tmpl["category"],
                    tmpl.get("description") or "",
                    tmpl.get("system_prompt", ""),
                    tmpl.get("user_prompt_template", ""),
                    float(tmpl.get("temperature", 0.3)),
                    int(tmpl.get("max_tokens", 2400)),
                ),
            )

        if existing == 0:
            logger.info("Seeded %d default prompt templates", len(DEFAULT_PROMPTS))
        elif missing:
            logger.info(
                "Back-filled %d missing default prompt templates: %s",
                len(missing),
                ", ".join(t["key"] for t in missing),
            )

        # 3) Refresh any built-in whose bundled content has been updated
        refreshed = await _reset_stale_builtin_prompts(db)
        if missing or refreshed:
            await db.commit()


async def reseed_default_prompts() -> Dict[str, int]:
    """Force-insert every bundled default whose key is missing.

    Returns a small summary dict useful for the CLI helper. Existing
    rows (including user-edited built-ins) are never overwritten.
    """
    async with get_db() as db:
        cur = await db.execute("SELECT key FROM prompt_templates")
        existing_keys = {r[0] for r in await cur.fetchall()}
        inserted: List[str] = []
        for tmpl in DEFAULT_PROMPTS:
            if tmpl["key"] in existing_keys:
                continue
            await db.execute(
                """
                INSERT INTO prompt_templates
                    (key, name, category, description, system_prompt,
                     user_prompt_template, temperature, max_tokens,
                     is_builtin, is_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
                """,
                (
                    tmpl["key"],
                    tmpl["name"],
                    tmpl["category"],
                    tmpl.get("description") or "",
                    tmpl.get("system_prompt", ""),
                    tmpl.get("user_prompt_template", ""),
                    float(tmpl.get("temperature", 0.3)),
                    int(tmpl.get("max_tokens", 2400)),
                ),
            )
            inserted.append(tmpl["key"])
        await db.commit()
    return {
        "total_defaults": len(DEFAULT_PROMPTS),
        "inserted": len(inserted),
        "inserted_keys": inserted,
    }


def _row_to_dict(row) -> Dict[str, Any]:
    data = dict(row)
    return data


async def list_prompts(category: Optional[str] = None) -> List[Dict[str, Any]]:
    async with get_db() as db:
        if category:
            cur = await db.execute(
                """
                SELECT * FROM prompt_templates
                WHERE category = ?
                ORDER BY category, id
                """,
                (category,),
            )
        else:
            cur = await db.execute(
                "SELECT * FROM prompt_templates ORDER BY category, id"
            )
        rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]


async def get_prompt(prompt_id: int) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM prompt_templates WHERE id = ?", (prompt_id,)
        )
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def get_prompt_by_key(key: str) -> Optional[Dict[str, Any]]:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT * FROM prompt_templates WHERE key = ?", (key,)
        )
        row = await cur.fetchone()
        return _row_to_dict(row) if row else None


async def get_active_prompt_by_key(key: str) -> Optional[Dict[str, Any]]:
    """Return the prompt template if it is enabled, else None."""
    prompt = await get_prompt_by_key(key)
    if not prompt:
        return None
    if not int(prompt.get("is_enabled", 1)):
        return None
    return prompt


async def update_prompt(
    prompt_id: int,
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    system_prompt: Optional[str] = None,
    user_prompt_template: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    is_enabled: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    existing = await get_prompt(prompt_id)
    if not existing:
        return None

    fields: List[str] = []
    values: List[Any] = []
    if name is not None:
        fields.append("name = ?")
        values.append(name)
    if description is not None:
        fields.append("description = ?")
        values.append(description)
    if system_prompt is not None:
        fields.append("system_prompt = ?")
        values.append(system_prompt)
    if user_prompt_template is not None:
        fields.append("user_prompt_template = ?")
        values.append(user_prompt_template)
    if temperature is not None:
        fields.append("temperature = ?")
        values.append(float(temperature))
    if max_tokens is not None:
        fields.append("max_tokens = ?")
        values.append(int(max_tokens))
    if is_enabled is not None:
        fields.append("is_enabled = ?")
        values.append(int(bool(is_enabled)))
    if not fields:
        return existing
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(prompt_id)
    async with get_db() as db:
        await db.execute(
            f"UPDATE prompt_templates SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        await db.commit()
    return await get_prompt(prompt_id)


async def reset_prompt(prompt_id: int) -> Optional[Dict[str, Any]]:
    """Reset a built-in template to its bundled default value."""
    existing = await get_prompt(prompt_id)
    if not existing:
        return None
    default = next((d for d in DEFAULT_PROMPTS if d["key"] == existing["key"]), None)
    if not default:
        # User-created prompt without a default -> just clear overrides.
        async with get_db() as db:
            await db.execute(
                "UPDATE prompt_templates SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (prompt_id,),
            )
            await db.commit()
        return await get_prompt(prompt_id)
    async with get_db() as db:
        await db.execute(
            """
            UPDATE prompt_templates SET
                name = ?,
                description = ?,
                system_prompt = ?,
                user_prompt_template = ?,
                temperature = ?,
                max_tokens = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                default["name"],
                default.get("description") or "",
                default.get("system_prompt", ""),
                default.get("user_prompt_template", ""),
                float(default.get("temperature", 0.3)),
                int(default.get("max_tokens", 2400)),
                prompt_id,
            ),
        )
        await db.commit()
    return await get_prompt(prompt_id)


async def create_prompt(
    *,
    key: str,
    name: str,
    category: str,
    description: str = "",
    system_prompt: str = "",
    user_prompt_template: str = "",
    temperature: float = 0.3,
    max_tokens: int = 2400,
    is_enabled: bool = True,
) -> Dict[str, Any]:
    async with get_db() as db:
        cur = await db.execute(
            """
            INSERT INTO prompt_templates
                (key, name, category, description, system_prompt,
                 user_prompt_template, temperature, max_tokens,
                 is_builtin, is_enabled)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                key,
                name,
                category,
                description,
                system_prompt,
                user_prompt_template,
                float(temperature),
                int(max_tokens),
                1 if is_enabled else 0,
            ),
        )
        await db.commit()
        new_id = cur.lastrowid or 0
    prompt = await get_prompt(new_id)
    assert prompt is not None
    return prompt


async def delete_prompt(prompt_id: int) -> bool:
    async with get_db() as db:
        cur = await db.execute(
            "SELECT is_builtin FROM prompt_templates WHERE id = ?", (prompt_id,)
        )
        row = await cur.fetchone()
        if not row:
            return False
        if int(row[0] or 0):
            # Built-in prompts are protected from deletion.
            return False
        await db.execute("DELETE FROM prompt_templates WHERE id = ?", (prompt_id,))
        await db.commit()
    return True


def get_default_prompt(key: str) -> Optional[Dict[str, Any]]:
    """Return the bundled default template for a key (read-only)."""
    for tmpl in DEFAULT_PROMPTS:
        if tmpl["key"] == key:
            return dict(tmpl)
    return None
