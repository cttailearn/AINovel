from pydantic import BaseModel, Field
from typing import Optional

class ModelConfig(BaseModel):
    provider: str = Field(..., pattern="^(anthropic|openai)$")
    model_url: str
    api_key: str
    model_name: str

class ConnectionTestRequest(BaseModel):
    provider: str = Field(..., pattern="^(anthropic|openai)$")
    model_url: str
    api_key: str
    model_name: str

class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    response_time: Optional[float] = None