#!/usr/bin/env python3
"""Safe, read-only diagnostic for the V4.0.6 category hotfix.
Run from the repository root: python verify_publisher_hotfix.py
No WordPress network requests or mutations occur in this script.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

root = Path(__file__).resolve().parent
expected = root / "phase4" / "publisher.py"
print("Project root:    ", root)
print("Expected source: ", expected)
if not expected.is_file():
    print("ERROR: Expected publisher.py missing; zip may have been extracted into a nested folder.")
    raise SystemExit(1)

source = expected.read_text(encoding="utf-8-sig")
print("Source SHA256:  ", hashlib.sha256(expected.read_bytes()).hexdigest())
print("V2 source marker:", "CATEGORY_HOTFIX_V2" in source)
print("Runtime log marker:", "CATEGORY HOTFIX V2 ACTIVE" in source)

try:
    from phase4 import publisher
    loaded = Path(publisher.__file__).resolve()
    loaded_func = inspect.getsource(publisher._category_checkbox)
    print("Imported source: ", loaded)
    print("Imported V2:     ", "CATEGORY_HOTFIX_V2" in loaded_func)
    print("Correct location:", loaded == expected.resolve())
    if loaded != expected.resolve() or "CATEGORY_HOTFIX_V2" not in loaded_func:
        print("FAIL: Python is using a different or unpatched Publisher implementation.")
        raise SystemExit(2)
except (ImportError, ModuleNotFoundError) as exc:
    print("IMPORT DIAGNOSTIC FAILED:", type(exc).__name__, str(exc))
    print("This does not change files. Check dependencies and compare the source-marker lines above.")
    raise SystemExit(3)
print("PASS: V2 category hotfix is the one imported by Python.")
