"""End-to-end smoke test against the running backend on port 8008."""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8008"


def request(path, method="GET", data=None, files=None):
    url = f"{BASE}{path}"
    headers = {}
    body = None
    if files:
        boundary = "----test-boundary"
        parts = []
        for name, (filename, content) in files.items():
            parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                "Content-Type: text/plain\r\n\r\n"
            )
            parts.append(content.decode("utf-8", "replace"))
            parts.append("\r\n")
        parts.append(f"--{boundary}--\r\n")
        body = "".join(parts).encode("utf-8")
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


SAMPLE = (
    "书名: 冒烟测试\n"
    "作者: Smoke Tester\n"
    "\n"
    "第一章 起点\n"
    "这是第一章的内容。\n"
    "\n"
    "第二章 发展\n"
    "故事继续。\n"
    "\n"
    "第三章 结局\n"
    "大结局。\n"
).encode("utf-8")


def expect(cond, msg, body=None):
    if not cond:
        print(f"  ❌ {msg}")
        if body is not None:
            print(f"     body: {json.dumps(body, ensure_ascii=False)[:300]}")
        sys.exit(1)
    print(f"  ✅ {msg}")


def main():
    print("== Smoke test ==")
    code, body = request("/api/health")
    expect(code == 200 and body.get("status") == "healthy", "/api/health OK")

    code, body = request("/api/models", method="POST", data={
        "name": "smoke",
        "provider": "openai",
        "model_url": "https://api.example.com",
        "api_key": "sk-smoke",
        "model_name": "gpt-4",
        "enabled": True,
    })
    expect(code == 201, "create model")
    model_id = body["id"]

    code, body = request("/api/models")
    expect(any(c["id"] == model_id for c in body["configs"]), "list contains model")

    code, body = request(f"/api/models/{model_id}", method="DELETE")
    expect(code == 200, "delete model")

    code, body = request(f"/api/models/99999", method="DELETE")
    expect(code == 404, "delete missing returns 404")

    code, body = request(
        "/api/novels/upload", method="POST", files={"file": ("smoke.txt", SAMPLE)}
    )
    expect(code == 201, "upload novel")
    novel_id = body["id"]
    expect(body["title"] == "冒烟测试", "title parsed from header")
    expect(body["author"] == "Smoke Tester", "author parsed from header")

    code, body = request(f"/api/novels/{novel_id}/parse", method="POST", data={"rule": r"^第.{1,5}章"})
    expect(code == 200 and body["success"], "parse by rule")
    expect(body["chapters_found"] == 3, "found 3 chapters")
    chapter_id = body["chapters"][1]["id"]

    code, body = request(f"/api/novels/{novel_id}/chapters/{chapter_id}")
    expect(code == 200 and "第二章" in body["title"], "get chapter content", body)

    code, body = request(
        f"/api/novels/{novel_id}/parse-preview", method="POST", data={"rule": r"^第.{1,5}章"}
    )
    expect(code == 200 and body["chapters_found"] == 3, "preview before commit")

    code, body = request(f"/api/novels/{novel_id}", method="PUT", data={"title": "新标题"})
    expect(code == 200, "update novel title")

    code, body = request(f"/api/novels/{novel_id}")
    expect(body["title"] == "新标题", "title updated")

    code, body = request(f"/api/novels/{novel_id}/parse-rule", method="PUT", data={"rule": r"^第\d+章"})
    expect(code == 200, "set parse rule")

    code, body = request(f"/api/novels/{novel_id}/parse-fixed", method="POST", data={"chunk_size": 50})
    expect(code == 200, "fixed-size parse")
    expect(body["chapters_found"] >= 1, "fixed-size found chunks")

    code, body = request(f"/api/novels/{novel_id}/raw", method="GET")
    expect(code == 200, "raw content")
    expect(isinstance(body.get("chunks"), list), "raw has chunks")

    code, body = request(f"/api/novels/{novel_id}", method="DELETE")
    expect(code == 200, "delete novel")

    code, body = request(f"/api/novels/{novel_id}")
    expect(code == 404, "deleted novel 404")

    code, body = request(
        "/api/novels/upload", method="POST", files={"file": ("bad.exe", b"x")}
    )
    expect(code == 400, "reject non-txt")

    code, body = request(
        "/api/novels/upload", method="POST", files={"file": ("empty.txt", b"")}
    )
    expect(code == 400, "reject empty")

    code, body = request(
        f"/api/novels/9999/parse", method="POST", data={"rule": r"^第\d+章"}
    )
    expect(code == 404, "parse missing novel 404")

    print("\n✅ All smoke tests passed")


if __name__ == "__main__":
    main()
