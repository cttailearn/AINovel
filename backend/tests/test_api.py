import io
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

import main as main_module
from main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _sample_novel_bytes() -> bytes:
    return (
        "书名: 测试小说\n"
        "作者: 测试作者\n"
        "\n"
        "第一章 起点\n"
        "这是第一章的内容，讲述了故事的开端。\n"
        "\n"
        "第二章 发展\n"
        "故事继续发展，情节逐步推进。\n"
        "\n"
        "第三章 结局\n"
        "故事迎来最终结局。\n"
    ).encode("utf-8")


def test_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_models_crud(client: TestClient):
    r = client.get("/api/models")
    assert r.status_code == 200
    assert r.json()["configs"] == []

    payload = {
        "name": "Test Claude",
        "provider": "anthropic",
        "model_url": "https://api.example.com",
        "api_key": "sk-test-12345",
        "model_name": "claude-3-5-sonnet",
        "enabled": True,
    }
    r = client.post("/api/models", json=payload)
    assert r.status_code == 201, r.text
    model_id = r.json()["id"]
    assert model_id > 0

    r = client.get("/api/models")
    assert len(r.json()["configs"]) == 1
    assert r.json()["configs"][0]["name"] == "Test Claude"

    r = client.patch(f"/api/models/{model_id}/toggle", params={"enabled": 0})
    assert r.status_code == 200

    payload["name"] = "Test Claude Updated"
    r = client.put(f"/api/models/{model_id}", json=payload)
    assert r.status_code == 200
    assert "updated" in r.json()["message"]

    r = client.delete(f"/api/models/{model_id}")
    assert r.status_code == 200
    assert r.json()["message"] == f"Configuration {model_id} deleted"

    r = client.get("/api/models")
    assert r.json()["configs"] == []


def test_model_not_found(client: TestClient):
    r = client.delete("/api/models/99999")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


def test_model_validation_error(client: TestClient):
    r = client.post("/api/models", json={"name": "x"})
    assert r.status_code == 422


def test_upload_invalid_extension(client: TestClient):
    files = {"file": ("a.exe", b"binary", "application/octet-stream")}
    r = client.post("/api/novels/upload", files=files)
    assert r.status_code == 400
    assert "格式" in r.json()["detail"]


def test_upload_novel_success(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    r = client.post("/api/novels/upload", files=files)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["title"] == "测试小说"
    assert body["author"] == "测试作者"
    assert body["status"] == "pending"
    assert body["id"] > 0


def test_upload_empty_file(client: TestClient):
    files = {"file": ("empty.txt", b"", "text/plain")}
    r = client.post("/api/novels/upload", files=files)
    assert r.status_code == 400


def test_list_novels_includes_count(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    r = client.post("/api/novels/upload", files=files)
    novel_id = r.json()["id"]

    r = client.get("/api/novels")
    assert r.status_code == 200
    novels = r.json()["novels"]
    assert len(novels) == 1
    assert novels[0]["chapter_count"] == 0


def test_get_novel_detail_404(client: TestClient):
    r = client.get("/api/novels/9999")
    assert r.status_code == 404


def test_parse_chapters_with_rule(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.post(
        f"/api/novels/{novel_id}/parse",
        json={"rule": r"^第.{1,5}章"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["chapters_found"] == 3
    assert [c["chapter_number"] for c in body["chapters"]] == [1, 2, 3]


def test_parse_preview(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.post(
        f"/api/novels/{novel_id}/parse-preview",
        json={"rule": r"^第.{1,5}章"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["chapters_found"] == 3
    assert len(body["preview"]) == 3


def test_parse_invalid_regex(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.post(
        f"/api/novels/{novel_id}/parse", json={"rule": "[invalid("}
    )
    assert r.status_code == 400


def test_parse_fixed_size(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.post(
        f"/api/novels/{novel_id}/parse-fixed", json={"chunk_size": 50}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["chapters_found"] >= 1


def test_set_parse_rule(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.put(
        f"/api/novels/{novel_id}/parse-rule", json={"rule": r"第\d+章"}
    )
    assert r.status_code == 200

    detail = client.get(f"/api/novels/{novel_id}").json()
    assert detail["parse_rule"] == r"第\d+章"


def test_update_novel_info(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.put(
        f"/api/novels/{novel_id}",
        json={"title": "新标题", "author": "新作者"},
    )
    assert r.status_code == 200

    detail = client.get(f"/api/novels/{novel_id}").json()
    assert detail["title"] == "新标题"
    assert detail["author"] == "新作者"


def test_get_chapter_content(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]
    client.post(
        f"/api/novels/{novel_id}/parse", json={"rule": r"^第.{1,5}章"}
    )

    detail = client.get(f"/api/novels/{novel_id}").json()
    chapter_id = detail["chapters"][1]["id"]

    r = client.get(f"/api/novels/{novel_id}/chapters/{chapter_id}")
    assert r.status_code == 200
    body = r.json()
    assert "第二章" in body["title"]
    assert body["content"]


def test_get_chapter_not_found(client: TestClient):
    r = client.get("/api/novels/1/chapters/9999")
    assert r.status_code == 404


def test_delete_novel_cascades_chapters(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]
    client.post(
        f"/api/novels/{novel_id}/parse", json={"rule": r"^第.{1,5}章"}
    )

    r = client.delete(f"/api/novels/{novel_id}")
    assert r.status_code == 200

    r = client.get(f"/api/novels/{novel_id}")
    assert r.status_code == 404


def test_raw_content_chunking(client: TestClient):
    files = {"file": ("demo.txt", _sample_novel_bytes(), "text/plain")}
    novel_id = client.post("/api/novels/upload", files=files).json()["id"]

    r = client.get(f"/api/novels/{novel_id}/raw", params={"chunk_size": 30})
    assert r.status_code == 200
    body = r.json()
    assert "chunks" in body
    assert isinstance(body["chunks"], list)


def test_cors_preflight(client: TestClient):
    r = client.options(
        "/api/models",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code in (200, 204)
    assert "access-control-allow-origin" in {k.lower() for k in r.headers.keys()}


def test_404_returns_json(client: TestClient):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
