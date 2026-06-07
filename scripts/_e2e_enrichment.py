"""End-to-end smoke test of the enrichment module.

Creates a temp novel with one chapter, then:
1. POST a single-chapter summary request (no model → expect 400 / not LLM called)
2. GET progress (should show pending for the new chapter)
3. GET the chapter detail (should be empty enrichment)
4. POST reset (should remove enrichment row)
"""
import sys
import json
import asyncio
import urllib.request
import urllib.error
from pathlib import Path

import aiosqlite

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from config import DATABASE_PATH

API = "http://127.0.0.1:18008/api"


def http(method, path, body=None, expect=None):
    url = f"{API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            payload = r.read().decode("utf-8")
            print(f"[{method} {path}] -> {r.status} {payload[:300]}")
            return r.status, json.loads(payload) if payload else None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"[{method} {path}] -> {e.code} {body[:300]}")
        return e.code, body


async def main():
    # 1. ensure no leftover enrichment
    http("POST", "/enrichment/novels/9999/reset", None)

    # 2. create a test novel directly via DB
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # 删旧数据
        await db.execute("DELETE FROM chapter_enrichments WHERE novel_id = 9999")
        await db.execute("DELETE FROM chapters WHERE novel_id = 9999")
        await db.execute("DELETE FROM novels WHERE id = 9999")
        await db.execute(
            """
            INSERT INTO novels (id, title, author, filename, file_path, file_size, status, summary)
            VALUES (9999, '测试加料', '未知作者', 'test.txt', '/tmp/test.txt', 100, 'parsed', 'summary')
            """
        )
        await db.execute(
            """
            INSERT INTO chapters (id, novel_id, chapter_number, title, content,
                                  start_position, end_position)
            VALUES (9001, 9999, 1, '第一章 测试', '一只敏捷的棕色狐狸从一只懒惰的狗身上跳过。', 0, 50),
                   (9002, 9999, 2, '第二章 测试', '第二次世界大战结束在 1945 年, 标志着历史新篇章。', 50, 100)
            """
        )
        await db.commit()

    # 3. GET progress
    http("GET", "/enrichment/novels/9999/progress")

    # 4. GET detail
    http("GET", "/enrichment/chapters/9001")

    # 5. POST summary with no model → should fail (value error)
    status, body = http(
        "POST",
        "/enrichment/chapters/9001/summary",
        {"model_config_id": 9999},
    )
    print(f"  -> model 9999 期望 400, 实际 {status}")

    # 6. POST reset on existing novel
    status, body = http("POST", "/enrichment/novels/9999/reset", None)
    print(f"  -> reset 期望 200, 实际 {status} body={body}")

    # 7. POST retry-failed on existing novel (no failures, should still 200)
    status, body = http("POST", "/enrichment/novels/9999/retry-failed", None)
    print(f"  -> retry-failed 期望 200, 实际 {status}")

    # 8. cleanup
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM chapter_enrichments WHERE novel_id = 9999")
        await db.execute("DELETE FROM chapters WHERE novel_id = 9999")
        await db.execute("DELETE FROM novels WHERE id = 9999")
        await db.commit()

    print("\n=== E2E DONE ===")


asyncio.run(main())