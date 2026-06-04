"""Routes for image generation (text-to-image and image-to-image).

The implementation is provider-agnostic. It looks up a model config with
``capability = 'image'`` and POSTs to ``{model_url}/v1/image_generation``.
The protocol mirrors MiniMax's documentation, but the envelope is also
compatible with other OpenAI-style image APIs.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from schemas import (
    ImageGenerationRequest,
    ImageGenerationResponse,
    ImageModelSummary,
)
from services import (
    generate_images,
    get_config,
    list_enabled_image_configs,
    list_all_configs,
)
from services.image_service import (
    ImageGenerationError,
    upload_reference_image,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/image", tags=["ImageGeneration"])

ALLOWED_REFERENCE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
MAX_REFERENCE_BYTES = 10 * 1024 * 1024  # 10MB – same as MiniMax limit


@router.get("/models", response_model=List[ImageModelSummary])
async def list_image_models():
    """Return all image-capable model configurations (enabled or not)."""
    configs = await list_all_configs()
    return [
        ImageModelSummary(
            id=int(c["id"]),
            name=str(c.get("name") or ""),
            provider=str(c.get("provider") or ""),
            model_name=str(c.get("model_name") or ""),
            model_url=str(c.get("model_url") or ""),
        )
        for c in configs
        if (c.get("capability") or "chat") == "image"
    ]


@router.get("/models/enabled", response_model=List[ImageModelSummary])
async def list_enabled_image_models():
    """Return enabled image-capable models (used by the picker)."""
    configs = await list_enabled_image_configs()
    return [
        ImageModelSummary(
            id=int(c["id"]),
            name=str(c.get("name") or ""),
            provider=str(c.get("provider") or ""),
            model_name=str(c.get("model_name") or ""),
            model_url=str(c.get("model_url") or ""),
        )
        for c in configs
    ]


async def _resolve_image_config(model_config_id: int) -> Dict[str, Any]:
    cfg = await get_config(model_config_id)
    if not cfg:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    if int(cfg.get("enabled") or 0) != 1:
        raise HTTPException(status_code=400, detail="该模型配置已禁用")
    if (cfg.get("capability") or "chat") != "image":
        raise HTTPException(
            status_code=400, detail="该模型不是图像生成模型，请在模型配置中调整能力为「图像」"
        )
    return cfg


@router.post("/generate", response_model=ImageGenerationResponse)
async def generate_image(request: ImageGenerationRequest):
    """Run a text-to-image or image-to-image generation call.

    If ``subject_reference`` is non-empty, the request is treated as
    image-to-image; otherwise it is plain text-to-image.
    """
    if request.model_config_id is None:
        configs = await list_enabled_image_configs()
        if not configs:
            raise HTTPException(
                status_code=400,
                detail="尚未配置任何已启用的图像生成模型，请先在「系统设置 → 模型配置」中添加。",
            )
        cfg = configs[0]
    else:
        cfg = await _resolve_image_config(request.model_config_id)

    if not cfg.get("api_key") or not cfg.get("model_url") or not cfg.get("model_name"):
        raise HTTPException(status_code=400, detail="模型配置不完整，请检查 URL / API Key / 模型名称")

    try:
        result = await generate_images(
            provider=str(cfg.get("provider") or "minimax"),
            model_url=str(cfg["model_url"]),
            api_key=str(cfg["api_key"]),
            model_name=str(cfg["model_name"]),
            request=request,
        )
    except ImageGenerationError as exc:
        logger.warning("image generation failed: %s", exc)
        return ImageGenerationResponse(
            success=False,
            message=str(exc),
            model=str(cfg.get("model_name") or ""),
        )
    result.model = result.model or str(cfg.get("model_name") or "")
    return result


@router.post("/reference-upload")
async def upload_reference(file: UploadFile = File(...)):
    """Accept a reference image and return a data URI for ``subject_reference``."""
    content_type = (file.content_type or "image/jpeg").lower()
    if content_type not in ALLOWED_REFERENCE_MIME:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片类型: {content_type}，仅允许 jpg/jpeg/png/webp",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="上传的文件为空")
    if len(data) > MAX_REFERENCE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"图片过大 ({len(data)} 字节)，上限 10MB",
        )
    data_uri = await upload_reference_image(data, content_type=content_type)
    return {
        "data_uri": data_uri,
        "size": len(data),
        "content_type": content_type,
    }
