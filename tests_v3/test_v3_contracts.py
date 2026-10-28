import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator

from bundles.canonical_bundle import build_canonical_bundle
from core.metadata_v3 import deterministic_product_title
from core.package_resolution import apply_package_candidate
from metadata_manager import load_or_create, save_admin_override
from orchestrator.adapter import sync_phase3_metadata
from phase2.resolver_v43 import extract_html_package
from phase4.publisher_state import PublisherStateStore, REQUIRED_STEPS
from reporting.excel_report import collect_rows


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase3_llm_schema_forbids_product_title_and_title_is_programmatic():
    root = Path(__file__).resolve().parents[1]
    schema = read_json(root / "schema" / "agent_output.schema.json")
    assert "product_title" not in schema["properties"]
    agent = {
        "product_title": "LLM should not own this",
        "seo_title": "seo",
        "meta_description": "meta",
        "body_markdown": "body",
        "image_alts": [],
        "internal_links": [],
        "external_links": [],
        "woocommerce_attributes": {"part_number": "TBA120S", "package_installation": "DIP-14"},
    }
    errors = list(Draft202012Validator(schema).iter_errors(agent))
    assert errors
    assert deterministic_product_title("TBA120S") == "آی سی TBA120S"


def test_phase2_html_package_extraction_is_explicit_and_rejects_sales_packaging():
    soup = BeautifulSoup("<table><tr><th>Package / Case</th><td>SDIP24-P-300-1.78</td></tr></table>", "html.parser")
    value, label = extract_html_package(soup)
    assert value == "SDIP24-P-300-1.78"
    assert label == "Package / Case"

    soup = BeautifulSoup("<table><tr><th>Package</th><td>Reel</td></tr></table>", "html.parser")
    assert extract_html_package(soup) == ("", "")


def _make_v3_meta(root: Path, pn: str):
    (root / "metadata").mkdir(parents=True, exist_ok=True)
    meta_path, data = load_or_create(root, pn)
    data["part_number"] = pn
    data["product_title"] = f"آی سی {pn}"
    data["source_reference"] = pn
    return meta_path, data


def test_phase3_package_fallback_fills_missing_but_never_overwrites_phase2(tmp_path):
    pn = "PKG100"
    meta_path, data = _make_v3_meta(tmp_path, pn)
    data["datasheet"].update({"status": "completed", "verified_exact_match": True})
    save_admin_override(meta_path, data)

    p3_dir = tmp_path / "phase3_outputs"
    p3_dir.mkdir()
    p3_path = p3_dir / f"{pn}.json"
    p3_path.write_text(json.dumps({
        "identity": {"part_number": pn},
        "source": {"fact_status": "COMPLETED"},
        "woocommerce": {"attributes": {"package_installation": "DIP-14"}},
        "content": {},
        "validation": {"final_seo_score": 85, "publishable": True},
        "tone_editor": {"status": "PASS"},
    }, ensure_ascii=False), encoding="utf-8")

    synced = sync_phase3_metadata(tmp_path, meta_path, p3_path)
    assert synced["package"]["value"] == "DIP-14"
    assert synced["package"]["source"] == "datasheet_pdf"
    assert synced["package"]["resolved_by"] == "phase3"
    assert synced["phase3"]["package_fallback_attempted"] is True

    # A stronger Phase-2 value is canonical and cannot be overwritten by Phase 3.
    data = read_json(meta_path)
    assert apply_package_candidate(
        data,
        value="QFN-48",
        source="mouser",
        resolved_by="phase2",
        exact_part_number_match=True,
        attribute_name="Package / Case",
    ) is True
    save_admin_override(meta_path, data)
    p3 = read_json(p3_path)
    p3["woocommerce"]["attributes"]["package_installation"] = "DIP-14"
    p3_path.write_text(json.dumps(p3, ensure_ascii=False), encoding="utf-8")
    synced = sync_phase3_metadata(tmp_path, meta_path, p3_path)
    assert synced["package"]["value"] == "QFN-48"
    assert synced["package"]["source"] == "mouser"
    assert synced["package"]["resolved_by"] == "phase2"
    assert synced["phase3"]["package_fallback_attempted"] is False


