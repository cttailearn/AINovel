from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    provider: str = Field(..., min_length=1, max_length=50)
    model_url: str = Field(..., min_length=1, max_length=500)
    api_key: str = Field(..., min_length=1, max_length=500)
    model_name: str = Field(..., min_length=1, max_length=200)
    capability: Literal["chat", "image"] = "chat"
    enabled: bool = True


class ConnectionTestRequest(BaseModel):
    provider: str
    model_url: str
    api_key: str
    model_name: str
    capability: Literal["chat", "image"] = "chat"


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    response_time: Optional[float] = None


class NovelUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    author: Optional[str] = Field(default=None, max_length=200)


class ParseRuleRequest(BaseModel):
    rule: str = Field(..., min_length=1, max_length=500)


class ParseFixedRequest(BaseModel):
    chunk_size: int = Field(default=5000, gt=0, le=100_000)


class ChapterBase(BaseModel):
    chapter_number: int
    title: str
    start_position: int
    end_position: int


class ChapterOut(ChapterBase):
    id: int
    novel_id: int
    created_at: Optional[str] = None


class ChapterDetail(ChapterOut):
    content: Optional[str] = None


class ChapterUpdate(BaseModel):
    """章节更新请求体,所有字段可选,仅修改传入的项."""

    title: Optional[str] = Field(default=None, max_length=500)
    content: Optional[str] = None


class ChapterPreview(ChapterBase):
    pass


class NovelSummary(BaseModel):
    id: int
    title: str
    author: str
    filename: str
    status: str
    chapter_count: int = 0
    parse_rule: Optional[str] = None
    summary: Optional[str] = None
    created_at: str


class NovelDetail(NovelSummary):
    file_path: str
    file_size: int
    updated_at: str
    chapters: List[ChapterOut] = []


class ParseResponse(BaseModel):
    success: bool
    message: str
    chapters_found: int = 0
    chapters: List[ChapterOut] = []


class ParsePreviewResponse(BaseModel):
    chapters_found: int
    preview: List[ChapterPreview]


class NovelUploadResponse(BaseModel):
    id: int
    title: str
    author: str
    filename: str
    status: str
    message: str


class NovelListResponse(BaseModel):
    novels: List[NovelSummary]


class ModelListResponse(BaseModel):
    configs: List[dict]


class ErrorResponse(BaseModel):
    detail: str


# ---------------------------------------------------------------------------
# Prompt template management
# ---------------------------------------------------------------------------


class PromptCategory(BaseModel):
    key: str
    label: str
    description: str = ""


class PromptTemplateBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    system_prompt: str = Field(default="")
    user_prompt_template: str = Field(default="")
    temperature: float = Field(default=0.3, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2400, ge=1, le=128_000)
    is_enabled: bool = True


class PromptTemplateOut(BaseModel):
    id: int
    key: str
    name: str
    category: str
    description: str = ""
    system_prompt: str = ""
    user_prompt_template: str = ""
    temperature: float
    max_tokens: int
    is_builtin: bool
    is_enabled: bool
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    system_prompt: Optional[str] = None
    user_prompt_template: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=128_000)
    is_enabled: Optional[bool] = None


class PromptTemplateCreate(PromptTemplateBase):
    key: str = Field(..., min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=50)


class PromptListResponse(BaseModel):
    prompts: List[PromptTemplateOut]
    categories: List[PromptCategory]


class CharacterExtractionRequest(BaseModel):
    model_config_id: Optional[int] = Field(default=None, ge=1)
    max_chars: int = Field(default=8000, ge=1000, le=120_000)
    max_characters: int = Field(default=20, ge=1, le=100)


class Character(BaseModel):
    name: str
    role: Optional[str] = None
    aliases: List[str] = []
    description: Optional[str] = None
    first_appearance: Optional[int] = None


