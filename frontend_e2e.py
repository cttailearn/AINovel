"""End-to-end smoke test through the Vite dev server."""
import json
import sys
import urllib.error
import urllib.request


def request(path, method="GET", data=None, files=None):
    url = f"http://127.0.0.1:5173{path}"
    headers = {}
    body = None
    if files:
        boundary = "----e2e"
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
        return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def expect(cond, msg, body=None):
    if not cond:
        print(f"  FAIL: {msg}", flush=True)
        if body is not None:
            print(f"     body: {body[:300]}", flush=True)
        sys.exit(1)
    print(f"  PASS: {msg}", flush=True)


SAMPLE = (
    "书名: E2E测试\n"
    "作者: Tester\n"
    "\n"
    "第一章 开始\n"
    "Hello world.\n"
    "\n"
    "第二章 旅途\n"
    "More text.\n"
    "\n"
    "第三章 结局\n"
    "End.\n"
).encode("utf-8")


def main():
    print("== Frontend (Vite) + Backend (FastAPI) E2E ==")

    code, body = request("/")
    expect(code == 200, "Vite serves index.html", body)

    code, body = request("/src/main.jsx")
    expect(code == 200, "Vite serves main.jsx", body)

    code, body = request("/api/health")
    expect(code == 200 and '"healthy"' in body, "/api/health via Vite proxy", body)

    code, body = request("/api/models")
    expect(code == 200 and '"configs"' in body, "/api/models via Vite proxy", body)

    code, body = request(
        "/api/models",
        method="POST",
        data={
            "name": "e2e",
            "provider": "openai",
            "model_url": "https://api.example.com",
            "api_key": "sk-e2e",
            "model_name": "gpt-4",
            "enabled": True,
        },
    )
    expect(code == 201, "Create model via Vite proxy", body)
    model_id = json.loads(body)["id"]

    code, body = request(
        f"/api/models/{model_id}", method="PUT",
        data={
            "name": "e2e-updated",
            "provider": "openai",
            "model_url": "https://api.example.com",
            "api_key": "sk-e2e",
            "model_name": "gpt-4",
            "enabled": True,
        },
    )
    expect(code == 200, "Update model via Vite proxy", body)

    code, body = request(f"/api/models/{model_id}/toggle?enabled=0", method="PATCH")
    expect(code == 200, "Toggle model via Vite proxy", body)

    code, body = request(f"/api/models/{model_id}", method="DELETE")
    expect(code == 200, "Delete model via Vite proxy", body)

    code, body = request(
        "/api/novels/upload", method="POST", files={"file": ("e2e.txt", SAMPLE)}
    )
    expect(code == 201, "Upload novel via Vite proxy", body)
    novel_id = json.loads(body)["id"]

    code, body = request(
        f"/api/novels/{novel_id}/parse",
        method="POST",
        data={"rule": r"^第.{1,5}章"},
    )
    expect(code == 200 and '"success":true' in body, "Parse by rule via proxy", body)
    chapters = json.loads(body)["chapters"]
    expect(len(chapters) == 3, f"Parsed 3 chapters (got {len(chapters)})")

    code, body = request(
        f"/api/novels/{novel_id}/parse-preview",
        method="POST",
        data={"rule": r"^第.{1,5}章"},
    )
    expect(code == 200, "Parse preview via proxy", body)

    code, body = request(
        f"/api/novels/{novel_id}",
        method="PUT",
        data={"title": "新标题", "author": "新作者"},
    )
    expect(code == 200, "Update novel via proxy", body)

    chapter_id = chapters[0]["id"]
    code, body = request(f"/api/novels/{novel_id}/chapters/{chapter_id}")
    expect(code == 200 and "第一章" in body, "Get chapter via proxy", body)

    code, body = request(
        f"/api/novels/{novel_id}/parse-fixed",
        method="POST",
        data={"chunk_size": 50},
    )
    expect(code == 200, "Parse fixed via proxy", body)

    code, body = request(f"/api/novels/{novel_id}", method="DELETE")
    expect(code == 200, "Delete novel via proxy", body)

    code, body = request(f"/api/novels/{novel_id}")
    expect(code == 404, "Deleted novel 404", body)

    print("\nALL PASS: Frontend & Backend fully integrated via Vite proxy.")


if __name__ == "__main__":
    main()
