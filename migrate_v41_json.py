"""Non-destructive metadata migration helper for Phase 1 Final V1.5.

The filename is retained for repository compatibility with previous releases.
Only missing fields are added; populated legacy values are never overwritten.
"""
from pathlib import Path
import json
from dotenv import load_dotenv

from metadata_manager import _new_record, _normalize_legacy_metadata, _normalize_integrated_identity, save


ROOT = Path(__file__).resolve().parent
META = ROOT / "metadata"


def _merge_missing(target: dict, defaults: dict):
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_missing(target[key], value)


def deep_defaults(data):
    ref = data.get("img_refrence_name") or data.get("product_id") or data.get("name") or "UNKNOWN"
    data.setdefault("product_id", ref)
    data.setdefault("name", ref)
    data.setdefault("category", "IC")
    data.setdefault("img_refrence_name", ref)
    data.setdefault("PartNumber", None)
    data.setdefault("manufacturer", None)
    data.setdefault("country", None)

    defaults = _new_record(str(ref), data.get("category") or "IC")
    _normalize_legacy_metadata(data)
    for section in (
        "status",
        "precheck",
        "regeneration",
        "identity_validation",
        "ocr",
        "logo",
        "output",
        "image_optimization",
        "datasheet",
        "api_accounting",
    ):
        _merge_missing(data.setdefault(section, {}), defaults[section])
    data.setdefault("phase2_history", [])
    _normalize_integrated_identity(data)
    return data


def main():
    load_dotenv(ROOT / ".env")
    if not META.exists():
        return
    for path in META.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        data = deep_defaults(data)
        save(path, data)
        print("[MIGRATED]", path.name)


if __name__ == "__main__":
    main()
