"""Altimate 1.0.1.1 legacy Sales-only decision compatibility regression tests."""
from __future__ import annotations

import json
from copy import deepcopy

from datasheet_authority_history import latest_admin_datasheet_decision
from metadata_manager import load_or_create, save, save_admin_override, save_phase2
from phase2.metadata_state import is_phase2_eligible, protected_datasheet_authority
from recover_datasheet_authority import propose, run
from pypdf import PdfWriter


def _record(root, pn="TEST100"):
    (root / "metadata").mkdir(exist_ok=True)
    path, rec = load_or_create(root, pn)
    rec["part_number"] = pn
    rec["datasheet"]["status"] = "web_error"
    save(path, rec)
    return path, rec


def _pdf(root, pn="TEST100"):
    dst = root / "datasheets" / f"{pn}.pdf"
    dst.parent.mkdir(exist_ok=True)
    pdf = PdfWriter()
    pdf.add_blank_page(width=320, height=240)
    with dst.open("wb") as stream:
        pdf.write(stream)
    return dst


def _history(rec, *events):
    rec["admin_audit"]["history"].extend(events)
    return rec


def _legacy_event(pn="TEST100"):
    return {"action": "AUTHORIZE_SALES_ONLY_WITHOUT_DATASHEET", "part_number": pn,
            "at": "2026-10-13T12:09:49Z", "note": "No PDF; admin authorized"}


def test_legacy_sales_only_restores_and_preserves_approval_and_seo(tmp_path):
    path, data = _record(tmp_path)
    data["admin_audit"]["status"] = "APPROVED"
    data["phase3"]["status"] = "completed"
    data["publishing"]["status"] = "NOT_STARTED"
    _history(data, _legacy_event(), {"action": "APPROVE", "part_number": "TEST100"})
    save_admin_override(path, data)
    before = path.read_bytes()
    proposals = run(tmp_path)
    assert proposals[0]["action"] == "RESTORE_SALES_ONLY"
    assert path.read_bytes() == before
    run(tmp_path, apply=True)
    live = json.loads(path.read_text(encoding="utf-8"))
    assert live["datasheet"]["status"] == "sales_only_no_datasheet"
    assert live["datasheet"]["sales_only_authorized"] is True
    assert live["datasheet"]["file"] is None
    assert live["admin_audit"]["status"] == "APPROVED"
    assert live["phase3"]["status"] == "completed"
    assert live["publishing"]["status"] == "NOT_STARTED"
    assert live["phase2_history"][-1]["source_action"] == "AUTHORIZE_SALES_ONLY_WITHOUT_DATASHEET"
    assert not any(row["action"] == "RESTORE_SALES_ONLY" for row in run(tmp_path))
    assert list((tmp_path / "audit_history").rglob("TEST100.json"))


def test_legacy_sales_only_blocks_phase2_before_recovery(tmp_path):
    path, data = _record(tmp_path)
    _history(data, _legacy_event())
    save_admin_override(path, data)
    ok, reason = is_phase2_eligible(json.loads(path.read_text(encoding="utf-8")), tmp_path)
    assert not ok and reason == "HISTORICAL_SALES_ONLY_REQUIRES_RECOVERY"
    stale = deepcopy(data)
    stale["datasheet"]["status"] = "failed"
    save_phase2(path, stale)
    assert json.loads(path.read_text(encoding="utf-8"))["datasheet"]["status"] == "web_error"


def test_wrong_datasheet_disapproval_revokes_prior_sales_only(tmp_path):
    path, data = _record(tmp_path)
    _history(data, _legacy_event(), {"action": "DISAPPROVE", "part_number": "TEST100",
                                    "issues": ["wrong_data_sheet"]})
    save_admin_override(path, data)
    kind, reason, updated = propose(tmp_path, path, data)
    assert kind == "MANUAL_REVIEW" and updated is None
    assert latest_admin_datasheet_decision(data, "TEST100") is None
    is_protected, _ = protected_datasheet_authority(data, tmp_path)
    assert not is_protected


def test_wrong_part_number_disapproval_revokes_prior_sales_only(tmp_path):
    path, data = _record(tmp_path)
    _history(data, _legacy_event(), {"action": "DISAPPROVE", "part_number": "TEST100",
                                    "selected_issues": ["wrong_part_number"]})
    kind, reason, updated = propose(tmp_path, path, data)
    assert kind == "MANUAL_REVIEW" and updated is None


def test_unrelated_disapproval_does_not_revoke_sales_authority(tmp_path):
    path, data = _record(tmp_path)
    _history(data, _legacy_event(), {"action": "DISAPPROVE", "part_number": "TEST100",
                                    "issues": ["seo_content_regeneration_needed"]})
    kind, _, updated = propose(tmp_path, path, data)
    assert kind == "RESTORE_SALES_ONLY" and updated is not None


def test_latest_manual_pdf_overrides_legacy_sales_only(tmp_path):
    path, data = _record(tmp_path)
    _pdf(tmp_path)
    _history(data, _legacy_event(),
             {"action": "MANUAL_DATASHEET_ATTACHED", "part_number": "TEST100",
              "file": "datasheets/TEST100.pdf"})
    kind, _, updated = propose(tmp_path, path, data)
    assert kind == "RESTORE_MANUAL_PDF"
    assert updated["datasheet"]["file"] == "datasheets/TEST100.pdf"


def test_latest_sales_only_with_existing_pdf_requires_review(tmp_path):
    path, data = _record(tmp_path)
    _pdf(tmp_path)
    _history(data, {"action": "MANUAL_DATASHEET_ATTACHED", "part_number": "TEST100",
                    "file": "datasheets/TEST100.pdf"}, _legacy_event())
    kind, reason, updated = propose(tmp_path, path, data)
    assert kind == "MANUAL_REVIEW" and updated is None
    assert reason == "PDF_EXISTS_CONFLICTS_WITH_SALES_ONLY"
    assert protected_datasheet_authority(data, tmp_path)[0]


def test_action_for_different_pn_does_not_authorize(tmp_path):
    path, data = _record(tmp_path)
    _history(data, _legacy_event("DIFFERENT"))
    assert propose(tmp_path, path, data)[0] == "MANUAL_REVIEW"


def test_fresh_authorization_after_invalidation_is_valid(tmp_path):
    path, data = _record(tmp_path)
    _history(data, _legacy_event(),
             {"action": "DISAPPROVE", "part_number": "TEST100", "issues": ["wrong_data_sheet"]},
             {"action": "ADMIN_SALES_ONLY_AFTER_WEB_ERROR", "part_number": "TEST100",
              "at": "2026-10-14T13:00:00Z"})
    kind, _, updated = propose(tmp_path, path, data)
    assert kind == "RESTORE_SALES_ONLY" and updated is not None
    assert updated["phase2_history"][-1]["source_action"] == "ADMIN_SALES_ONLY_AFTER_WEB_ERROR"
