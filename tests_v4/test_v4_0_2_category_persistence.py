from pathlib import Path

from core.category_registry import category_context
from metadata_manager import _canonicalize_before_write, _new_record


def test_v4_category_context_survives_metadata_write():
    record = _new_record("2N7000", "mosfet")
    persisted = _canonicalize_before_write(record)
    assert persisted["product_type"] == "mosfet"
    assert persisted["category"] == category_context("mosfet")
    assert persisted["category"]["key"] == "mosfet"


def test_integrated_adapter_rebuilds_context_from_registry_not_optional_metadata_block():
    root = Path(__file__).resolve().parents[1]
    text = (root / "orchestrator" / "adapter.py").read_text(encoding="utf-8")
    assert '"category_context": category_context(get_category_key(meta))' in text
    assert '"category_context": deepcopy(meta.get("category") or {})' not in text
