"""Quick syntax check for backend AI creation module."""
import ast
import sys
import py_compile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

files = [
    BACKEND / "database.py",
    BACKEND / "schemas.py",
    BACKEND / "main.py",
    BACKEND / "config.py",
    BACKEND / "routers" / "creation.py",
    BACKEND / "routers" / "__init__.py",
    BACKEND / "services" / "__init__.py",
    BACKEND / "services" / "creation_service.py",
    BACKEND / "services" / "creation_agents.py",
    BACKEND / "services" / "prompt_service.py",
]

errors = []
for fp in files:
    try:
        py_compile.compile(str(fp), doraise=True)
        print(f"OK   {fp.relative_to(BACKEND.parent)}")
    except py_compile.PyCompileError as e:
        errors.append((fp, str(e)))
        print(f"FAIL {fp.relative_to(BACKEND.parent)}: {e}")

if errors:
    print(f"\n{len(errors)} syntax error(s)")
    sys.exit(1)
print("\nAll files OK")
