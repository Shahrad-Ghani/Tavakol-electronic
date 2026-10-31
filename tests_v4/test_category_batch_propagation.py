import json
from pathlib import Path

import admin_audit
from metadata_manager import _new_record


def test_batch_category_change_archives_old_metadata_and_invalidates_downstream(tmp_path, monkeypatch):
    root = tmp_path
    metadata_dir = root / "metadata"
    metadata_dir.mkdir()
    meta_path = metadata_dir / "2N7000.json"
    data = _new_record("2N7000", "ic")
    data["part_number"] = "2N7000"
    data["source_reference"] = "2N7000"
    data["phase3"]["status"] = "completed"
    data["publishing"]["bundle_status"] = "READY"
    meta_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    p3 = root / "phase3_outputs" / "2N7000.json"
    p3.parent.mkdir()
    p3.write_text(json.dumps({"identity": {"part_number": "2N7000", "product_category": "ic"}}), encoding="utf-8")

    archive = root / "audit_history" / "category_change"
    monkeypatch.setattr(admin_audit, "_archive_dir", lambda *args: archive)
    monkeypatch.setattr(admin_audit, "_invalidate_phase3", lambda *args, **kwargs: {})
    monkeypatch.setattr(admin_audit, "_invalidate_fact_extraction", lambda *args, **kwargs: None)
    monkeypatch.setattr(admin_audit, "invalidate_bundle", lambda *args, **kwargs: None)

    result = admin_audit.apply_batch_category(root, meta_path, data, "mosfet")
    saved = json.loads(meta_path.read_text(encoding="utf-8"))
    archived = json.loads((archive / "metadata_before" / meta_path.name).read_text(encoding="utf-8"))

    assert result["changed"] is True
    assert result["invalidated_downstream"] is True
    assert saved["category"]["key"] == "mosfet"
    assert saved["product_type"] == "mosfet"
    assert saved["product_title"] == "ماسفت 2N7000"
    assert saved["admin_audit"]["status"] == "DISAPPROVED_PENDING_REPROCESS"
    assert saved["admin_audit"]["force_fact_extraction"] is True
    assert archived["category"]["key"] == "ic"


def test_existing_wordpress_product_blocks_batch_category_change(tmp_path):
    meta_path = tmp_path / "metadata.json"
    data = _new_record("2N7000", "ic")
    data["part_number"] = "2N7000"
    data["publishing"]["wordpress_product_id"] = "1234"

    result = admin_audit.apply_batch_category(tmp_path, meta_path, data, "mosfet")

    assert result["blocked"] is True
    assert result["reason"] == "WORDPRESS_PRODUCT_ALREADY_EXISTS"
    assert data["category"]["key"] == "ic"
