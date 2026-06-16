import os
from pathlib import Path
from typing import List

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
NOVELS_DIR = DATA_DIR / "novels"
DATABASE_PATH = DATA_DIR / "models.db"
PORT_FILE = DATA_DIR / ".port"

# 后端服务默认绑定 127.0.0.1:8008 — 这是与桌面壳 (Tauri) 和 Vite proxy
# (frontend/vite.config.js) 中所有调用约定的默认值。允许 AINOVEL_PORT 覆盖
# (CI / 多实例 / Tauri 端口随机化场景),并写回 data/.port 供前端同步读取。
_DEFAULT_PORT = 8008


def _resolve_port() -> int:
    """决定最终端口: AINOVEL_PORT > data/.port > 8008.

    优先级说明:
    * ``AINOVEL_PORT``:  启动时显式指定 (CI / 调试用)
    * ``data/.port``:    上次成功启动时写入, 用于前端启动时同步
    * ``8008``:          默认
    """
    env = os.getenv("AINOVEL_PORT")
    if env:
        try:
            return int(env)
        except (TypeError, ValueError):
            pass
    if PORT_FILE.exists():
        try:
            saved = int(PORT_FILE.read_text(encoding="utf-8").strip())
            if 1 <= saved <= 65535:
                return saved
        except (TypeError, ValueError, OSError):
            pass
    return _DEFAULT_PORT


API_HOST = "127.0.0.1"
API_PORT = _resolve_port()


def write_port_file(port: int) -> None:
    """启动成功后将端口号写回 data/.port, 供前端启动时同步.

    失败不抛异常 (本地 IO 不应阻塞主流程).
    """
    try:
        PORT_FILE.write_text(str(int(port)), encoding="utf-8")
    except OSError:
        # 静默 — 写入失败仅影响前端同步端口, 后端本身不受影响
        pass

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
IMAGE_CACHE_DIR = DATA_DIR / "image_cache"

DATA_DIR.mkdir(parents=True, exist_ok=True)
NOVELS_DIR.mkdir(parents=True, exist_ok=True)
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
