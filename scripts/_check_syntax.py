"""Verify enrichment module can be imported + its key symbols exist."""
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# Import enrichment directly without going through services package
import importlib

# 1. config
from config import (
    ENRICHMENT_DEFAULT_CONCURRENCY,
    EXPORTS_DIR,
)
assert ENRICHMENT_DEFAULT_CONCURRENCY > 0
assert EXPORTS_DIR.exists(), f"EXPORTS_DIR not created: {EXPORTS_DIR}"
print(f"[OK ] ENRICHMENT_DEFAULT_CONCURRENCY={ENRICHMENT_DEFAULT_CONCURRENCY}")
print(f"[OK ] EXPORTS_DIR={EXPORTS_DIR}")

# 2. schemas
from schemas import (
    ENRICHMENT_STEPS,
    ENRICHMENT_STEP_LABELS,
    EnrichmentBatchRequest,
    EnrichmentDetailResponse,
    EnrichmentProgressItem,
    EnrichmentProgressResponse,
    EnrichmentResetResponse,
    EnrichmentRunRequest,
    EnrichmentRunResponse,
    EnrichmentUpdateRequest,
)
assert ENRICHMENT_STEPS == ("summary", "recognition", "rewrite")
print(f"[OK ] ENRICHMENT_STEPS={ENRICHMENT_STEPS}")
print(f"[OK ] ENRICHMENT_STEP_LABELS={ENRICHMENT_STEP_LABELS}")

# 3. database helpers
from database import (
    list_enrichment_by_novel,
    list_failed_chapter_ids,
    reset_novel_enrichments,
    upsert_enrichment,
    get_enrichment_by_chapter,
)
print("[OK ] database enrichment helpers import")

# 4. service
from services.enrichment_service import (
    ENRICHMENT_STEPS as SVC_STEPS,
    STEP_PROMPT_KEY,
    list_progress,
    get_detail,
    run_step,
    run_batch,
    update_manual,
    reset_novel,
    export_enriched_txt,
)
assert SVC_STEPS == ("summary", "recognition", "rewrite")
print(f"[OK ] service steps={SVC_STEPS}")
print(f"[OK ] STEP_PROMPT_KEY={STEP_PROMPT_KEY}")

# 5. router
from routers.enrichment import router as enrichment_router
prefix = enrichment_router.prefix
assert prefix == "/api/enrichment", f"unexpected prefix: {prefix}"
print(f"[OK ] enrichment router prefix={prefix}")

# 6. main app loads
import main
print(f"[OK ] main loaded, app routes: {len(main.app.routes)}")

# 7. check enrichment routes are registered
enrich_paths = [r.path for r in main.app.routes if hasattr(r, "path") and "/enrichment" in getattr(r, "path", "")]
print(f"[OK ] enrichment paths: {enrich_paths}")

# 8. check default prompts include enrichment
from services.prompt_service import DEFAULT_PROMPTS, PROMPT_CATEGORIES
keys = [p["key"] for p in DEFAULT_PROMPTS]
expected = [
    "enrichment.summary",
    "enrichment.recognition",
    "enrichment.rewrite",
    "enrichment.scene_classify",
    "enrichment.rewrite_rule.general",
    "enrichment.rewrite_rule.scene_battle",
    "enrichment.rewrite_rule.scene_emotion",
]
for k in expected:
    assert k in keys, f"missing default prompt: {k}"
print(f"[OK ] all {len(expected)} enrichment default prompts registered")

cat_keys = [c["key"] for c in PROMPT_CATEGORIES]
for ck in ("enrichment", "rewrite_general", "rewrite_scene"):
    assert ck in cat_keys, f"missing category: {ck}"
print("[OK ] enrichment / rewrite_general / rewrite_scene categories present")

print("\n=== ALL CHECKS PASSED ===")