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


class KnowledgeGraphEntity(BaseModel):
    id: str
    name: str
    attributes: Dict[str, Any] = {}


class KnowledgeGraphRelation(BaseModel):
    source: str
    relation: str
    target: str
    role: Optional[str] = None
    action: Optional[str] = None
    properties: Dict[str, Any] = {}


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

