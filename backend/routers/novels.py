from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from services.novel_service import (
    list_all_novels, get_novel_detail, upload_novel_file,
    update_novel_info, delete_novel, parse_chapters_by_rule,
    get_chapter, get_raw_content, parse_chapters_fixed_size
)
from database import update_novel_file_path
from config import NOVELS_DIR

router = APIRouter(prefix="/api/novels", tags=["Novels"])


@router.get("")
async def get_novels():
    novels = await list_all_novels()
    return {"novels": novels}


@router.post("/upload")
async def upload_novel(file: UploadFile = File(...)):
    if not file.filename.endswith('.txt'):
        raise HTTPException(status_code=400, detail="Only TXT files are supported")
    
    content = await file.read()
    file_size = len(content)
    
    filename = file.filename
    safe_filename = f"temp_{filename}"
    file_path = NOVELS_DIR / safe_filename
    
    with open(file_path, 'wb') as f:
        f.write(content)
    
    result = await upload_novel_file(file, str(file_path))
    
    import os
    os.remove(file_path)
    
    new_safe_filename = f"{result['id']}_{filename}"
    new_file_path = NOVELS_DIR / new_safe_filename
    with open(new_file_path, 'wb') as f:
        f.write(content)
    
    await update_novel_file_path(result['id'], str(new_file_path))
    
    return result


@router.get("/{novel_id}")
async def get_novel(novel_id: int):
    result = await get_novel_detail(novel_id)
    if not result:
        raise HTTPException(status_code=404, detail="Novel not found")
    return result


@router.put("/{novel_id}")
async def update_novel(novel_id: int, title: str = Form(None), author: str = Form(None)):
    result = await update_novel_info(novel_id, title, author)
    if not result:
        raise HTTPException(status_code=404, detail="Novel not found")
    return result


@router.delete("/{novel_id}")
async def delete_novel_endpoint(novel_id: int):
    result = await delete_novel(novel_id)
    if not result:
        raise HTTPException(status_code=404, detail="Novel not found")
    return result


@router.put("/{novel_id}/parse-rule")
async def set_parse_rule(novel_id: int, rule: str = Form(...)):
    from database import update_novel_parse_rule
    novel = await get_novel_detail(novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    await update_novel_parse_rule(novel_id, rule)
    return {"message": "规则已更新"}


@router.post("/{novel_id}/parse")
async def parse_chapters(novel_id: int, rule: str = Form(...)):
    result = await parse_chapters_by_rule(novel_id, rule)
    if result and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    if not result:
        raise HTTPException(status_code=404, detail="Novel not found")
    return result


@router.get("/{novel_id}/chapters/{chapter_id}")
async def get_chapter_endpoint(novel_id: int, chapter_id: int):
    result = await get_chapter(novel_id, chapter_id)
    if not result:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return result


@router.get("/{novel_id}/raw")
async def get_raw_content_endpoint(novel_id: int, chunk_size: int = 5000):
    result = await get_raw_content(novel_id, chunk_size)
    if not result:
        raise HTTPException(status_code=404, detail="Novel not found")
    if result and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/{novel_id}/parse-fixed")
async def parse_chapters_fixed(novel_id: int, chunk_size: int = Form(5000)):
    result = await parse_chapters_fixed_size(novel_id, chunk_size)
    if result and "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    if not result:
        raise HTTPException(status_code=404, detail="Novel not found")
    return result