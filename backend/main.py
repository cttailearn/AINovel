from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
import httpx
import time

from database import init_db, get_all_configs, get_enabled_configs, get_config_by_provider, save_config, update_config, toggle_config_enabled, delete_config_by_id
from schemas import ModelConfig, ConnectionTestRequest, ConnectionTestResponse

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api")
def read_root():
    return {"message": "Hello, World!"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.get("/api/models")
async def list_models():
    configs = await get_all_configs()
    return {"configs": configs}


@app.get("/api/models/enabled")
async def list_enabled_models():
    configs = await get_enabled_configs()
    return {"configs": configs}


@app.post("/api/models")
async def create_model(config: ModelConfig):
    await save_config(config.name, config.provider, config.model_url, config.api_key, config.model_name, config.enabled)
    return {"message": f"Configuration '{config.name}' saved successfully"}


@app.put("/api/models/{id}")
async def update_model(id: int, config: ModelConfig):
    await update_config(id, config.name, config.provider, config.model_url, config.api_key, config.model_name, config.enabled)
    return {"message": f"Configuration '{config.name}' updated successfully"}


@app.patch("/api/models/{id}/toggle")
async def toggle_model(id: int, enabled: int):
    await toggle_config_enabled(id, enabled)
    return {"message": f"Configuration {id} enabled status updated"}


@app.delete("/api/models/{id}")
async def delete_model_by_id(id: int):
    await delete_config_by_id(id)
    return {"message": f"Configuration {id} deleted successfully"}


@app.post("/api/models/test", response_model=ConnectionTestResponse)
async def test_connection(request: ConnectionTestRequest):
    start_time = time.time()
    
    headers = {
        "Authorization": f"Bearer {request.api_key}",
        "Content-Type": "application/json"
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if request.provider.lower() == "anthropic":
                response = await client.post(
                    f"{request.model_url}/v1/messages",
                    headers=headers,
                    json={
                        "model": request.model_name,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "Hi"}]
                    }
                )
            else:
                response = await client.post(
                    f"{request.model_url}/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": request.model_name,
                        "max_tokens": 1,
                        "messages": [{"role": "user", "content": "Hi"}]
                    }
                )
            
            elapsed_time = time.time() - start_time
            
            if response.status_code in [200, 201]:
                return ConnectionTestResponse(
                    success=True,
                    message="Connection successful",
                    response_time=round(elapsed_time, 3)
                )
            else:
                return ConnectionTestResponse(
                    success=False,
                    message=f"API error: {response.status_code}",
                    response_time=round(elapsed_time, 3)
                )
    except httpx.TimeoutException:
        return ConnectionTestResponse(
            success=False,
            message="Connection timeout"
        )
    except Exception as e:
        return ConnectionTestResponse(
            success=False,
            message=f"Connection failed: {str(e)}"
        )


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8008)