def _prepare_bundle_source(root: Path, pn: str, *, datasheet_status="not_found_confirmed"):
    for folder in ("metadata", "Final", "phase3_outputs", "datasheets", "ready_for_upload"):
        (root / folder).mkdir(parents=True, exist_ok=True)
    meta_path, data = _make_v3_meta(root, pn)
    image = root / "Final" / f"{pn}.webp"
    image.write_bytes(b"not-empty-image")
    data["image_optimization"].update({"status": "completed", "file": f"Final/{pn}.webp"})
    data["package"].update({
        "value": "DIP-14", "status": "resolved", "source": "datasheet_pdf",
        "resolved_by": "phase3", "exact_part_number_match": True,
    })
    data["datasheet"].update({"status": datasheet_status, "verified_exact_match": datasheet_status == "completed"})
    if datasheet_status == "completed":
        pdf = root / "datasheets" / f"{pn}.pdf"
        pdf.write_bytes(b"%PDF-1.4\n%stub")
        data["datasheet"]["file"] = f"datasheets/{pn}.pdf"
    data["admin_audit"].update({"status": "APPROVED", "classification": "FINALIZED", "last_decision_at": "2026-09-15T00:00:00Z"})
    data["publishing"]["release_allowed"] = True

    p3_json = root / "phase3_outputs" / f"{pn}.json"
    p3_json.write_text(json.dumps({
        "identity": {"part_number": pn},
        "snippet": {"seo_title": f"خرید {pn}", "meta_description": "meta"},
        "validation": {"final_seo_score": 84, "publishable": True},
    }, ensure_ascii=False), encoding="utf-8")
    html = root / "phase3_outputs" / f"{pn}.html"
    html.write_text(f"<p>پاراگراف اول {pn}</p><p>ادامه</p>", encoding="utf-8")
    data["phase3"].update({
        "status": "completed", "content_status": "completed", "json_file": f"phase3_outputs/{pn}.json",
        "content_file": f"phase3_outputs/{pn}.html",
    })
    save_admin_override(meta_path, data)
    return meta_path


def test_canonical_bundle_is_approved_snapshot_with_exact_title_category_and_optional_pdf(tmp_path):
    pn = "TBA120S"
    meta_path = _prepare_bundle_source(tmp_path, pn, datasheet_status="not_found_confirmed")
    bundle = build_canonical_bundle(tmp_path, meta_path)
    product = read_json(bundle / "product.json")
    assert product["product_title"] == "آی سی TBA120S"
    assert product["package"] == "DIP-14"
    assert product["image"]["alt"] == "آی سی TBA120S"
    assert product["image"]["media_title"] == "TBA120S"
    assert product["datasheet"] == {
        "status": "not_found_confirmed", "file": None,
        "verified_exact_match": False, "sha256": None,
    }
    assert product["wordpress"]["category"] == {"parent": "قطعات الکترونیکی", "child": "آی سی"}
    assert product["wordpress"]["publish_mode"] == "DRAFT"


def test_publisher_state_is_per_product_duplicate_safe_and_report_success_is_strict(tmp_path):
    pn = "PUB100"
    meta_path, data = _make_v3_meta(tmp_path, pn)
    save_admin_override(meta_path, data)
    store = PublisherStateStore(tmp_path)
    store.begin(pn)
    for step in REQUIRED_STEPS:
        store.record_step(pn, step, success=True)
    state = store.finalize_draft(pn, post_id="123", edit_url="https://example.test/wp-admin/post.php?post=123&action=edit")
    assert state["status"] == "DRAFT_SAVED"
    assert state["successful"] is True
    guarded, guarded_state = store.duplicate_guard(pn)
    assert guarded is True
    assert guarded_state["wordpress_product_id"] == "123"

    row = next(r for r in collect_rows(tmp_path) if r[0] == pn)
    assert row[-1] == "successful"

    # One required Publisher step failing makes the single Phase-4 report status unsuccessful.
    store.record_step(pn, "category", success=False, error="category changed")
    state = store.finalize_draft(pn, post_id="123", edit_url="https://example.test/wp-admin/post.php?post=123&action=edit")
    assert state["status"] == "DRAFT_SAVED_WITH_WARNINGS"
    assert state["successful"] is False
    row = next(r for r in collect_rows(tmp_path) if r[0] == pn)
    assert row[-1] == "unsuccessful"


