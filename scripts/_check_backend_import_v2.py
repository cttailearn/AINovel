"""Smoke import test for v0.2 backend changes."""
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from routers import enrichment_router
    from services import enrichment_suggestion_service, diff_service
    from services.enrichment_service import reset_novel, export_enriched_txt
    from database import (
        insert_suggestion,
        list_suggestions_by_chapter,
        get_suggestion,
        get_latest_applied_suggestion,
        mark_suggestion_status,
        touch_suggestion_applied,
        delete_suggestions_by_novel,
    )
    from schemas import (
        DiffSegment,
        DiffResponse,
        ApplyRequest,
        ApplyResponse,
        RevertRequest,
        RevertResponse,
        SuggestionOut,
        HistoryResponse,
    )
    from main import app

    # 找到 enrichment 路由
    enrichment_paths = [
        r.path for r in app.routes
        if hasattr(r, "path") and "/enrichment" in r.path
    ]
    print("IMPORT OK")
    print("enrichment routes:")
    for p in sorted(set(enrichment_paths)):
        print(f"  {p}")
except Exception as e:
    print(f"IMPORT FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
