from typing import List, Optional

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
