import os
import re
from database import (
    save_novel, get_novel_by_id, get_all_novels, update_novel_title,
    update_novel_status, update_novel_parse_rule, delete_novel_by_id,
    save_chapter, get_chapters_by_novel, get_chapter_content, delete_chapters_by_novel,
    update_novel_file_path
)
from config import NOVELS_DIR, DEFAULT_CHUNK_SIZE


async def list_all_novels():
    return await get_all_novels()


async def get_novel_detail(novel_id: int):
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    
    chapters = await get_chapters_by_novel(novel_id)
    
    return {
        "id": novel['id'],
        "title": novel['title'],
        "author": novel['author'],
        "filename": novel['filename'],
        "file_path": novel['file_path'],
        "file_size": novel['file_size'],
        "status": novel['status'],
        "parse_rule": novel['parse_rule'],
        "chapter_count": len(chapters),
        "chapters": chapters,
        "created_at": novel['created_at'],
        "updated_at": novel['updated_at']
    }


async def upload_novel_file(file, file_path: str):
    content = await file.read()
    file_size = len(content)
    
    filename = file.filename
    title = os.path.splitext(filename)[0]
    author = '未知作者'
    
    novel_id = await save_novel(title, author, filename, file_path, file_size)
    
    try:
        lines = content.decode('utf-8').split('\n', 20)
        for line in lines[:20]:
            if line.strip():
                if '作者' in line or 'author' in line.lower():
                    parts = re.split(r'[:：]', line, 1)
                    if len(parts) > 1:
                        author = parts[1].strip()
                if '书名' in line or 'title' in line.lower():
                    parts2 = re.split(r'[:：]', line, 1)
                    if len(parts2) > 1:
                        title = parts2[1].strip()
    except:
        pass
    
    if title or author != '未知作者':
        await update_novel_title(novel_id, title, author)
    
    return {
        "id": novel_id,
        "title": title,
        "author": author,
        "filename": filename,
        "status": "pending",
        "message": "上传成功"
    }


async def update_novel_info(novel_id: int, title: str = None, author: str = None):
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    
    new_title = title if title else novel['title']
    new_author = author if author else novel['author']
    
    await update_novel_title(novel_id, new_title, new_author)
    return {"message": "小说信息已更新"}


async def delete_novel(novel_id: int):
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    
    if novel['file_path'] and os.path.exists(novel['file_path']):
        try:
            os.remove(novel['file_path'])
        except:
            pass
    
    await delete_novel_by_id(novel_id)
    return {"message": "小说已删除"}


async def parse_chapters_by_rule(novel_id: int, rule: str):
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    
    if not novel['file_path'] or not os.path.exists(novel['file_path']):
        return {"error": "Novel file not found"}
    
    try:
        with open(novel['file_path'], 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}
    
    await delete_chapters_by_novel(novel_id)
    
    try:
        pattern = re.compile(rule, re.MULTILINE)
        matches = list(pattern.finditer(content))
    except Exception as e:
        return {"error": f"Invalid regex pattern: {str(e)}"}
    
    if not matches:
        await update_novel_status(novel_id, 'pending')
        return {
            "success": False,
            "message": "未找到匹配的章节",
            "chapters_found": 0,
            "chapters": []
        }
    
    chapters = []
    for i, match in enumerate(matches):
        start_pos = match.start()
        title = match.group().strip()
        chapter_number = i + 1
        
        if i + 1 < len(matches):
            end_pos = matches[i + 1].start()
        else:
            end_pos = len(content)
        
        chapter_id = await save_chapter(novel_id, chapter_number, title, start_pos, end_pos)
        chapters.append({
            "id": chapter_id,
            "chapter_number": chapter_number,
            "title": title
        })
    
    await update_novel_status(novel_id, 'parsed')
    await update_novel_parse_rule(novel_id, rule)
    
    return {
        "success": True,
        "message": f"成功解析 {len(chapters)} 个章节",
        "chapters_found": len(chapters),
        "chapters": chapters
    }


async def get_chapter(novel_id: int, chapter_id: int):
    return await get_chapter_content(novel_id, chapter_id)


async def get_raw_content(novel_id: int, chunk_size: int = DEFAULT_CHUNK_SIZE):
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    
    if not novel['file_path'] or not os.path.exists(novel['file_path']):
        return {"error": "Novel file not found"}
    
    try:
        with open(novel['file_path'], 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}
    
    chunks = smart_chunk_content(content, chunk_size)
    
    return {
        "id": novel['id'],
        "title": novel['title'],
        "author": novel['author'],
        "status": novel['status'],
        "total_length": len(content),
        "chunks": chunks
    }


