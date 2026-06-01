import asyncio
import time
from typing import Any, Dict

import httpx

from schemas import ConnectionTestRequest, ConnectionTestResponse

REQUEST_TIMEOUT_SECONDS = 30.0


async def _send_probe(client: httpx.AsyncClient, request: ConnectionTestRequest) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {request.api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": request.model_name,
        "max_tokens": 1,
    }

    if request.provider.lower() == "anthropic":
        return await client.post(
            f"{request.model_url.rstrip('/')}/v1/messages",
            headers={**headers, "anthropic-version": "2023-06-01"},
            json={
                **payload,
                "system": "",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )

    return await client.post(
        f"{request.model_url.rstrip('/')}/v1/chat/completions",
        headers=headers,
        json={
            **payload,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )


async def test_connection(request: ConnectionTestRequest) -> ConnectionTestResponse:
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await _send_probe(client, request)
    except httpx.TimeoutException:
        return ConnectionTestResponse(success=False, message="连接超时")
    except httpx.HTTPError as exc:
        return ConnectionTestResponse(
            success=False, message=f"网络错误: {exc}"
        )
    except Exception as exc:  # noqa: BLE001
        return ConnectionTestResponse(
            success=False, message=f"连接失败: {exc}"
        )

    elapsed = round(time.monotonic() - start, 3)
    if response.status_code in (200, 201):
        return ConnectionTestResponse(
            success=True,
            message="连接成功",
            response_time=elapsed,
        )
    body_preview = response.text[:200] if response.content else ""
    return ConnectionTestResponse(
        success=False,
        message=f"API 返回 {response.status_code}: {body_preview}",
        response_time=elapsed,
    )
