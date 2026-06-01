from fastapi import APIRouter, HTTPException, Query

from schemas import ConnectionTestRequest, ModelConfig
from services import (
    create_model,
    delete_model,
    list_all_configs,
    list_enabled_configs,
    test_connection,
    toggle_model,
    update_model,
)

router = APIRouter(prefix="/api/models", tags=["Models"])


@router.get("")
async def get_models():
    return {"configs": await list_all_configs()}


@router.get("/enabled")
async def get_enabled_models():
    return {"configs": await list_enabled_configs()}


@router.post("", status_code=201)
async def create_model_endpoint(config: ModelConfig):
    return await create_model(config)


@router.put("/{config_id}")
async def update_model_endpoint(config_id: int, config: ModelConfig):
    result = await update_model(config_id, config)
    if not result:
        raise HTTPException(status_code=404, detail="Model config not found")
    return result


@router.patch("/{config_id}/toggle")
async def toggle_model_endpoint(
    config_id: int,
    enabled: int = Query(..., ge=0, le=1, description="1 to enable, 0 to disable"),
):
    result = await toggle_model(config_id, enabled)
    if not result:
        raise HTTPException(status_code=404, detail="Model config not found")
    return result


@router.delete("/{config_id}")
async def delete_model_endpoint(config_id: int):
    ok = await delete_model(config_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Model config not found")
    return {"message": f"Configuration {config_id} deleted"}


@router.post("/test")
async def test_connection_endpoint(request: ConnectionTestRequest):
    return await test_connection(request)