async def parse_chapters_fixed_size(novel_id: int, chunk_size: int):
    novel = await get_novel_by_id(novel_id)
    if not novel:
        return None
    
    if not novel['file_path'] or not os.path.exists(novel['file_path']):
        return {"error": "Novel file not found"}
    
    try:
        with open(novel['file_path'], 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        return {"error": f"Failed to read file: {str(e)}"}
    
    await delete_chapters_by_novel(novel_id)
    
    paragraphs = content.split('\n')
    chapters = []
    chapter_number = 0
    
    def find_punctuation_cut(text, start_pos, end_pos):
        for i in range(end_pos - 1, max(start_pos, end_pos - 200), -1):
            if text[i] in '。！？；，.!?,;':
                return i + 1
        return end_pos
    
    current_pos = 0
    chapter_content = []
    chapter_start_pos = 0
    
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        
        paragraph_length = len(paragraph)
        
        while paragraph_length > chunk_size:
            if chapter_content:
                text = '\n'.join(chapter_content)
                chapter_number += 1
                chapters.append({
                    "chapter_number": chapter_number,
                    "title": text[:30] + ('...' if len(text) > 30 else ''),
                    "start_position": chapter_start_pos,
                    "end_position": chapter_start_pos + len(text)
                })
                chapter_content = []
            
            cut_end = find_punctuation_cut(paragraph, 0, chunk_size)
            sub_text = paragraph[0:cut_end]
            chapter_number += 1
            sub_start = content.find(sub_text, current_pos)
            if sub_start < 0:
                sub_start = current_pos
            chapters.append({
                "chapter_number": chapter_number,
                "title": sub_text[:30] + ('...' if len(sub_text) > 30 else ''),
                "start_position": sub_start,
                "end_position": sub_start + len(sub_text)
            })
            
            current_pos += cut_end
            paragraph = paragraph[cut_end:]
            paragraph_length = len(paragraph)
        
        if chapter_content and (sum(len(p) for p in chapter_content) + paragraph_length > chunk_size):
            text = '\n'.join(chapter_content)
            chapter_number += 1
            chapter_start = content.find(text, chapter_start_pos)
            if chapter_start < 0:
                chapter_start = chapter_start_pos
            chapters.append({
                "chapter_number": chapter_number,
                "title": text[:30] + ('...' if len(text) > 30 else ''),
                "start_position": chapter_start,
                "end_position": chapter_start + len(text)
            })
            chapter_content = []
            chapter_start_pos = content.find(paragraph, current_pos)
            if chapter_start_pos < 0:
                chapter_start_pos = current_pos
        
        if not chapter_content and paragraph:
            chapter_start_pos = content.find(paragraph, current_pos)
            if chapter_start_pos < 0:
                chapter_start_pos = current_pos
        
        chapter_content.append(paragraph)
        current_pos = chapter_start_pos + len(paragraph)
    
    if chapter_content:
        text = '\n'.join(chapter_content)
        chapter_number += 1
        chapter_start = content.find(text, chapter_start_pos)
        if chapter_start < 0:
            chapter_start = chapter_start_pos
        chapters.append({
            "chapter_number": chapter_number,
            "title": text[:30] + ('...' if len(text) > 30 else ''),
            "start_position": chapter_start,
            "end_position": chapter_start + len(text)
        })
    
    for chapter in chapters:
        chapter_id = await save_chapter(
            novel_id, 
            chapter['chapter_number'], 
            chapter['title'], 
            chapter['start_position'], 
            chapter['end_position']
        )
        chapter['id'] = chapter_id
    
    await update_novel_status(novel_id, 'parsed')
    await update_novel_parse_rule(novel_id, f"fixed:{chunk_size}")
    
    return {
        "success": True,
        "message": f"成功解析 {len(chapters)} 个章节",
        "chapters_found": len(chapters),
        "chapters": [{"id": c['id'], "chapter_number": c['chapter_number'], "title": c['title']} for c in chapters]
    }


def smart_chunk_content(content: str, chunk_size: int = 5000) -> list:
    if len(content) <= chunk_size:
        return [{
            "chunk_number": 1,
            "title": content[:10] if len(content) >= 10 else content,
            "content": content
        }]
    
    paragraphs = content.split('\n')
    chunks = []
    current_chunk = ""
    current_length = 0
    chunk_number = 1
    
    for paragraph in paragraphs:
        paragraph_length = len(paragraph)
        
        if paragraph_length > chunk_size:
            if current_chunk:
                chunks.append({
                    "chunk_number": chunk_number,
                    "title": current_chunk[:10] if len(current_chunk) >= 10 else current_chunk,
                    "content": current_chunk.strip()
                })
                chunk_number += 1
                current_chunk = ""
                current_length = 0
            
            sub_chunks = []
            start = 0
            while start < paragraph_length:
                end = min(start + chunk_size, paragraph_length)
                if end < paragraph_length:
                    search_start = max(start, end - 200)
                    search_end = min(end + 200, paragraph_length)
                    punctuation_marks = ['。', '！', '？', '；', '，', '.', '!', '?', ';', ',']
                    best_cut = end
                    for i in range(search_start, search_end):
                        if paragraph[i] in punctuation_marks:
                            best_cut = i + 1
                            break
                    end = best_cut
                
                sub_chunk = paragraph[start:end].strip()
                if sub_chunk:
                    sub_chunks.append({
                        "chunk_number": chunk_number,
                        "title": sub_chunk[:10] if len(sub_chunk) >= 10 else sub_chunk,
                        "content": sub_chunk
                    })
                    chunk_number += 1
                start = end
            
            chunks.extend(sub_chunks)
            continue
        
        if current_length + paragraph_length > chunk_size and current_chunk:
            chunks.append({
                "chunk_number": chunk_number,
                "title": current_chunk[:10] if len(current_chunk) >= 10 else current_chunk,
                "content": current_chunk.strip()
            })
            chunk_number += 1
            current_chunk = paragraph
            current_length = paragraph_length
        else:
            if current_chunk:
                current_chunk += '\n' + paragraph
            else:
                current_chunk = paragraph
            current_length += paragraph_length
    
    if current_chunk.strip():
        chunks.append({
            "chunk_number": chunk_number,
            "title": current_chunk[:10] if len(current_chunk) >= 10 else current_chunk,
            "content": current_chunk.strip()
        })
    
    return chunks