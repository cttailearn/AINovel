"""Routes for managing AI prompt templates.

Templates are kept in the ``prompt_templates`` table and seeded with the
default KG-extraction prompts on first run. Users can view and edit any
template from the settings UI; built-in templates may be reset back to
their bundled defaults.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from schemas import (
    PromptCategory,
    PromptListResponse,
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
)
from services import prompt_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompts", tags=["Prompts"])


def _serialize_prompt(p: Dict[str, Any]) -> PromptTemplateOut:
    return PromptTemplateOut(
        id=int(p["id"]),
        key=str(p["key"]),
        name=str(p.get("name") or ""),
        category=str(p.get("category") or ""),
        description=str(p.get("description") or ""),
        system_prompt=str(p.get("system_prompt") or ""),
        user_prompt_template=str(p.get("user_prompt_template") or ""),
        temperature=float(p.get("temperature") or 0.0),
        max_tokens=int(p.get("max_tokens") or 0),
        is_builtin=bool(int(p.get("is_builtin") or 0)),
        is_enabled=bool(int(p.get("is_enabled") or 0)),
        created_at=p.get("created_at"),
        updated_at=p.get("updated_at"),
    )


def _categories() -> List[PromptCategory]:
    return [
        PromptCategory(**cat) for cat in prompt_service.PROMPT_CATEGORIES
    ]


@router.get("", response_model=PromptListResponse)
async def list_prompts(
    category: Optional[str] = Query(
        default=None, description="按分类筛选 (connection / kg)"
    ),
):
    rows = await prompt_service.list_prompts(category=category)
    if category:
        return PromptListResponse(
            prompts=[_serialize_prompt(r) for r in rows],
            categories=_categories(),
        )
    return PromptListResponse(
        prompts=[_serialize_prompt(r) for r in rows],
        categories=_categories(),
    )


@router.get("/categories")
async def list_categories():
    return {"categories": _categories()}


@router.get("/{prompt_id}", response_model=PromptTemplateOut)
async def get_prompt(prompt_id: int):
    row = await prompt_service.get_prompt(prompt_id)
    if not row:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return _serialize_prompt(row)


@router.put("/{prompt_id}", response_model=PromptTemplateOut)
async def update_prompt(prompt_id: int, payload: PromptTemplateUpdate):
    try:
        updated = await prompt_service.update_prompt(
            prompt_id,
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            user_prompt_template=payload.user_prompt_template,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            is_enabled=int(payload.is_enabled) if payload.is_enabled is not None else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not updated:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return _serialize_prompt(updated)


@router.post("/reset/{prompt_id}", response_model=PromptTemplateOut)
async def reset_prompt(prompt_id: int):
    updated = await prompt_service.reset_prompt(prompt_id)
    if not updated:
        raise HTTPException(status_code=404, detail="提示词不存在")
    return _serialize_prompt(updated)


@router.post("", response_model=PromptTemplateOut, status_code=201)
async def create_prompt(payload: PromptTemplateCreate):
    try:
        created = await prompt_service.create_prompt(
            key=payload.key,
            name=payload.name,
            category=payload.category,
            description=payload.description,
            system_prompt=payload.system_prompt,
            user_prompt_template=payload.user_prompt_template,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            is_enabled=payload.is_enabled,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("create prompt failed: %s", exc)
        raise HTTPException(status_code=400, detail="创建失败：键名可能已存在")
    return _serialize_prompt(created)


@router.delete("/{prompt_id}")
async def delete_prompt(prompt_id: int):
    ok = await prompt_service.delete_prompt(prompt_id)
    if not ok:
        raise HTTPException(
            status_code=400, detail="提示词不存在或为内置模板，不可删除"
        )
    return {"message": f"提示词 {prompt_id} 已删除"}
