from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from pathlib import Path

from jsonschema import Draft202012Validator

from core.metadata_v3 import deterministic_product_title, get_category_key, get_part_number, get_source_reference, image_finalized, utcnow
from core.package_resolution import apply_package_candidate, needs_phase3_package_fallback
from core.category_registry import category_context, product_slug
from core.category_integrity import assert_upstream_category_consistency
from metadata_manager import save_phase3 as save_metadata


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _portable(root: Path, value):
    if not value:
        return None
    p = Path(str(value))
    if not p.is_absolute():
        p = root / p
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(value).replace("\\", "/")


def _resolve(root: Path, value):
    if not value:
        return None
    p = Path(str(value))
    return p if p.is_absolute() else (root / p).resolve()


def _internal_links(root: Path, category: str) -> list[dict]:
    ctx = category_context(category)
    anchors = ctx.get("internal_link", {}).get("anchor_variants") or [
        f"خرید {ctx['display_name']}", f"انواع {ctx['display_name']}", ctx['display_name']
    ]
    return [{"url": ctx["category_url"], "anchor_hint": anchors[0]}]


def build_phase3_input(root: Path, metadata_path: Path) -> tuple[Path, dict]:
    root = Path(root)
    meta = read_json(metadata_path)
    pn = get_part_number(meta)
    if not pn:
        raise ValueError("Phase3 input cannot be built without PartNumber")
    ds = meta.get("datasheet") or {}
    if str(ds.get("status") or "") == "manual_required":
        raise RuntimeError("Phase3 is blocked: datasheet status is manual_required; admin must attach the PDF first")
    if str(ds.get("status") or "") == "web_error":
        raise RuntimeError("Phase3 blocked: web_error requires explicit admin decision")
    if str(ds.get("status") or "") == "sales_only_no_datasheet":
        if not bool(ds.get("sales_only_authorized")) or ds.get("file") or (root / "datasheets" / f"{pn}.pdf").exists():
            raise RuntimeError("Sales-only route requires admin authorization and no exact PDF")
    final_image = meta.get("image_optimization", {}).get("file") or f"Final/{pn}.webp"
    filename = Path(str(final_image)).name if final_image else f"{pn}.webp"
    category_key = get_category_key(meta)
    ctx = category_context(category_key)
    data = {
        "schema_version": "phase3-final-input-v0.2",
        "identity": {
            "part_number": pn,
            "manufacturer": meta.get("manufacturer") or ds.get("manufacturer"),
            "product_type_label": ctx["display_name"],
            "product_category": category_key,
            # Mouser package is deliberately not promoted to FINAL_FACTS truth.
            # Phase3 may fill this only from its exact datasheet fact extraction.
            "verified_package_installation": None,
        },
        "images": [{
            "filename": filename,
            "path": _portable(root, final_image),
            "is_primary": True,
        }],
        "seo_context": {
            "approved_internal_links": _internal_links(root, category_key),
            "approved_external_links": [],
        },
        "source_hint": {
            "datasheet_status": str(ds.get("status") or "pending"),
            "datasheet_path": _portable(root, ds.get("file")),
            "phase2_verified_exact_match": bool(ds.get("verified_exact_match")),
            "phase2_package": deepcopy(meta.get("package") or {}),
        },
    }
    out = root / "work" / "phase3_inputs" / f"{pn}.json"
    atomic_json(out, data)
    return out, data


