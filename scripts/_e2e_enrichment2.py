"""Second-stage E2E: insert fake model + run a single-chapter update and check export."""
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


def http(method, path, body=None):
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
    # 1. Insert a fake model + fake novel + fake chapter
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM chapter_enrichments WHERE novel_id = 9998")
        await db.execute("DELETE FROM chapters WHERE novel_id = 9998")
        await db.execute("DELETE FROM novels WHERE id = 9998")
        await db.execute("DELETE FROM model_configs WHERE id = 9998")
        await db.execute(
            """
            INSERT INTO model_configs
                (id, name, provider, model_url, api_key, model_name, capability, enabled)
            VALUES (9998, 'FakeModel', 'openai', 'http://127.0.0.1:1', 'sk-fake', 'fake', 'chat', 1)
            """
        )
        await db.execute(
            """
            INSERT INTO novels (id, title, author, filename, file_path, file_size, status, summary)
            VALUES (9998, '加料测试书', '未知作者', 'test.txt', '/tmp/test.txt', 100, 'parsed', 'summary')
            """
        )
        await db.execute(
            """
            INSERT INTO chapters (id, novel_id, chapter_number, title, content,
                                  start_position, end_position)
            VALUES (8001, 9998, 1, '第一章', '原文第一章内容', 0, 50),
                   (8002, 9998, 2, '第二章', '原文第二章内容', 50, 100)
            """
        )
        await db.commit()

    # 2. Test PUT /chapters/{id} 手动编辑
    print("\n--- 手动编辑 summary ---")
    http("PUT", "/enrichment/chapters/8001", {"summary": "这是一章的概要"})
    # 重新拉取
    http("GET", "/enrichment/chapters/8001")

    # 3. 验证 list_progress 反映状态
    print("\n--- 进度查询 ---")
    http("GET", "/enrichment/novels/9998/progress")

    # 4. 测试 export
    print("\n--- 导出 (没有 rewrite, 应回退原文) ---")
    req = urllib.request.Request(f"{API}/enrichment/novels/9998/export")
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8")
        print(f"export: status={r.status}, body[:400]=\n{body[:400]}")

    # 5. 测试 PUT 同时更新 rewrite + scene_tag
    print("\n--- 手动更新 rewrite + scene_tag ---")
    http("PUT", "/enrichment/chapters/8001", {
        "rewrite_text": "改写后的第一章",
        "scene_tag": "高燃战斗场景",
    })
    http("GET", "/enrichment/chapters/8001")
    http("GET", "/enrichment/novels/9998/progress")

    # 6. 测试 export 这次应包含改写内容
    print("\n--- 导出 (有改写) ---")
    req = urllib.request.Request(f"{API}/enrichment/novels/9998/export")
    with urllib.request.urlopen(req, timeout=20) as r:
        body = r.read().decode("utf-8")
        print(f"export: status={r.status}, body[:600]=\n{body[:600]}")

    # 7. reset
    print("\n--- 清空 ---")
    http("POST", "/enrichment/novels/9998/reset", None)
    http("GET", "/enrichment/chapters/8001")

    # 8. cleanup
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("DELETE FROM chapter_enrichments WHERE novel_id = 9998")
        await db.execute("DELETE FROM chapters WHERE novel_id = 9998")
        await db.execute("DELETE FROM novels WHERE id = 9998")
        await db.execute("DELETE FROM model_configs WHERE id = 9998")
        await db.commit()

    print("\n=== E2E STAGE 2 DONE ===")


asyncio.run(main())