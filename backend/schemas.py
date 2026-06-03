from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ModelConfig(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    provider: str = Field(..., min_length=1, max_length=50)
    model_url: str = Field(..., min_length=1, max_length=500)
    api_key: str = Field(..., min_length=1, max_length=500)
    model_name: str = Field(..., min_length=1, max_length=200)
    enabled: bool = True


class ConnectionTestRequest(BaseModel):
    provider: str
    model_url: str
    api_key: str
    model_name: str


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

