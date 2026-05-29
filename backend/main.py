from contextlib import asynccontextmanager
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import API_HOST, API_PORT, CORS_ORIGINS, CORS_CREDENTIALS, CORS_METHODS, CORS_HEADERS, NOVELS_DIR
from database import init_db
from routers import models_router, novels_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    if not NOVELS_DIR.exists():
        NOVELS_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_CREDENTIALS,
    allow_methods=CORS_METHODS,
    allow_headers=CORS_HEADERS,
)

app.include_router(models_router)
app.include_router(novels_router)


@app.get("/api")
def read_root():
    return {"message": "Hello, World!"}


@app.get("/api/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host=API_HOST, port=API_PORT)