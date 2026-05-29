from pydantic import BaseModel
from typing import Optional, List

class ModelConfig(BaseModel):
    name: str
    provider: str
    model_url: str
    api_key: str
    model_name: str
    enabled: int = 1

class ConnectionTestRequest(BaseModel):
    provider: str
    model_url: str
    api_key: str
    model_name: str

class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    response_time: Optional[float] = None

class NovelBase(BaseModel):
    title: str
    author: str = '未知作者'

class NovelInfo(BaseModel):
    id: int
    title: str
    author: str
    filename: str
    status: str
    chapter_count: int = 0
    parse_rule: Optional[str] = None
    created_at: str

class NovelDetail(NovelInfo):
    file_path: str
    file_size: int
    updated_at: str
    chapters: List[dict] = []

class ParseRuleRequest(BaseModel):
    rule: str

class ParseRuleResponse(BaseModel):
    success: bool
    message: str
    chapters_found: int = 0
    chapters: List[dict] = []

class ChapterInfo(BaseModel):
    id: int
    novel_id: int
    chapter_number: int
    title: str
    start_position: int
    end_position: int
    content: Optional[str] = None
    created_at: Optional[str] = None