from pydantic import BaseModel
from typing import Optional

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