"""End-to-end HTTP test against a running uvicorn server at 127.0.0.1:8008."""
import json
import sys
import time
import urllib.request
import urllib.error
from urllib.parse import urlencode

BASE = "http://127.0.0.1:8008/api"


def request(method, path, body=None, expect=200):
    url = f"{BASE}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            print(f"  {method} {path} -> {resp.status}")
            return resp.status, (json.loads(text) if text else None)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8")
        print(f"  {method} {path} -> {e.code}: {text[:200]}")
        return e.code, (json.loads(text) if text else None)


def main():
    print("=== E2E AI Creation HTTP test ===")
    print("[1] health")
    s, d = request("GET", "/health")
    assert s == 200 and d == {"status": "healthy"}

    print("[2] list projects (initial)")
    s, d = request("GET", "/creation/projects")
    assert s == 200
    initial = d.get("projects", [])
    print(f"    initial projects: {len(initial)}")

    print("[3] create project")
    s, d = request("POST", "/creation/projects", {
        "title": "E2E 测试项目",
        "genre": "玄幻",
        "worldview": "修仙界",
        "outline": "主角意外获得凤凰剑",
        "initial_concepts": [{"name": "张三", "attributes": {"性别": "男"}}],
        "style_pref": {"视角": "第三人称"},
    })
    assert s == 200
    pid = d["id"]
    print(f"    project_id={pid}")

    print("[4] get project")
    s, d = request("GET", f"/creation/projects/{pid}")
    assert s == 200
    assert d["project"]["id"] == pid
    assert d["kg_stats"] == {
        "characters": 0, "events": 0,
        "participations": 0, "character_relations": 0, "event_relations": 0,
    }

    print("[5] update project")
    s, d = request("PUT", f"/creation/projects/{pid}", {"outline": "更新后的总纲"})
    assert s == 200
    s, d = request("GET", f"/creation/projects/{pid}")
    assert d["project"]["outline"] == "更新后的总纲"

    print("[6] seed KG")
    s, d = request("POST", f"/creation/projects/{pid}/kg/seed")
    assert s == 200
    assert d.get("characters") == 1, f"got {d}"

    print("[7] get KG")
    s, d = request("GET", f"/creation/projects/{pid}/kg")
    assert s == 200
    assert len(d["characters"]) == 1
    assert d["characters"][0]["name"] == "张三"

    print("[8] list chapters (initial empty)")
    s, d = request("GET", f"/creation/projects/{pid}/chapters")
    assert s == 200
    assert d["chapters"] == []

    print("[9] delete project (cleanup)")
    s, d = request("DELETE", f"/creation/projects/{pid}")
    assert s == 200

    print("[10] verify deleted")
    s, d = request("GET", f"/creation/projects/{pid}")
    assert s == 404

    print("\n=== ALL E2E TESTS PASSED ===")


if __name__ == "__main__":
    main()