class CharacterExtractionResponse(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None
    characters: List[Character] = []


# ---------------------------------------------------------------------------
# Knowledge graph
# ---------------------------------------------------------------------------


class KnowledgeGraphRequest(BaseModel):
    model_config_id: Optional[int] = Field(default=None, ge=1)
    chunk_size: int = Field(default=8000, ge=1000, le=120_000)
    max_concurrency: int = Field(default=3, ge=1, le=10)
    # Multi-agent (v2) knobs. Only honoured by /knowledge-graph/v2.
    run_validator: bool = True
    run_llm_dedup: bool = True
    run_llm_completeness: bool = False


class EvidenceSpanOut(BaseModel):
    """原文引用 span, 支持前端跳转 + 高亮.

    字段语义:
    * ``chunk_id`` 对应 chunk_novel 输出的 chunk 标识.
    * ``quote`` 是原文片段 (30~200 字符), 找不到位置时仍可作为提示.
    * ``start`` / ``end`` 是 quote 在 chunk 文本内的字符 offset, 找不到时为 None.
    * ``strategy``:
        - ``"anchor"`` 基于实体名/属性锚点定位, 高置信;
        - ``"head"`` 段首兜底, 中等;
        - ``"fallback"`` 找不到, 仅作提示.
    * ``sentence_idx`` 句子索引, 用于"跳到第 N 句"级别的快速跳转.
    """
    chunk_id: str = ""
    quote: str = ""
    start: Optional[int] = None
    end: Optional[int] = None
    strategy: str = "anchor"
    sentence_idx: Optional[int] = None


class EntityExtras(BaseModel):
    """人物/事件实体的 evidence + confidence + 抽取上下文.

    前端"原文引用"面板: 遍历 ``evidence`` 列表, 逐条定位 + 高亮.
    """
    evidence: List[EvidenceSpanOut] = []
    confidence: Optional[float] = None
    chunk_id: Optional[str] = None
    # 自由扩展位, 例如: 模型版本、抽取时间、反馈重抽标记等.
    extra: Dict[str, Any] = {}


class KnowledgeGraphEntity(BaseModel):
    id: str
    name: str
    attributes: Dict[str, Any] = {}
    extras: EntityExtras = EntityExtras()


class KnowledgeGraphRelation(BaseModel):
    source: str
    relation: str
    target: str
    role: Optional[str] = None
    action: Optional[str] = None
    properties: Dict[str, Any] = {}
    # 关系的 evidence 通常是两端实体的 span 合并, 前端跳转时逐条渲染.
    extras: EntityExtras = EntityExtras()


class KnowledgeGraphStats(BaseModel):
    characters: int = 0
    events: int = 0
    participations: int = 0
    character_relations: int = 0
    event_relations: int = 0
    chunks_processed: int = 0


class ValidationIssueOut(BaseModel):
    """One issue raised by the MergeValidatorAgent (v2)."""

    severity: str
    code: str
    message: str
    payload: Dict[str, Any] = {}


class KnowledgeGraphValidation(BaseModel):
    """Validation report from the v2 multi-agent pipeline."""

    issues: List[ValidationIssueOut] = []
    dedup_log: List[Dict[str, Any]] = []
    coverage: Dict[str, Any] = {}


class KnowledgeGraphResponse(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None
    chunks_processed: int = 0
    characters: List[KnowledgeGraphEntity] = []
    events: List[KnowledgeGraphEntity] = []
    character_event_relations: List[KnowledgeGraphRelation] = []
    character_relations: List[KnowledgeGraphRelation] = []
    event_relations: List[KnowledgeGraphRelation] = []
    stats: KnowledgeGraphStats = KnowledgeGraphStats()
    # Populated only by the v2 endpoint. ``None`` for the legacy endpoint.
    validation: Optional[KnowledgeGraphValidation] = None


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------


class ImageSubjectReference(BaseModel):
    """Person subject reference for image-to-image (MiniMax)."""

    type: Literal["character"] = "character"
    image_file: str = Field(
        ...,
        description=(
            "参考图 URL 或 base64 data URI (data:image/jpeg;base64,...)"
        ),
    )


class ImageStyle(BaseModel):
    """Optional style hint, only honoured by image-01-live."""

    style_type: Optional[Literal["漫画", "元气", "中世纪", "水彩"]] = None
    style_weight: Optional[float] = Field(default=None, gt=0.0, le=1.0)


class ImageGenerationRequest(BaseModel):
    model_config_id: Optional[int] = Field(default=None, ge=1)
    prompt: str = Field(..., min_length=1, max_length=1500)
    negative_prompt: Optional[str] = Field(default=None, max_length=1500)
    # 图生图参考 (MiniMax subject_reference / DashScope content[].image)
    subject_reference: List[ImageSubjectReference] = []
    style: Optional[ImageStyle] = None
    aspect_ratio: Optional[str] = Field(
        default="1:1",
        description=(
            "1:1, 16:9, 4:3, 3:2, 2:3, 3:4, 9:16, 21:9 (21:9 仅 image-01)"
        ),
    )
    width: Optional[int] = Field(default=None, ge=512, le=2048)
    height: Optional[int] = Field(default=None, ge=512, le=2048)
    response_format: Literal["url", "base64"] = "url"
    seed: Optional[int] = None
    n: int = Field(default=1, ge=1, le=9)
    prompt_optimizer: bool = False
    aigc_watermark: bool = False


class ImageGenerationItem(BaseModel):
    url: Optional[str] = None
    b64: Optional[str] = None


class ImageGenerationResponse(BaseModel):
    success: bool
    message: str
    model: Optional[str] = None
    task_id: Optional[str] = None
    images: List[ImageGenerationItem] = []
    success_count: int = 0
    failed_count: int = 0


class ImageModelSummary(BaseModel):
    id: int
    name: str
    provider: str
    model_name: str
    model_url: str


# ---------------------------------------------------------------------------
# Novel enrichment (小说加料)
# ---------------------------------------------------------------------------


# 步骤名常量, 与 chapter_enrichments 表的 *_status 列一一对应
ENRICHMENT_STEPS = ("summary", "recognition", "rewrite")
ENRICHMENT_STEP_LABELS = {
    "summary": "内容总结",
    "recognition": "识别待处理",
    "rewrite": "AI 改写",
}


class EnrichmentRunRequest(BaseModel):
    """单章单步执行的请求体.

    至少需要 ``model_config_id`` 用于选择 LLM; ``prompt_key`` 缺省时
    按步骤名取内置模板 (``enrichment.summary/recognition/rewrite``).
    """

    model_config_id: int = Field(..., ge=1)
    prompt_key: Optional[str] = Field(default=None, max_length=100)
    override_prompt: Optional[str] = Field(default=None, max_length=20000)
    # 仅 rewrite 步骤有效: 从「改写规则」分类下挑选的规则子模板
    general_rule: Optional[str] = Field(default=None, max_length=20000)
    scene_rule: Optional[str] = Field(default=None, max_length=20000)


class EnrichmentUpdateRequest(BaseModel):
    """手动编辑某个字段 (summary / recognition / rewrite_text)."""

    summary: Optional[str] = Field(default=None, max_length=20000)
    rewrite_text: Optional[str] = Field(default=None, max_length=200000)
    scene_tag: Optional[str] = Field(default=None, max_length=100)


class EnrichmentBatchRequest(BaseModel):
    """整本批量处理请求体 (SSE 入口)."""

    model_config_id: int = Field(..., ge=1)
    steps: List[str] = Field(
        default_factory=lambda: list(ENRICHMENT_STEPS),
        description="要执行的步骤, 任意顺序; 默认全跑 summary+recognition+rewrite",
    )
    chapter_ids: Optional[List[int]] = Field(
        default=None,
        description="仅跑这些章节, 留空跑全部",
    )
    concurrency: int = Field(default=2, ge=1, le=10)
    skip_existing: bool = Field(
        default=True,
        description="若为 true, 已 done 的步骤会被跳过",
    )
    # 仅 rewrite 步骤生效, 与单章请求体一致
    general_rule: Optional[str] = Field(default=None, max_length=20000)
    scene_rule: Optional[str] = Field(default=None, max_length=20000)


class EnrichmentProgressItem(BaseModel):
    """单章节的三态进度, 配合 chapters 表一起返回."""

    chapter_id: int
    novel_id: int
    chapter_number: int
    title: str
    word_count: int
    summary_status: str = "pending"
    recognition_status: str = "pending"
    rewrite_status: str = "pending"
    status: str = "pending"
    scene_tag: Optional[str] = None


class EnrichmentProgressResponse(BaseModel):
    novel_id: int
    total: int
    summary_done: int = 0
    recognition_done: int = 0
    rewrite_done: int = 0
    summary_failed: int = 0
    recognition_failed: int = 0
    rewrite_failed: int = 0
    # 1.0 = summary+recognition+rewrite 全部 done
    overall_percent: float = 0.0
    items: List[EnrichmentProgressItem] = []


class EnrichmentDetailResponse(BaseModel):
    chapter_id: int
    novel_id: int
    chapter_number: int
    title: str
    word_count: int
    content: str = ""
    summary: Optional[str] = None
    summary_status: str = "pending"
    summary_error: Optional[str] = None
    summary_model_id: Optional[int] = None
    recognition: Dict[str, Any] = {}
    recognition_status: str = "pending"
    recognition_error: Optional[str] = None
    recognition_model_id: Optional[int] = None
    rewrite_text: Optional[str] = None
    rewrite_status: str = "pending"
    rewrite_error: Optional[str] = None
    rewrite_model_id: Optional[int] = None
    scene_tag: Optional[str] = None
    status: str = "pending"
    error: Optional[str] = None
    updated_at: Optional[str] = None


class EnrichmentRunResponse(BaseModel):
    """单章单步执行的结果."""

    success: bool
    status: str
    message: str
    chapter_id: int
    step: str
    duration_ms: int = 0
    model_id: Optional[int] = None
    # 简单回传识别结果, 方便单步重跑后立刻看到
    summary: Optional[str] = None
    recognition: Optional[Dict[str, Any]] = None
    rewrite_text: Optional[str] = None
    scene_tag: Optional[str] = None


class EnrichmentResetResponse(BaseModel):
    novel_id: int
    deleted: int
    message: str = "已清空加料结果"

