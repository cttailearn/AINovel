import logging
import socket
import sys
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from config import (
    API_HOST,
    API_PORT,
    CORS_CREDENTIALS,
    CORS_HEADERS,
    CORS_METHODS,
    CORS_ORIGINS,
    write_port_file,
)
from database import close_db, init_db
from routers import (
    creation_router,
    enrichment_router,
    image_router,
    models_router,
    novels_router,
    prompts_router,
    tasks_router,
)
from services.metrics_service import render_metrics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logger.info("Database initialized")
    try:
        yield
    finally:
        await close_db()
        logger.info("Database connection closed")


app = FastAPI(
    title="AI 小说管理系统 API",
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_CREDENTIALS,
    allow_methods=CORS_METHODS,
    allow_headers=CORS_HEADERS,
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    return JSONResponse(
        status_code=422,
        content={"detail": "请求参数不合法", "errors": exc.errors()},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request, exc: Exception
):
    logger.exception("Unhandled exception at %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "服务器内部错误"},
    )


app.include_router(models_router)
app.include_router(novels_router)
app.include_router(prompts_router)
app.include_router(image_router)
app.include_router(enrichment_router)
app.include_router(creation_router)
app.include_router(tasks_router)


@app.get("/api")
def read_root():
    return {"message": "AI 小说管理系统 API"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


@app.get("/metrics", include_in_schema=False)
def metrics():
    return PlainTextResponse(
        render_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ============================================================
# 端口绑定:硬编码 8008,启动前强校验,不被其它程序干扰
# ============================================================
def _try_bind(host: str, port: int):
    """尝试用 SO_REUSEADDR 绑定端口。返回 (socket, None) 或 (None, exc)。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except OSError:
        # 极少数环境不支持 SO_REUSEADDR,继续尝试普通 bind
        pass
    try:
        sock.bind((host, port))
    except OSError as exc:
        try:
            sock.close()
        except Exception:
            pass
        return None, exc
    return sock, None


def _preflight_check_port(host: str, port: int, retries: int = 5, delay: float = 0.6) -> bool:
    """在 uvicorn 启动前对目标端口做预检。

    - 监听 SO_REUSEADDR,允许绑定到 TIME_WAIT 状态的端口;
    - 若被占用,短暂等待并重试,应对端口刚被释放的场景;
    - 真正长期占用时返回 False,由调用方决定是否直接退出。
    """
    for attempt in range(1, retries + 1):
        sock, exc = _try_bind(host, port)
        if sock is not None:
            sock.close()
            if attempt > 1:
                logger.info("端口预检通过 (第 %d 次尝试)", attempt)
            return True
        if attempt < retries:
            logger.warning(
                "端口 %s:%d 暂不可用 (%s),%.1fs 后重试 (%d/%d)",
                host, port, exc, delay, attempt, retries,
            )
            time.sleep(delay)
        else:
            logger.error("端口 %s:%d 持续不可用: %s", host, port, exc)
    return False


if __name__ == "__main__":
    logger.info(
        "后端服务端口: %s:%d (可用 AINOVEL_PORT 环境变量覆盖,默认 8008)",
        API_HOST, API_PORT,
    )

    # 把最终端口写回 data/.port, 让前端 (尤其 Tauri 模式下) 启动时可读
    # 到实际端口而不是猜 8008。
    write_port_file(API_PORT)

    # 预检端口:若被占用,短暂等待重试;持续占用则清晰报错退出
    if not _preflight_check_port(API_HOST, API_PORT):
        logger.error("=" * 64)
        logger.error(
            "无法启动:端口 %s:%d 已被其它程序占用,且重试后仍不可用",
            API_HOST, API_PORT,
        )
        logger.error("请在 PowerShell 中执行以下命令定位占用进程并结束它:")
        logger.error("    netstat -ano | findstr \":%d \"", API_PORT)
        logger.error("    taskkill /F /PID <上一步得到的 PID>")
        logger.error("=" * 64)
        sys.exit(1)

    # 直接交给 uvicorn 绑定监听(预检已确认端口可用)。
    # 注意:不要用 fd= 参数,uvicorn 内部硬编码 socket.AF_UNIX,
    # 在 Windows 上会因为模块没有 AF_UNIX 而崩溃。host/port 路径走的是 IPv4,
    # 与 config.API_HOST/API_PORT 一致。
    try:
        uvicorn.run(
            app,
            host=API_HOST,
            port=API_PORT,
            log_level="info",
            access_log=False,
        )
    except OSError as exc:
        # 极端 race:预检通过但 uvicorn 绑定时仍然失败
        logger.error("=" * 64)
        logger.error("uvicorn 绑定失败: %s", exc)
        logger.error("端口 %d 在预检与启动之间被其它程序抢占", API_PORT)
        logger.error("=" * 64)
        sys.exit(1)
