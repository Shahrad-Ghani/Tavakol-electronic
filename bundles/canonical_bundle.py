from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from core.metadata_v3 import deterministic_product_title, get_category_key, get_part_number, utcnow
from core.category_registry import category_context, product_slug
from phase3_fact_extraction.mosfet_specs import resolve_for_product
from core.category_integrity import (
    CategoryConsistencyError,
    assert_bundle_category_consistency,
    assert_upstream_category_consistency,
)
from metadata_manager import portable_path, resolve_recorded_path, save_admin_override
from phase2.banner_injector import has_banner

BUNDLE_CONTRACT_VERSION = "4.0"


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _first_paragraph(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    p = soup.find("p")
    if p is None or not p.get_text(" ", strip=True):
        raise ValueError("Phase 3 HTML has no non-empty first paragraph")
    return str(p).strip()


def invalidate_bundle(root: Path, metadata_path: Path, data: dict[str, Any], *, reason: str) -> None:
    """Invalidate a previously approved publisher snapshot without destroying history."""
    root = Path(root).resolve()
    pn = get_part_number(data)
    pub = data.setdefault("publishing", {})
    old_path = pub.get("bundle_path") or (data.get("admin_audit") or {}).get("ready_bundle")
    if old_path:
        candidate = resolve_recorded_path(root, str(old_path))
    else:
        candidate = root / "ready_for_upload" / pn if pn else None
    if candidate and candidate.exists():
        archive = root / "audit_history" / "invalidated_bundles" / f"{utcnow().replace(':','').replace('-','')}_{pn or 'UNKNOWN'}"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            shutil.rmtree(archive)
        shutil.move(str(candidate), str(archive))
    pub.update({
        "bundle_status": "INVALIDATED",
        "bundle_path": None,
        "status": "NOT_STARTED",
        "successful": None,
        "wordpress_product_id": None,
        "wordpress_edit_url": None,
        "completed_with_warnings": False,
        "step_errors": {},
        "updated_at": utcnow(),
    })
    audit = data.setdefault("admin_audit", {})
    audit["ready_bundle"] = None
    audit.setdefault("history", []).append({"action": "BUNDLE_INVALIDATED", "at": utcnow(), "reason": reason})
    save_admin_override(metadata_path, data)


def build_canonical_bundle(root: Path, metadata_path: Path, data: dict[str, Any] | None = None) -> Path:
    """Create the immutable-ish approved snapshot consumed by Phase 4.

    Publisher V3 is forbidden from discovering fields in legacy runtime folders. All
    values and local files needed for publication are copied/declared here.
    """
    root = Path(root).resolve()
    metadata_path = Path(metadata_path).resolve()
    if data is None:
        data = _read_json(metadata_path)

    pn = get_part_number(data)
    if not pn:
        raise RuntimeError("Cannot build canonical bundle without part_number")
    category_key = get_category_key(data)
    category = category_context(category_key)
    title = deterministic_product_title(pn, category_key)
    data["product_title"] = title

    audit = data.get("admin_audit") or {}
    if audit.get("status") != "APPROVED" or audit.get("classification") != "FINALIZED":
        raise RuntimeError("Canonical bundle requires Admin Audit APPROVED + FINALIZED")
    pub = data.setdefault("publishing", {})
    if not bool(pub.get("release_allowed")):
        # metadata_manager canonicalization will set this when audit is approved,
        # but be explicit in this service too.
        pub["release_allowed"] = True
        pub["release_source"] = "ADMIN_AUDIT"

    package = data.get("package") or {}
    package_value = str(package.get("value") or "").strip()
    package_status = "resolved" if package.get("status") == "resolved" and package_value else "unresolved"

    image_recorded = str((data.get("image_optimization") or {}).get("file") or "").strip()
    image_path = resolve_recorded_path(root, image_recorded)
    if not image_path or not image_path.exists() or image_path.stat().st_size <= 0:
        raise RuntimeError("Final product image is missing")

    phase3 = data.get("phase3") or {}
    p3_json = resolve_recorded_path(root, phase3.get("json_file")) if phase3.get("json_file") else root / "phase3_outputs" / f"{pn}.json"
    p3_html = resolve_recorded_path(root, phase3.get("content_file")) if phase3.get("content_file") else root / "phase3_outputs" / f"{pn}.html"
    if not p3_json or not p3_json.exists():
        p3_json = root / "phase3_outputs" / f"{pn}.json"
    if not p3_html or not p3_html.exists():
        p3_html = root / "phase3_outputs" / f"{pn}.html"
    if not p3_json.exists() or not p3_html.exists():
        raise RuntimeError("Phase 3 output JSON/HTML is missing")

    phase3_doc = _read_json(p3_json)
    integrated_path = root / "products" / f"{pn}.json"
    integrated_doc = _read_json(integrated_path) if integrated_path.exists() else None
    integrity = assert_upstream_category_consistency(
        data, phase3=phase3_doc, integrated=integrated_doc
    )
    if integrity.key != category_key:
        raise CategoryConsistencyError(
            f"CATEGORY_CONSISTENCY_ERROR: metadata category changed during bundle build: {category_key!r} -> {integrity.key!r}"
        )
    html = p3_html.read_text(encoding="utf-8")
    if not html.strip():
        raise RuntimeError("Phase 3 HTML is empty")
    snippet = phase3_doc.get("snippet") or {}
    short_description = str(snippet.get("meta_description") or "").strip() or _first_paragraph(html)
    if not short_description:
        raise RuntimeError("Phase 3 canonical meta description is missing")

    ds = data.get("datasheet") or {}
    ds_status = str(ds.get("status") or "pending")
    datasheet_path: Path | None = None
    if ds.get("file"):
        datasheet_path = resolve_recorded_path(root, str(ds.get("file")))
        if datasheet_path and (not datasheet_path.exists() or datasheet_path.stat().st_size <= 0):
            datasheet_path = None
    if ds_status == "completed" and datasheet_path is None:
        raise RuntimeError("Datasheet status is completed but PDF file is missing")
    # Phase 2's exact source PDF remains pristine for technical extraction.
    # Publication uses a separately branded copy only when its marker verifies.
    if datasheet_path is not None:
        branded_candidate = root / "datasheets_branded" / f"{pn}.pdf"
        if branded_candidate.is_file() and has_banner(branded_candidate):
            datasheet_path = branded_candidate
    if ds_status == "sales_only_no_datasheet":
        if not bool(ds.get("sales_only_authorized")) or datasheet_path is not None:
            raise RuntimeError("Sales-only without datasheet requires explicit admin authorization and no PDF")
    elif ds_status not in {"completed", "not_found_confirmed"}:
        raise RuntimeError(f"Datasheet is not terminal for publishing: {ds_status!r}")

    bundle = root / "ready_for_upload" / pn
    tmp_bundle = root / "ready_for_upload" / f".{pn}.building"
    if tmp_bundle.exists():
        shutil.rmtree(tmp_bundle)
    tmp_bundle.mkdir(parents=True, exist_ok=True)

    image_dest = tmp_bundle / f"{pn}{image_path.suffix.lower()}"
    shutil.copy2(image_path, image_dest)
    html_dest = tmp_bundle / "product.html"
    html_dest.write_text(html, encoding="utf-8")

    pdf_name = None
    if datasheet_path is not None:
        pdf_name = f"{pn}.pdf"
        shutil.copy2(datasheet_path, tmp_bundle / pdf_name)

    mosfet_specs = resolve_for_product(root, pn, category_key)
    if category_key == 'mosfet':
        data.setdefault('phase3', {})['mosfet_specs'] = mosfet_specs
    validation = phase3_doc.get("validation") or {}
    seo = phase3_doc.get("seo") or {}
    snippet = phase3_doc.get("snippet") or {}
    product_json = {
        "contract_version": BUNDLE_CONTRACT_VERSION,
        "part_number": pn,
        "product_type": category_key,
        "category": category,
        "product_title": title,
        "manufacturer": data.get("manufacturer") or ds.get("manufacturer"),
        "country": data.get("country") or ds.get("manufacturer_country"),
        "package": package_value or None,
        "package_status": package_status,
        "mosfet_specs": mosfet_specs,
        "image": {
            "file": image_dest.name,
            "alt": title,
            "media_title": pn,
            "sha256": _sha256(image_dest),
        },
        "datasheet": {
            "status": ds_status,
            "file": pdf_name,
            "verified_exact_match": bool(ds.get("verified_exact_match")),
            "sha256": _sha256(tmp_bundle / pdf_name) if pdf_name else None,
        },
        "content": {
            "html_file": html_dest.name,
            "short_description_html": short_description,
        },
        "seo": {
            "focus_keyword": pn,
            "permalink": product_slug(pn, category_key),
            "seo_title": snippet.get("seo_title") or snippet.get("title"),
            "meta_description": snippet.get("meta_description"),
            "score": validation.get("final_seo_score"),
            "validator_publishable": validation.get("publishable"),
        },
        "wordpress": {
            "category": {
                "parent": category["wordpress"]["parent"],
                "child": category["wordpress"]["child"],
            },
            "category_key": category_key,
            "category_parent_term_id": category["wordpress"]["parent_term_id"],
            "category_term_id": category["wordpress"]["term_id"],
            "category_url": category["category_url"],
            "publish_mode": "DRAFT",
        },
        "audit": {
            "status": audit.get("status"),
            "classification": audit.get("classification"),
            "approved_at": audit.get("last_decision_at"),
        },
        "release": {
            "allowed": True,
            "source": "ADMIN_AUDIT",
            "bundle_built_at": utcnow(),
        },
    }
    if ds_status == "sales_only_no_datasheet":
        product_json["datasheet"]["sales_only_authorized"] = bool(ds.get("sales_only_authorized"))
    _write_json(tmp_bundle / "product.json", product_json)
    manifest = {
        "contract_version": BUNDLE_CONTRACT_VERSION,
        "part_number": pn,
        "files": {
            "product_json": "product.json",
            "html": "product.html",
            "image": image_dest.name,
            "datasheet": pdf_name,
        },
        "hashes": {
            "product_json": _sha256(tmp_bundle / "product.json"),
            "html": _sha256(html_dest),
            "image": _sha256(image_dest),
            "datasheet": _sha256(tmp_bundle / pdf_name) if pdf_name else None,
        },
        "built_at": utcnow(),
    }
    _write_json(tmp_bundle / "manifest.json", manifest)

    if bundle.exists():
        shutil.rmtree(bundle)
    tmp_bundle.replace(bundle)

    pub.update({
        "release_allowed": True,
        "release_source": "ADMIN_AUDIT",
        "bundle_status": "READY",
        "bundle_path": portable_path(root, bundle),
        "status": "READY",
        "successful": None,
        "updated_at": utcnow(),
    })
    audit["ready_bundle"] = portable_path(root, bundle)
    audit.setdefault("history", []).append({"action": "CANONICAL_BUNDLE_BUILT", "at": utcnow(), "bundle": portable_path(root, bundle)})
    save_admin_override(metadata_path, data)
    return bundle

def prepare_approved_bundles(root: Path) -> dict[str, Any]:
    """Build missing Canonical Bundles for already-approved V3 metadata.

    This is the compatibility bridge for products approved before V3 migration.
    It never guesses missing package/content/image data. An unresolved package is
    allowed in V3.1 and is published without a package attribute; missing content/image
    data still prevents staging. Existing READY bundles are category-validated; a
    stale category snapshot is archived and rebuilt before any WordPress product exists.
    """
    root = Path(root).resolve()
    metadata_dir = root / "metadata"
    ready_dir = root / "ready_for_upload"
    ready_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {"built": [], "rebuilt": [], "existing": [], "errors": {}, "skipped": []}
    for meta_path in sorted(metadata_dir.glob("*.json"), key=lambda x: x.stem.casefold()):
        try:
            data = _read_json(meta_path)
            pn = get_part_number(data) or meta_path.stem
            audit = data.get("admin_audit") or {}
            pub = data.get("publishing") or {}
            approved = audit.get("status") == "APPROVED" and audit.get("classification") == "FINALIZED"
            if not approved:
                result["skipped"].append(pn)
                continue
            # A WordPress product id is the duplicate-prevention boundary. Do not
            # rebuild release snapshots for already-created products.
            if pub.get("wordpress_product_id"):
                result["skipped"].append(pn)
                continue
            p3_path = root / "phase3_outputs" / f"{pn}.json"
            integrated_path = root / "products" / f"{pn}.json"
            p3_doc = _read_json(p3_path) if p3_path.exists() else None
            integrated_doc = _read_json(integrated_path) if integrated_path.exists() else None
            integrity = assert_upstream_category_consistency(
                data, phase3=p3_doc, integrated=integrated_doc
            )

            bundle = ready_dir / pn
            bundle_product_path = bundle / "product.json"
            if bundle_product_path.exists() and pub.get("bundle_status") == "READY":
                try:
                    existing_product = _read_json(bundle_product_path)
                    assert_bundle_category_consistency(existing_product, expected_key=integrity.key)
                    result["existing"].append(pn)
                    continue
                except CategoryConsistencyError as exc:
                    # Safe auto-rebuild boundary: no WordPress product exists yet.
                    archive = root / "audit_history" / "stale_category_bundles" / f"{utcnow().replace(':','').replace('-','')}_{pn}"
                    archive.parent.mkdir(parents=True, exist_ok=True)
                    if archive.exists():
                        shutil.rmtree(archive)
                    shutil.move(str(bundle), str(archive))
                    pub["bundle_status"] = "INVALIDATED"
                    pub["bundle_path"] = None
                    data.setdefault("admin_audit", {}).setdefault("history", []).append({
                        "action": "STALE_CATEGORY_BUNDLE_INVALIDATED",
                        "at": utcnow(),
                        "reason": str(exc),
                        "archive": portable_path(root, archive),
                    })
                    save_admin_override(meta_path, data)
                    result.setdefault("rebuilt", []).append(pn)
            build_canonical_bundle(root, meta_path, data)
            result["built"].append(pn)
        except Exception as exc:
            result["errors"][meta_path.stem] = f"{type(exc).__name__}: {exc}"
    return result

