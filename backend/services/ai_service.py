import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from schemas import ConnectionTestRequest, ConnectionTestResponse

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 60.0
CHAT_TIMEOUT_SECONDS = 90.0
CONNECTION_TEST_PROMPT_KEY = "connection.test"


async def _resolve_connection_test_payload() -> Dict[str, Any]:
    """Return the user prompt + system prompt for the connection test.

    Falls back to ``{"system_prompt": "", "user_prompt": "hi"}`` if the
    template is disabled / missing in the database.
    """
    fallback = {"system_prompt": "", "user_prompt": "hi"}
    try:
        from services import prompt_service

        tmpl = await prompt_service.get_active_prompt_by_key(
            CONNECTION_TEST_PROMPT_KEY
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load connection test prompt: %s", exc)
        return fallback
    if not tmpl:
        return fallback
    return {
        "system_prompt": tmpl.get("system_prompt") or "",
        "user_prompt": tmpl.get("user_prompt_template") or fallback["user_prompt"],
    }


async def _send_probe(client: httpx.AsyncClient, request: ConnectionTestRequest) -> httpx.Response:
    headers = {
        "Authorization": f"Bearer {request.api_key}",
        "Content-Type": "application/json",
    }

    # Image generation models dispatch through the image_service provider
    # registry (MiniMax, DashScope, …). Each provider owns its own URL path
    # and request envelope.
    if (request.capability or "chat").lower() == "image":
        from services.image_service import build_probe_request

        endpoint, payload, _ = await build_probe_request(
            provider=request.provider or "minimax",
            model_url=request.model_url,
            model_name=request.model_name,
        )
        return await client.post(endpoint, headers=headers, json=payload)

    payload: Dict[str, Any] = {
        "model": request.model_name,
        "max_tokens": 1,
    }

    test_payload = await _resolve_connection_test_payload()
    system_prompt = test_payload["system_prompt"]
    user_prompt = test_payload["user_prompt"]

    if request.provider.lower() == "anthropic":
        return await client.post(
            f"{request.model_url.rstrip('/')}/v1/messages",
            headers={**headers, "anthropic-version": "2023-06-01"},
            json={
                **payload,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )

    if system_prompt:
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    else:
        messages = [{"role": "user", "content": user_prompt}]
    return await client.post(
        f"{request.model_url.rstrip('/')}/v1/chat/completions",
        headers=headers,
        json={
            **payload,
            "messages": messages,
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
        # For image models, also check the body for a non-success status.
        # MiniMax returns 200 with base_resp.status_code != 0 on quota /
        # safety issues; DashScope returns 200 with a top-level "code"
        # field. The image_service provider knows how to detect both.
        if (request.capability or "chat").lower() == "image":
            from services.image_service import parse_probe_response

            err = await parse_probe_response(
                request.provider or "minimax", response
            )
            if err:
                return ConnectionTestResponse(
                    success=False,
                    message=f"API 错误: {err}",
                    response_time=elapsed,
                )
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


class AIRequestError(RuntimeError):
    """Raised when the AI backend returns an unrecoverable error."""


def _extract_text_from_response(provider: str, payload: Dict[str, Any]) -> str:
    if not payload:
        return ""
    if provider.lower() == "anthropic":
        content = payload.get("content")
        if isinstance(content, list):
            parts: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return "\n".join(parts).strip()
        if isinstance(content, str):
            return content.strip()
        return ""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()


async def chat_completion(
    *,
    provider: str,
    model_url: str,
    api_key: str,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.4,
    max_tokens: int = 2048,
    timeout: float = CHAT_TIMEOUT_SECONDS,
    retries: int = 0,
    retry_base_delay: float = 1.0,
) -> str:
    """Call the LLM with optional retries on transient empty / network errors.

    ``retries=0`` keeps the original one-shot behaviour. Callers that
    can tolerate duplicate work (validator dedup/completeness) typically
    pass ``retries=2`` to absorb the occasional "AI 响应内容为空" from
    anthropic-protocol proxies that return thinking-only blocks.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    provider_key = (provider or "").lower()
    if provider_key == "anthropic":
        body: Dict[str, Any] = {
            "model": model_name,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        endpoint = f"{model_url.rstrip('/')}/v1/messages"
        request_headers = {**headers, "anthropic-version": "2023-06-01"}
    else:
        body = {
            "model": model_name,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        endpoint = f"{model_url.rstrip('/')}/v1/chat/completions"
        request_headers = headers

    last_exc: Optional[AIRequestError] = None
    for attempt in range(1, max(1, retries) + 2):  # attempts = retries + 1
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint, headers=request_headers, json=body
                )
        except httpx.TimeoutException as exc:
            last_exc = AIRequestError(f"AI 请求超时: {exc}")
        except httpx.HTTPError as exc:
            last_exc = AIRequestError(f"AI 网络错误: {exc}")
        else:
            if response.status_code >= 400:
                body_preview = response.text[:300] if response.content else ""
                last_exc = AIRequestError(
                    f"AI 返回 {response.status_code}: {body_preview}"
                )
            else:
                try:
                    payload = response.json()
                except json.JSONDecodeError as exc:
                    last_exc = AIRequestError("AI 响应不是有效的 JSON")
                else:
                    text = _extract_text_from_response(provider, payload)
                    if not text:
                        last_exc = AIRequestError("AI 响应内容为空")
                    else:
                        return text
        # 4xx errors are not retriable (they'll fail again); everything
        # else (timeout, network, 5xx, empty content) is worth retrying.
        if last_exc and "AI 返回 4" in last_exc.args[0]:
            break
        if attempt <= max(1, retries):
            import asyncio as _asyncio
            await _asyncio.sleep(retry_base_delay * (2 ** (attempt - 1)))
    assert last_exc is not None  # loop only exits via return or via last_exc
    raise last_exc


_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def parse_json_object(raw: str) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None
