from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import re

SOURCE_PRIORITY = {
    "mouser": 100,
    "official": 95,
    "datasheet4u": 85,
    "alldatasheet": 85,
    "datasheet_pdf": 70,
    "migration": 50,
    "admin": 110,
}

_BAD = {"reel", "cut tape", "tray", "mousereel", "mouse reel", "tube", "bulk", "tape & reel", "tape and reel"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def clean_package(value: Optional[str]) -> Optional[str]:
    """Return a canonical package token/name, never a surrounding prose sentence."""
    v = " ".join(str(value or "").replace("\n", " ").split()).strip(" .,:;()[]")
    if not v or v.casefold() in _BAD:
        return None
    # Already compact package codes/names are preserved.
    if len(v) <= 64 and len(v.split()) <= 5 and not re.search(r"\b(?:device|available|package|packaged|comes in|provided in|offered in)\b", v, re.I):
        return v
    # Extract the package-bearing token from prose, preferring explicit pin-count + family.
    patterns = [
        r"\b(?:\d{1,3}[- ]?pin[- ]?)?(?:SDIP|PDIP|DIP|SIP|SOIC|SOP|SSOP|TSSOP|TSOP|QFP|LQFP|TQFP|QFN|DFN|BGA|FBGA|LGA|PLCC|CLCC|SOT[- ]?\d+[A-Z0-9-]*|TO[- ]?\d+[A-Z0-9-]*)(?:[- /][A-Z0-9.]+){0,5}\b",
        r"\b[A-Z]{1,8}\d{1,3}[-P]*[-A-Z0-9.]{2,40}\b",
    ]
    for pat in patterns:
        m = re.search(pat, v, flags=re.I)
        if m:
            token = " ".join(m.group(0).split()).strip(" .,:;()[]")
            token = re.sub(r"\s+package$", "", token, flags=re.I).strip()
            if token and token.casefold() not in _BAD:
                return token
    # Do not promote long natural-language claims into canonical metadata.
    return None


def apply_package_candidate(metadata: Dict[str, Any], *, value: Optional[str], source: str, resolved_by: str,
                            exact_part_number_match: bool, attribute_name: Optional[str] = None) -> bool:
    value = clean_package(value)
    if not value:
        return False
    pkg = metadata.setdefault("package", {})
    current = clean_package(pkg.get("value"))
    incoming_score = SOURCE_PRIORITY.get(source, 40)
    current_score = SOURCE_PRIORITY.get(str(pkg.get("source") or ""), -1) if current else -1
    # Phase 3 is a fallback; it never overwrites a valid Phase-2 package.
    if current and current_score >= incoming_score:
        return False
    pkg.update({
        "value": value,
        "source": source,
        "attribute_name": attribute_name,
        "status": "resolved",
        "resolved_by": resolved_by,
        "exact_part_number_match": bool(exact_part_number_match),
        "updated_at": _now(),
    })
    return True


def needs_phase3_package_fallback(metadata: Dict[str, Any]) -> bool:
    return not bool(clean_package((metadata.get("package") or {}).get("value")))
