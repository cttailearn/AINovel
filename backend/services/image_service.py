"""Image generation service.

Supports multiple image providers behind a single async function. Each
provider encapsulates its own request envelope and response parser so the
caller (router / frontend) doesn't need to know the API shape.

Currently implemented:
    - ``minimax``  : MiniMax / MiniMax image-01 / image-01-live
    - ``dashscope``: Alibaba Cloud DashScope multimodal-generation
                     (e.g. qwen-image-2.0-pro)

Providers are looked up by name from ``PROVIDERS``. The router passes the
provider identifier from the stored model config.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from config import IMAGE_CACHE_DIR
from schemas import (
    ImageGenerationItem,
    ImageGenerationRequest,
    ImageGenerationResponse,
)
from services.metrics_service import record_image_call

logger = logging.getLogger(__name__)

IMAGE_TIMEOUT_SECONDS = 180.0


class ImageGenerationError(RuntimeError):
    """Raised when the image generation backend reports an unrecoverable error."""


# ---------------------------------------------------------------------------
# Provider protocol
# ---------------------------------------------------------------------------


class ImageProvider(Protocol):
    """Minimal contract every image provider implementation must satisfy."""

    name: str

    def build_endpoint(self, model_url: str) -> str: ...

    def build_payload(
        self, request: ImageGenerationRequest, model_name: str
    ) -> Dict[str, Any]: ...

    def parse_response(
        self, body: Dict[str, Any], model_name: str
    ) -> ImageGenerationResponse: ...

    def probe_payload(
        self, model_name: str
    ) -> Dict[str, Any]: ...

    def is_error_response(self, body: Dict[str, Any]) -> Optional[str]:
        """Return an error message if the body signals a failure, else None."""
        ...


# ---------------------------------------------------------------------------
# MiniMax
# ---------------------------------------------------------------------------


class MiniMaxProvider:
    name = "minimax"

    def build_endpoint(self, model_url: str) -> str:
        return f"{model_url.rstrip('/')}/v1/image_generation"

    def build_payload(
        self, request: ImageGenerationRequest, model_name: str
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": model_name,
            "prompt": request.prompt,
        }
        if request.subject_reference:
            payload["subject_reference"] = [
                ref.model_dump() for ref in request.subject_reference
            ]
        if request.style and request.style.style_type:
            payload["style"] = request.style.model_dump(exclude_none=True)
        if request.aspect_ratio:
            payload["aspect_ratio"] = request.aspect_ratio
        if request.width is not None:
            payload["width"] = request.width
        if request.height is not None:
            payload["height"] = request.height
        payload["response_format"] = request.response_format
        if request.seed is not None:
            payload["seed"] = request.seed
        payload["n"] = request.n
        payload["prompt_optimizer"] = request.prompt_optimizer
        payload["aigc_watermark"] = request.aigc_watermark
        return payload

    def probe_payload(self, model_name: str) -> Dict[str, Any]:
        return {
            "model": model_name,
            "prompt": "ping",
            "n": 1,
            "aspect_ratio": "1:1",
            "response_format": "url",
        }

    def is_error_response(self, body: Dict[str, Any]) -> Optional[str]:
        base = body.get("base_resp") or {}
        code = int(base.get("status_code", 0))
        if code != 0:
            return str(base.get("status_msg") or "unknown")
        return None

    def parse_response(
        self, body: Dict[str, Any], model_name: str
    ) -> ImageGenerationResponse:
        images = _extract_minimax_images(body)
        success, failed = _extract_minimax_counts(body, len(images))
        return ImageGenerationResponse(
            success=True,
            message="生成成功",
            model=model_name,
            task_id=body.get("id"),
            images=images,
            success_count=success or len(images),
            failed_count=failed,
        )


def _extract_minimax_images(body: Dict[str, Any]) -> List[ImageGenerationItem]:
    data = body.get("data") or {}
    items: List[ImageGenerationItem] = []
    for url in data.get("image_urls") or []:
        if url:
            items.append(ImageGenerationItem(url=url, b64=None))
    for b64 in data.get("image_base64") or []:
        if b64:
            items.append(ImageGenerationItem(url=None, b64=b64))
    return items


def _extract_minimax_counts(
    body: Dict[str, Any], fallback_success: int
) -> Tuple[int, int]:
    meta = body.get("metadata") or {}
    try:
        success = int(meta.get("success_count") or fallback_success)
    except (TypeError, ValueError):
        success = fallback_success
    try:
        failed = int(meta.get("failed_count") or 0)
    except (TypeError, ValueError):
        failed = 0
    return success, failed


# ---------------------------------------------------------------------------
# DashScope (Alibaba Cloud)
# ---------------------------------------------------------------------------


class DashScopeProvider:
    """Alibaba Cloud DashScope multimodal-generation API.

    Reference request body::

        {
          "model": "qwen-image-2.0-pro",
          "input": {
            "messages": [{
              "role": "user",
              "content": [
                {"image": "https://..."},
                {"text": "图1中的女生穿着图2中的黑色裙子坐下"}
              ]
            }]
          },
          "parameters": {
            "n": 2,
            "negative_prompt": "",
            "watermark": false
          }
        }

    Response::

        {
          "output": {
            "choices": [{
              "finish_reason": "stop",
              "message": {
                "role": "assistant",
                "content": [{"image": "https://..."}]
              }
            }]
          },
          "usage": {"image_count": 1},
          "request_id": "..."
        }
    """

    name = "dashscope"

    def build_endpoint(self, model_url: str) -> str:
        return (
            f"{model_url.rstrip('/')}"
            "/api/v1/services/aigc/multimodal-generation/generation"
        )

    def build_payload(
        self, request: ImageGenerationRequest, model_name: str
    ) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = []
        # DashScope mixes reference images and the prompt in a single content
        # array, preserving order. We push images first then the prompt text.
        for ref in request.subject_reference:
            if ref.image_file:
                content.append({"image": ref.image_file})
        content.append({"text": request.prompt})
        if request.negative_prompt:
            # DashScope's negative_prompt lives in parameters, not the user
            # message, so we don't push it into content here.
            pass
        payload: Dict[str, Any] = {
            "model": model_name,
            "input": {
                "messages": [
                    {"role": "user", "content": content}
                ]
            },
            "parameters": {
                "n": request.n,
                "watermark": bool(request.aigc_watermark),
            },
        }
        if request.negative_prompt:
            payload["parameters"]["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            payload["parameters"]["seed"] = request.seed
        return payload

    def probe_payload(self, model_name: str) -> Dict[str, Any]:
        return {
            "model": model_name,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [{"text": "ping"}],
                    }
                ]
            },
            "parameters": {"n": 1},
        }

    def is_error_response(self, body: Dict[str, Any]) -> Optional[str]:
        code = body.get("code")
        if code and code != "Success":
            return str(body.get("message") or code)
        return None

    def parse_response(
        self, body: Dict[str, Any], model_name: str
    ) -> ImageGenerationResponse:
        images = _extract_dashscope_images(body)
        usage = body.get("usage") or {}
        try:
            success = int(usage.get("image_count") or len(images))
        except (TypeError, ValueError):
            success = len(images)
        return ImageGenerationResponse(
            success=True,
            message="生成成功",
            model=model_name,
            task_id=body.get("request_id"),
            images=images,
            success_count=success or len(images),
            failed_count=0,
        )


def _extract_dashscope_images(body: Dict[str, Any]) -> List[ImageGenerationItem]:
    output = body.get("output") or {}
    choices = output.get("choices") or []
    items: List[ImageGenerationItem] = []
    for choice in choices:
        message = choice.get("message") or {}
        for part in message.get("content") or []:
            if not isinstance(part, dict):
                continue
            url = part.get("image")
            if url:
                items.append(ImageGenerationItem(url=url, b64=None))
    return items


# ---------------------------------------------------------------------------
# Registry & dispatch
# ---------------------------------------------------------------------------


PROVIDERS: Dict[str, ImageProvider] = {
    "minimax": MiniMaxProvider(),
    "dashscope": DashScopeProvider(),
}


def get_provider(name: str) -> ImageProvider:
    impl = PROVIDERS.get((name or "").lower())
    if not impl:
        raise ImageGenerationError(
            f"不支持的图像提供商: {name!r}。请在「系统设置 → 模型配置」中检查配置。"
        )
    return impl


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_images(
    *,
    provider: str,
    model_url: str,
    api_key: str,
    model_name: str,
    request: ImageGenerationRequest,
    timeout: float = IMAGE_TIMEOUT_SECONDS,
) -> ImageGenerationResponse:
    """Call the upstream image generation API and normalise the response."""
    import time

    started = time.monotonic()
    impl = get_provider(provider)
    endpoint = impl.build_endpoint(model_url)
    payload = impl.build_payload(request, model_name)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
    except httpx.TimeoutException as exc:
        record_image_call(provider, "timeout", time.monotonic() - started)
        raise ImageGenerationError(f"图像生成超时: {exc}") from exc
    except httpx.HTTPError as exc:
        record_image_call(provider, "network_error", time.monotonic() - started)
        raise ImageGenerationError(f"图像生成网络错误: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        record_image_call(provider, "exception", time.monotonic() - started)
        raise ImageGenerationError(f"图像生成失败: {exc}") from exc

    if response.status_code >= 400:
        body_preview = response.text[:300] if response.content else ""
        record_image_call(provider, "http_error", time.monotonic() - started)
        raise ImageGenerationError(
            f"API 返回 {response.status_code}: {body_preview}"
        )

    try:
        body: Dict[str, Any] = response.json()
    except Exception as exc:  # noqa: BLE001
        record_image_call(provider, "bad_json", time.monotonic() - started)
        raise ImageGenerationError(f"API 响应不是有效的 JSON: {exc}") from exc

    err = impl.is_error_response(body)
    if err:
        record_image_call(provider, "api_error", time.monotonic() - started)
        raise ImageGenerationError(f"API 错误: {err}")

    result = impl.parse_response(body, model_name)
    result = await cache_generated_images(result)
    record_image_call(provider, "success", time.monotonic() - started)
    return result


async def build_probe_request(
    *, provider: str, model_url: str, model_name: str
) -> Tuple[str, Dict[str, Any], Dict[str, str]]:
    """Build a tiny probe (URL + body + headers) for the connection test."""
    impl = get_provider(provider)
    endpoint = impl.build_endpoint(model_url)
    payload = impl.probe_payload(model_name)
    headers = {"Content-Type": "application/json"}
    return endpoint, payload, headers


async def parse_probe_response(
    provider: str, response: httpx.Response
) -> Optional[str]:
    """Return an error message if the probe response is a failure, else None."""
    if response.status_code >= 400:
        body_preview = response.text[:200] if response.content else ""
        return f"API 返回 {response.status_code}: {body_preview}"
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        return None
    impl = get_provider(provider)
    return impl.is_error_response(body)


async def upload_reference_image(
    file_bytes: bytes,
    *,
    content_type: str = "image/jpeg",
) -> str:
    """Convert an uploaded image to a data URI suitable for both providers.

    MiniMax and DashScope both accept ``data:image/...;base64,...`` URIs
    (DashScope also accepts hosted URLs), so we can reuse the same helper
    for both.
    """
    encoded = base64.b64encode(file_bytes).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _guess_extension(content_type: Optional[str], source_url: Optional[str] = None) -> str:
    if content_type:
        if "png" in content_type:
            return ".png"
        if "webp" in content_type:
            return ".webp"
        if "jpeg" in content_type or "jpg" in content_type:
            return ".jpg"
    if source_url:
        suffix = Path(urlparse(source_url).path).suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            return suffix
    return ".png"


async def cache_image_bytes(
    data: bytes,
    *,
    content_type: str = "image/png",
    source_name: Optional[str] = None,
) -> str:
    ext = _guess_extension(content_type, source_name)
    name = f"{uuid4().hex}{ext}"
    path = IMAGE_CACHE_DIR / name
    path.write_bytes(data)
    return name


async def cache_generated_images(
    response: ImageGenerationResponse,
) -> ImageGenerationResponse:
    cached_items: List[ImageGenerationItem] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for item in response.images or []:
            if item.b64:
                data = base64.b64decode(item.b64)
                filename = await cache_image_bytes(data, content_type="image/png")
                cached_items.append(
                    ImageGenerationItem(
                        url=f"/api/image/cache/{filename}",
                        b64=None,
                    )
                )
                continue
            if item.url and item.url.startswith(("http://", "https://")):
                try:
                    remote = await client.get(item.url)
                    if remote.status_code < 400 and remote.content:
                        filename = await cache_image_bytes(
                            remote.content,
                            content_type=remote.headers.get("content-type") or "image/png",
                            source_name=item.url,
                        )
                        cached_items.append(
                            ImageGenerationItem(
                                url=f"/api/image/cache/{filename}",
                                b64=None,
                            )
                        )
                        continue
                except Exception:
                    logger.warning("cache remote image failed: %s", item.url, exc_info=True)
            cached_items.append(ImageGenerationItem(url=item.url, b64=None))
    response.images = cached_items
    return response
