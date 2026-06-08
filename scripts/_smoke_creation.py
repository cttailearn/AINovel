"""Smoke-test that the AI creation module imports and works.

This script does NOT use a temp DB — it works against the real DB.
It filters by a unique title prefix to avoid interference with other data.
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from database import (
    init_db, create_ai_project, list_ai_projects,
    create_ai_chapter, insert_ai_variant,
)
from services.creation_agents import (
    PlannerAgent, WriterAgent, CriticAgent, EntityExtractor,
    serialize_kg_for_prompt,
)
from services.creation_service import (
    list_projects, get_project_detail, create_project, update_project,
    delete_project, get_kg, seed_kg_from_concepts,
    list_chapters, get_chapter_detail, select_variant, update_chapter_content,
    confirm_chapter, _resolve_model_cfg, _ascii_word_count,
)


async def main():
    tag = f"smoke-{uuid.uuid4().hex[:8]}"
    title = f"测试项目-{tag}"

    print(f"[1] init_db (tag={tag})...")
    await init_db()
    print("    OK")

    print("[2] create_project via service...")
    pid = await create_project({
        "title": title, "genre": "玄幻",
        "worldview": "修仙", "outline": "主角奇遇",
        "initial_concepts": [{"name": "张三"}, {"name": "李四"}],
        "style_pref": {"视角": "第三人称"},
    })
    print(f"    project_id={pid}")

    print("[3] list_projects (filter by tag)...")
    projs = await list_projects()
    mine = [p for p in projs if p["title"] == title]
    assert len(mine) == 1, f"expected 1 mine, got {len(mine)}"
    print(f"    OK")

    print("[4] get_project_detail...")
    detail = await get_project_detail(pid)
    assert detail["project"]["title"] == title
    print(f"    chapters={len(detail['chapters'])}, kg_stats={detail['kg_stats']}")

    print("[5] seed_kg_from_concepts...")
    res = await seed_kg_from_concepts(pid)
    assert res["characters"] == 2
    kg = await get_kg(pid)
    assert len(kg["characters"]) == 2
    print(f"    OK, {len(kg['characters'])} characters")

    print("[6] serialize_kg_for_prompt...")
    txt = serialize_kg_for_prompt(kg)
    assert "张三" in txt and "李四" in txt
    print("    OK")

    print("[7] _ascii_word_count...")
    assert _ascii_word_count("") == 0
    assert _ascii_word_count("abc") == 3
    assert _ascii_word_count("你好") == 2
    assert _ascii_word_count("hi 你好") == 4
    print("    OK")

    print("[8] create chapter + variant...")
    ch_id = await create_ai_chapter(project_id=pid, chapter_no=1,
                                     title="第1章 测试", user_intent="开端")
    vid = await insert_ai_variant(
        chapter_id=ch_id, variant_index=0, planner_direction="方向A",
        content="这是测试章节的正文内容。" * 30, focus_summary="测试",
        critic_report={"overall": 8.0}, score=8.0,
    )
    print(f"    chapter_id={ch_id}, variant_id={vid}")

    print("[9] select_variant...")
    ch = await select_variant(ch_id, vid)
    assert ch["selected_variant_id"] == vid
    assert ch["final_content"]
    expected_wc = len("这是测试章节的正文内容。") * 30
    assert ch["word_count"] == expected_wc, f"{ch['word_count']} != {expected_wc}"
    print(f"    OK, word_count={ch['word_count']}")

    print("[10] update_chapter_content...")
    content2 = "用户编辑后的内容" * 10
    expected2 = len("用户编辑后的内容") * 10
    ch2 = await update_chapter_content(ch_id, content2)
    assert ch2["word_count"] == expected2
    print(f"    OK, word_count={ch2['word_count']}")

    print("[11] list_chapters...")
    chs = await list_chapters(pid)
    assert len(chs) == 1
    assert len(chs[0]["variants"]) == 1
    print(f"    OK, {len(chs)} chapter, {len(chs[0]['variants'])} variant(s)")

    print("[12] get_chapter_detail...")
    ch3 = await get_chapter_detail(ch_id)
    assert ch3["id"] == ch_id
    print("    OK")

    print("[13] cleanup: delete project...")
    ok = await delete_project(pid)
    assert ok
    projs2 = await list_projects()
    still_mine = [p for p in projs2 if p["title"] == title]
    assert len(still_mine) == 0
    print("    OK")

    print("\n=== ALL SMOKE TESTS PASSED ===")


if __name__ == "__main__":
    asyncio.run(main())
