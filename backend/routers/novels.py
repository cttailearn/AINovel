import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from config import (
    ALLOWED_NOVEL_EXT,
    DEFAULT_CHUNK_SIZE,
    MAX_UPLOAD_SIZE,
    NOVELS_DIR,
)
from schemas import (
    ChapterDetail,
    NovelDetail,
    NovelListResponse,
    NovelUpdate,
    NovelUploadResponse,
    ParseFixedRequest,
    ParsePreviewResponse,
    ParseResponse,
    ParseRuleRequest,
)
from services import (
    ParseError,
    delete_novel,
    get_chapter,
    get_novel_detail,
    get_raw_content,
    list_all_novels,
    parse_chapters_by_rule,
    parse_chapters_fixed_size,
    preview_chapters_by_rule,
    update_novel_info,
    upload_novel,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/novels", tags=["Novels"])


@router.get("", response_model=NovelListResponse)
async def get_novels():
    return {"novels": await list_all_novels()}


@router.post(
    "/upload",
    response_model=NovelUploadResponse,
    status_code=201,
)
async def upload_novel_endpoint(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名为空")

    safe_name = Path(file.filename).name
    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_NOVEL_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持以下文件格式: {', '.join(sorted(ALLOWED_NOVEL_EXT))}",
        )

    content = await file.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"文件超过 {MAX_UPLOAD_SIZE} 字节限制",
        )
    if not content:
        raise HTTPException(status_code=400, detail="文件内容为空")

    try:
        return await upload_novel(
            original_filename=safe_name, content=content
        )
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Upload failed: %s", exc)
        raise HTTPException(status_code=500, detail="上传失败，请稍后再试")


@router.get("/{novel_id}", response_model=NovelDetail)
async def get_novel(novel_id: int):
    novel = await get_novel_detail(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    return novel


@router.put("/{novel_id}")
async def update_novel(novel_id: int, payload: NovelUpdate):
    ok = await update_novel_info(novel_id, payload.title, payload.author)
    if not ok:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "小说信息已更新"}


@router.delete("/{novel_id}")
async def delete_novel_endpoint(novel_id: int):
    ok = await delete_novel(novel_id)
    if not ok:
        raise HTTPException(status_code=404, detail="小说不存在")
    return {"message": "小说已删除"}


@router.put("/{novel_id}/parse-rule")
async def set_parse_rule(novel_id: int, payload: ParseRuleRequest):
    novel = await get_novel_detail(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="小说不存在")
    from database import update_novel_parse_rule

    await update_novel_parse_rule(novel_id, payload.rule)
    return {"message": "规则已更新", "rule": payload.rule}


@router.post("/{novel_id}/parse", response_model=ParseResponse)
async def parse_chapters(novel_id: int, payload: ParseRuleRequest):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await parse_chapters_by_rule(novel_id, payload.rule)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/{novel_id}/parse-preview", response_model=ParsePreviewResponse
)
async def parse_preview(novel_id: int, payload: ParseRuleRequest):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await preview_chapters_by_rule(novel_id, payload.rule)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/{novel_id}/parse-fixed", response_model=ParseResponse
)
async def parse_fixed(novel_id: int, payload: ParseFixedRequest):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await parse_chapters_fixed_size(novel_id, payload.chunk_size)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get(
    "/{novel_id}/chapters/{chapter_id}", response_model=ChapterDetail
)
async def get_chapter_endpoint(novel_id: int, chapter_id: int):
    chapter = await get_chapter(novel_id, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="章节不存在")
    return chapter


@router.get("/{novel_id}/raw")
async def get_raw_content_endpoint(
    novel_id: int,
    chunk_size: int = Query(
        DEFAULT_CHUNK_SIZE, gt=0, le=100_000
    ),
):
    if not await get_novel_detail(novel_id):
        raise HTTPException(status_code=404, detail="小说不存在")
    try:
        return await get_raw_content(novel_id, chunk_size)
    except ParseError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
