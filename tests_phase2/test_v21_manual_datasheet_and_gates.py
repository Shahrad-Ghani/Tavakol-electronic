import json
from pathlib import Path

from pypdf import PdfWriter

from admin_audit import attach_manual_datasheet, list_audit_items
from metadata_manager import load_or_create, save
from orchestrator.adapter import build_phase3_input


def _dirs(root: Path):
    for name in ("metadata", "input", "output", "Final", "datasheets", "phase3_outputs", "products", "work/fact_extraction", "work/content", "runtime_state", "audit_history"):
        (root / name).mkdir(parents=True, exist_ok=True)


def _valid_pdf(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    w = PdfWriter()
    w.add_blank_page(width=612, height=792)
    with path.open("wb") as f:
        w.write(f)


def _manual_required_meta(root: Path, pn="MAN123"):
    _dirs(root)
    meta, data = load_or_create(root, pn)
    data["part_number"] = pn
    data["product_title"] = f"آی سی {pn}"
    data["source_reference"] = pn
    data["datasheet"].update({
        "status": "manual_required",
        "searched_part_number": pn,
        "matched_part_number": pn,
        "verified_exact_match": True,
        "identity_status": "EXACT_PART_NUMBER_FOUND",
        "file": None,
    })
    save(meta, data)
    return meta


def test_manual_required_is_audit_needed_and_cannot_build_phase3(tmp_path):
    meta = _manual_required_meta(tmp_path)
    items = list_audit_items(tmp_path)
    assert items[0]["classification"] == "AUDIT_NEEDED"
    assert items[0]["datasheet"]["status"] == "manual_required"
    try:
        build_phase3_input(tmp_path, meta)
    except RuntimeError as exc:
        assert "manual_required" in str(exc)
    else:
        raise AssertionError("Phase3 input should be blocked for manual_required")


def test_attach_manual_datasheet_copies_pdf_updates_metadata_and_queues_phase3(tmp_path):
    meta = _manual_required_meta(tmp_path, pn="MAN456")
    source = tmp_path / "incoming.pdf"
    _valid_pdf(source)
    result = attach_manual_datasheet(tmp_path, meta, source)
    target = tmp_path / "datasheets" / "MAN456.pdf"
    assert target.exists()
    assert result["pages"] == 1
    saved = json.loads(meta.read_text(encoding="utf-8"))
    assert saved["datasheet"]["status"] == "completed"
    assert saved["datasheet"]["file"] == "datasheets/MAN456.pdf"
    assert saved["datasheet"]["document_source"] == "ADMIN_AUDIT_MANUAL"
    assert saved["datasheet"]["verified_exact_match"] is True
    assert "status" not in saved  # V3 has no duplicate summary-status booleans.
    assert saved["phase3"]["status"] in {"not_started", "invalidated"}
    assert saved["admin_audit"]["force_phase2"] is False
    assert saved["admin_audit"]["force_seo"] is True
    assert saved["admin_audit"]["force_fact_extraction"] is True
    assert "manual_datasheet_added" in saved["admin_audit"]["selected_issues"]


def test_ui_contains_drag_drop_and_browse_fallback():
    text = Path("run_ui.py").read_text(encoding="utf-8")
    assert "tkinterdnd2" in text
    assert "Drop datasheet PDF here" in text
    assert "Browse PDF" in text
    assert "attach_manual_datasheet" in text
    assert 'dnd_bind("<<Drop>>"' in text


def test_orchestrator_blocks_manual_required_before_phase3_queue():
    text = Path("orchestrator/engine.py").read_text(encoding="utf-8")
    assert '"sales_only_no_datasheet"' in text
    assert '"manual_required"' not in next(line for line in text.splitlines() if line.startswith('P2_TERMINAL_TO_PHASE3 ='))
    assert 'if ds_status == "manual_required":' in text
    assert 'phase3="BLOCKED_MANUAL_DATASHEET"' in text
    assert 'if status == "manual_required":' in text