def _norm_package(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def reconcile_package(meta: dict, phase3: dict | None) -> dict:
    """Compatibility view for integrated_product schema; canonical value lives in metadata.package."""
    pkg = meta.get("package") or {}
    p2 = pkg.get("value") if pkg.get("resolved_by") == "phase2" else None
    p3 = None
    if phase3:
        p3 = ((phase3.get("woocommerce") or {}).get("attributes") or {}).get("package_installation")
        if p3 == "نیازمند تأیید":
            p3 = None
    value = pkg.get("value") or p3
    if p2 and p3 and _norm_package(p2) == _norm_package(p3):
        status = "CONFIRMED_MOUSER_AND_DATASHEET" if pkg.get("source") == "mouser" else "DATASHEET_VERIFIED"
    elif p2 and p3:
        status = "CONFLICT_REVIEW"
    elif p2:
        status = "MOUSER_EXACT_ONLY" if pkg.get("source") == "mouser" else "DATASHEET_VERIFIED"
    elif value:
        status = "DATASHEET_VERIFIED"
    else:
        status = "UNKNOWN"
    return {"value": value, "status": status, "phase2_mouser": p2 if pkg.get("source") == "mouser" else None,
            "phase3_datasheet": p3}

def sync_phase3_metadata(root: Path, metadata_path: Path, phase3_json_path: Path) -> dict:
    """Write Phase-3 canonical summary and package fallback into Metadata V3."""
    meta = read_json(metadata_path)
    p3 = read_json(phase3_json_path)
    pn = get_part_number(meta)
    if not pn or str((p3.get("identity") or {}).get("part_number") or "").casefold() != pn.casefold():
        raise ValueError("Phase3/metadata Part Number mismatch")
    package_fallback_attempted = False
    if needs_phase3_package_fallback(meta):
        package_fallback_attempted = True
        candidate = ((p3.get("woocommerce") or {}).get("attributes") or {}).get("package_installation")
        if candidate and candidate != "نیازمند تأیید":
            apply_package_candidate(meta, value=candidate, source="datasheet_pdf", resolved_by="phase3",
                                    exact_part_number_match=bool((meta.get("datasheet") or {}).get("verified_exact_match")))
    html_rel = None
    html_name = (p3.get("content") or {}).get("html_path")
    if html_name:
        html_rel = _portable(root, phase3_json_path.parent / str(html_name))
    validation = p3.get("validation") or {}
    integrity = assert_upstream_category_consistency(meta, phase3=p3)
    category_key = integrity.key
    meta["product_title"] = deterministic_product_title(pn, category_key)
    meta["phase3"].update({
        "status": "completed",
        "facts_status": str((p3.get("source") or {}).get("fact_status") or "NOT_RUN"),
        "content_status": "completed",
        "json_file": _portable(root, phase3_json_path),
        "content_file": html_rel,
        "seo_score": validation.get("final_seo_score"),
        "validator_publishable": validation.get("publishable"),
        "tone_status": (p3.get("tone_editor") or {}).get("status"),
        "seo_agent_status": (p3.get("seo_snippet_agent") or {}).get("status"),
        "seo_title": (p3.get("snippet") or {}).get("seo_title"),
        "meta_description": (p3.get("snippet") or {}).get("meta_description"),
        "slug": (p3.get("page") or {}).get("slug"),
        "semantic_audit_status": (validation.get("final_semantic_audit") or {}).get("status"),
        "package_fallback_attempted": package_fallback_attempted,
        "updated_at": utcnow(),
    })
    save_metadata(metadata_path, meta)
    return meta


def _phase1_status(meta: dict) -> str:
    if image_finalized(meta):
        return "COMPLETED"
    if get_part_number(meta):
        return "PN_READY"
    return "IN_PROGRESS"


def _validate_document(document: dict, schema_path: Path, label: str) -> None:
    schema = read_json(schema_path)
    errors = sorted(Draft202012Validator(schema).iter_errors(document), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        loc = ".".join(str(x) for x in first.path) or "<root>"
        raise ValueError(f"{label} schema validation failed at {loc}: {first.message}")


def build_integrated_product(root: Path, metadata_path: Path, phase3_json_path: Path | None, runtime_state: dict | None = None) -> tuple[Path, dict]:
    root = Path(root)
    meta = read_json(metadata_path)
    _validate_document(meta, root / "metadata_schema.json", "Phase1+2 metadata")
    p3 = read_json(phase3_json_path) if phase3_json_path and Path(phase3_json_path).exists() else None
    if p3 is not None:
        _validate_document(p3, root / "schema" / "phase3_final_product.schema.json", "Phase3 product")
    pn = get_part_number(meta) or str((p3 or {}).get("identity", {}).get("part_number") or "").strip()
    if not pn:
        raise ValueError("Integrated product requires PartNumber")
    integrity = assert_upstream_category_consistency(meta, phase3=p3) if p3 is not None else assert_upstream_category_consistency(meta)
    category_key = integrity.key
    ds = deepcopy(meta.get("datasheet") or {})
    package = reconcile_package(meta, p3)
    final_image = meta.get("image_optimization", {}).get("file")
    primary_alt = None
    if p3 and p3.get("images"):
        primary = next((x for x in p3["images"] if x.get("is_primary")), p3["images"][0])
        primary_alt = primary.get("alt")

    p3_html = (p3 or {}).get("content", {}).get("html_path")
    if p3_html and phase3_json_path:
        p3_html = _portable(root, Path(phase3_json_path).parent / str(p3_html))
    wc_attributes = deepcopy((p3 or {}).get("woocommerce", {}).get("attributes") or {})
    if package.get("value"):
        wc_attributes["package_installation"] = package.get("value")
    preview = {
        "target": (p3 or {}).get("publishing", {}).get("target") or "woocommerce",
        "publish_mode": (p3 or {}).get("publishing", {}).get("publish_mode") or "DRAFT",
        "product_title": deterministic_product_title(pn, category_key),
        "slug": (p3 or {}).get("page", {}).get("slug") or product_slug(pn, category_key),
        "focus_keyword": (p3 or {}).get("seo", {}).get("focus_keyword"),
        "seo_title": (p3 or {}).get("snippet", {}).get("seo_title"),
        "meta_description": (p3 or {}).get("snippet", {}).get("meta_description"),
        "primary_image_alt": deterministic_product_title(pn, category_key),
        "primary_image_path": _portable(root, final_image),
        "description_html_path": p3_html,
        "package_installation": package.get("value"),
        "woocommerce_attributes": wc_attributes,
        "internal_links": deepcopy((p3 or {}).get("links", {}).get("internal") or []),
    }
    integrated = {
        "schema_version": "tavakol-integrated-product-v1",
        "product_id": str(meta.get("product_id") or pn),
        "identity": {
            "part_number": pn,
            "manufacturer": meta.get("manufacturer") or ds.get("manufacturer"),
            "manufacturer_country": meta.get("country") or ds.get("manufacturer_country"),
            "category": category_key,
            # V4.0.2 regression reference: "category_context": category_context(get_category_key(meta))
            "category_context": category_context(category_key),
            "package": package,
        },
        "phase1": {
            "status": _phase1_status(meta),
            "source_reference": get_source_reference(meta),
            "part_number_ocr": deepcopy(meta.get("ocr") or {}),
            "identity_validation": deepcopy(meta.get("identity_validation") or {}),
            "final_image": _portable(root, final_image),
            "image_optimization": deepcopy(meta.get("image_optimization") or {}),
            "api_accounting": deepcopy((meta.get("diagnostics") or {}).get("api_accounting") or {}),
            "metadata_path": _portable(root, metadata_path),
        },
        "phase2": {
            "status": str(ds.get("status") or "pending"),
            "verified_exact_match": bool(ds.get("verified_exact_match")),
            "manufacturer": ds.get("manufacturer"),
            "manufacturer_country": ds.get("manufacturer_country"),
            "datasheet_path": _portable(root, ds.get("file")),
            "document_source": ds.get("document_source"),
            "source_url": ds.get("source_url"),
            "package": deepcopy(meta.get("package") or {}),
            "ambiguity_flag": ds.get("ambiguity_flag"),
            "source_trace": deepcopy(ds.get("source_trace") or []),
            "last_error": ds.get("last_error"),
        },
        "phase3": p3,
        "publishing_preview": preview,
        "orchestration": deepcopy(runtime_state or {}),
    }
    assert_upstream_category_consistency(meta, phase3=p3, integrated=integrated)
    _validate_document(integrated, root / "schema" / "integrated_product.schema.json", "Integrated product")
    out = root / "products" / f"{pn}.json"
    atomic_json(out, integrated)
    return out, integrated
