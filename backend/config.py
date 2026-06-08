import os
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
NOVELS_DIR = DATA_DIR / "novels"
DATABASE_PATH = DATA_DIR / "models.db"

# 后端服务固定绑定 127.0.0.1:8008 — 这是硬编码,与桌面壳 (Tauri) 和 Vite proxy
# (frontend/vite.config.js) 中所有调用约定一致。不要改成 env 变量或换端口,否则前端将无法定位。
API_HOST = "127.0.0.1"
API_PORT = 8008

CORS_ORIGINS: List[str] = [
    o.strip()
    for o in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,tauri://localhost,http://tauri.localhost",
    ).split(",")
    if o.strip()
]
CORS_CREDENTIALS = True
CORS_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
CORS_HEADERS = ["*"]

DEFAULT_CHUNK_SIZE = 5000
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))
MAX_RAW_PREVIEW_SIZE = int(os.getenv("MAX_RAW_PREVIEW_SIZE", str(20 * 1024 * 1024)))
PARSE_RULE_PREVIEW_LIMIT = 20

ALLOWED_NOVEL_EXT = {".txt"}

# Novel enrichment (小说加料)
ENRICHMENT_DEFAULT_CONCURRENCY = int(
    os.getenv("ENRICHMENT_DEFAULT_CONCURRENCY", "2")
)
ENRICHMENT_DEFAULT_MODEL = os.getenv("ENRICHMENT_DEFAULT_MODEL", "")
EXPORTS_DIR = DATA_DIR / "exports"

DATA_DIR.mkdir(parents=True, exist_ok=True)
NOVELS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
