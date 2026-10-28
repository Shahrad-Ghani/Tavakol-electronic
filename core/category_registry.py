from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "config" / "category_registry.json"


@lru_cache(maxsize=4)
def load_registry(path: str | None = None) -> dict[str, Any]:
    p = Path(path).resolve() if path else REGISTRY_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("categories"), dict):
        raise ValueError(f"Invalid category registry: {p}")
    return data


def category_keys() -> list[str]:
    return [k for k, v in load_registry()["categories"].items() if v.get("active", True)]


def category_record(key: str) -> dict[str, Any]:
    k = str(key or "").strip()
    rec = load_registry()["categories"].get(k)
    if not isinstance(rec, dict):
        raise KeyError(f"Unknown category key: {key!r}")
    return rec


def normalize_category_key(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw in load_registry()["categories"]:
        return raw
    folded = re.sub(r"\s+", " ", raw).casefold()
    legacy_folded = folded.replace("‌", " ")
    for key, rec in load_registry()["categories"].items():
        aliases = [key, rec.get("display_name"), rec.get("title_prefix"), rec.get("wordpress", {}).get("child")]
        normalized = [re.sub(r"\s+", " ", str(x or "")).casefold() for x in aliases if str(x or "").strip()]
        if any(alias == folded for alias in normalized):
            return key
    # Legacy V3 breadcrumb mapping must run AFTER exact dynamic-name matches.
    if "آی سی" in legacy_folded:
        return "ic"
    for key, rec in load_registry()["categories"].items():
        aliases = [key, rec.get("display_name"), rec.get("wordpress",{}).get("child")]
        if any(re.sub(r"\s+", " ", str(alias or "")).casefold() in folded
               for alias in aliases if str(alias or "").strip()):
            return key
    return None


def product_title(part_number: str, category_key: str | None) -> str:
    pn = str(part_number or "").strip()
    if not pn:
        raise ValueError("part_number is required")
    key = normalize_category_key(category_key) or "ic"
    prefix = str(category_record(key).get("title_prefix") or category_record(key).get("display_name") or "محصول").strip()
    return f"{prefix} {pn}".strip()


def density_phrase(category_key: str | None) -> str:
    key = normalize_category_key(category_key) or "ic"
    return str(category_record(key).get("density_phrase") or f"این {category_record(key).get('display_name','محصول')}").strip()


def category_context(category_key: str | None) -> dict[str, Any]:
    key = normalize_category_key(category_key) or "ic"
    rec = category_record(key)
    return {"key": key, **rec}


def product_slug(part_number: str, category_key: str | None) -> str:
    pn = str(part_number or "").strip().lower()
    key = normalize_category_key(category_key) or "ic"
    rule = str(category_record(key).get("slug_rule") or "{pn}-{key}")
    return rule.format(pn=pn, key=key).strip("-/ ")
