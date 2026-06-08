from .creation import router as creation_router
from .enrichment import router as enrichment_router
from .image import router as image_router
from .models import router as models_router
from .novels import router as novels_router
from .prompts import router as prompts_router

__all__ = [
    "models_router",
    "novels_router",
    "prompts_router",
    "image_router",
    "enrichment_router",
    "creation_router",
]
