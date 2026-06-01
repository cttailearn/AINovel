import logging
from typing import Any, Dict, List, Optional

from database import (
    delete_config_by_id,
    get_all_configs,
    get_config_by_id,
    get_enabled_configs,
    save_config,
    toggle_config_enabled,
    update_config,
)
from schemas import ModelConfig

logger = logging.getLogger(__name__)


async def list_all_configs() -> List[Dict[str, Any]]:
    return await get_all_configs()


async def list_enabled_configs() -> List[Dict[str, Any]]:
    return await get_enabled_configs()


async def get_config(config_id: int) -> Optional[Dict[str, Any]]:
    return await get_config_by_id(config_id)


async def create_model(config: ModelConfig) -> Dict[str, Any]:
    config_id = await save_config(
        config.name,
        config.provider,
        config.model_url,
        config.api_key,
        config.model_name,
        int(bool(config.enabled)),
    )
    return {
        "id": config_id,
        "message": f"Configuration '{config.name}' saved successfully",
    }


async def update_model(config_id: int, config: ModelConfig) -> Optional[Dict[str, Any]]:
    existing = await get_config_by_id(config_id)
    if not existing:
        return None
    await update_config(
        config_id,
        config.name,
        config.provider,
        config.model_url,
        config.api_key,
        config.model_name,
        int(bool(config.enabled)),
    )
    return {"message": f"Configuration '{config.name}' updated successfully"}


async def toggle_model(config_id: int, enabled: int) -> Optional[Dict[str, Any]]:
    existing = await get_config_by_id(config_id)
    if not existing:
        return None
    await toggle_config_enabled(config_id, 1 if int(enabled) else 0)
    return {"message": f"Configuration {config_id} {'enabled' if enabled else 'disabled'}"}


async def delete_model(config_id: int) -> bool:
    return await delete_config_by_id(config_id)
