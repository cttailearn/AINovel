from pathlib import Path
import os

BASE_DIR = Path(__file__).parent
NOVELS_DIR = BASE_DIR / "novels"
DATABASE_PATH = BASE_DIR / "models.db"

API_HOST = "0.0.0.0"
API_PORT = 8008

CORS_ORIGINS = ["*"]
CORS_CREDENTIALS = True
CORS_METHODS = ["*"]
CORS_HEADERS = ["*"]

DEFAULT_CHUNK_SIZE = 5000