"""Syntax check for backend Python files (v0.2)."""
import ast
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent / "backend"

FILES = [
    "database.py",
    "schemas.py",
    "routers/enrichment.py",
    "services/diff_service.py",
    "services/enrichment_service.py",
    "services/enrichment_suggestion_service.py",
]

failed = False
for name in FILES:
    path = BACKEND / name
    if not path.exists():
        print(f"MISSING: {name}")
        failed = True
        continue
    src = path.read_text(encoding="utf-8")
    try:
        ast.parse(src, filename=name)
        print(f"OK: {name}")
    except SyntaxError as exc:
        print(f"FAIL: {name} -> {exc}")
        failed = True

sys.exit(1 if failed else 0)
