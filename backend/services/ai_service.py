import httpx
import time
from schemas import ConnectionTestRequest, ConnectionTestResponse


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