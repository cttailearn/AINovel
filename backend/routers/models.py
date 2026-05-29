from fastapi import APIRouter, HTTPException
from schemas import ModelConfig, ConnectionTestRequest

from services.model_service import (
    list_all_configs, list_enabled_configs,
    create_model, update_model, toggle_model, delete_model
)
from services.ai_service import test_connection

router = APIRouter(prefix="/api/models", tags=["Models"])


@router.get("")
async def get_models():
    configs = await list_all_configs()
    return {"configs": configs}


@router.get("/enabled")
async def get_enabled_models():
    configs = await list_enabled_configs()
    return {"configs": configs}


@router.post("")
async def create_model_endpoint(config: ModelConfig):
    result = await create_model(config)
    return result


@router.put("/{id}")
async def update_model_endpoint(id: int, config: ModelConfig):
    result = await update_model(id, config)
    return result


@router.patch("/{id}/toggle")
async def toggle_model_endpoint(id: int, enabled: int):
    result = await toggle_model(id, enabled)
    return result


@router.delete("/{id}")
async def delete_model_endpoint(id: int):
    result = await delete_model(id)
    return result


@router.post("/test")
async def test_connection_endpoint(request: ConnectionTestRequest):
    return await test_connection(request)