from database import (
    get_all_configs, get_enabled_configs,
    save_config, update_config, toggle_config_enabled, delete_config_by_id
)
from schemas import ModelConfig


async def list_all_configs():
    return await get_all_configs()


async def list_enabled_configs():
    return await get_enabled_configs()


async def create_model(config: ModelConfig):
    await save_config(
        config.name, config.provider, config.model_url, 
        config.api_key, config.model_name, config.enabled
    )
    return {"message": f"Configuration '{config.name}' saved successfully"}


async def update_model(id: int, config: ModelConfig):
    await update_config(
        id, config.name, config.provider, config.model_url,
        config.api_key, config.model_name, config.enabled
    )
    return {"message": f"Configuration '{config.name}' updated successfully"}


async def toggle_model(id: int, enabled: int):
    await toggle_config_enabled(id, enabled)
    return {"message": f"Configuration {id} enabled status updated"}


async def delete_model(id: int):
    await delete_config_by_id(id)
    return {"message": f"Configuration {id} deleted successfully"}