def test_publisher_source_uses_canonical_bundles_category_and_never_clicks_publish():
    root = Path(__file__).resolve().parents[1]
    text = (root / "phase4" / "publisher.py").read_text(encoding="utf-8")
    assert "ready_for_upload" in text
    assert "قطعات الکترونیکی" in text
    assert '"آی سی"' in text or "'آی سی'" in text
    assert "set_product_category" in text
    assert "#save-post" in text
    # Comments may mention #publish, but there must be no executable click on it.
    assert 'locator("#publish").click' not in text
    assert "page.click('#publish')" not in text
    assert 'page.click("#publish")' not in text


def test_v31_unresolved_package_is_publishable_with_part_number_only_and_report_flags_package(tmp_path):
    from openpyxl import load_workbook
    from phase4.publisher import build_bundle as load_publisher_bundle
    from reporting.excel_report import generate_report

    pn = "NOPKG100"
    meta_path = _prepare_bundle_source(tmp_path, pn, datasheet_status="not_found_confirmed")
    meta = read_json(meta_path)
    meta["package"] = {
        "value": None,
        "source": None,
        "attribute_name": None,
        "status": "unresolved",
        "resolved_by": None,
        "exact_part_number_match": False,
        "sources_tried": [],
        "updated_at": None,
    }
    save_admin_override(meta_path, meta)

    bundle_dir = build_canonical_bundle(tmp_path, meta_path)
    product = read_json(bundle_dir / "product.json")
    assert product["package"] is None
    assert product["package_status"] == "unresolved"

    publisher_bundle = load_publisher_bundle(bundle_dir)
    assert publisher_bundle.package is None

    store = PublisherStateStore(tmp_path)
    store.begin(pn)
    for step in REQUIRED_STEPS:
        store.record_step(pn, step, success=True)
    state = store.finalize_draft(
        pn,
        post_id="321",
        edit_url="https://example.test/wp-admin/post.php?post=321&action=edit",
    )
    assert state["successful"] is True

    row = next(r for r in collect_rows(tmp_path) if r[0] == pn)
    package_col = HEADERS.index("P2 Package") if False else 8
    assert row[package_col] == "unresolved"
    assert row[-1] == "successful"

    report = generate_report(tmp_path, tmp_path / "reports")
    wb = load_workbook(report)
    ws = wb["Pipeline Report"]
    headers = [cell.value for cell in ws[1]]
    p2_col = headers.index("P2 Package") + 1
    p4_col = headers.index("Phase 4") + 1
    assert ws.cell(2, p2_col).value == "unresolved"
    assert ws.cell(2, p4_col).value == "successful"
    assert ws.cell(2, p2_col).fill.fgColor.rgb in {"00FFC7CE", "FFC7CE"}
    assert ws.cell(2, p4_col).fill.fgColor.rgb in {"00C6EFCE", "C6EFCE"}


def test_v31_publisher_attributes_explicitly_support_part_number_only_when_package_unresolved():
    from phase4.publisher import ProductBundle, _attribute_pairs
    from pathlib import Path
    # Non-MOSFET unresolved package: only Part Number, as V3.1 requires.
    bundle = ProductBundle(
        pn="DUMMY", title="آی سی DUMMY", package=None,
        html_path=Path("example.html"), html="<p>example</p>",
        short_description_html="text", image_path=Path("image.png"),
        datasheet_path=None, datasheet_status="not_found_confirmed",
        product_json_path=Path("product.json"), category_key="ic",
        category_parent="قطعات الکترونیکی", category_child="آی سی",
        category_parent_term_id=110, category_term_id=113,
        slug="dummy-ic", seo_title="title", meta_description="text",
    )
    assert _attribute_pairs(bundle) == ([("Part Number", "DUMMY")], [])
