from __future__ import annotations

import json
import re
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from bundles.canonical_bundle import build_canonical_bundle, invalidate_bundle
from core.metadata_v3 import deterministic_product_title, get_category_key, get_part_number, get_source_reference, sync_category
from core.category_registry import category_context
from core.category_integrity import assert_upstream_category_consistency
from core.category_integrity import CategoryConsistencyError, assert_upstream_category_consistency

from metadata_manager import (
    load_or_create,
    portable_path,
    rename_metadata_to_partnumber,
    resolve_recorded_path,
    save,
    save_admin_override,
    save_audit_phase_state,
    utc_now,
)

SUPPORTED_IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
P2_TERMINAL = {"completed", "not_found_confirmed", "identity_found_unresolved", "sales_only_no_datasheet"}
ISSUES = {
    "wrong_part_number",
    "image_regeneration_needed",
    "wrong_data_sheet",
    "seo_content_regeneration_needed",
}


def _read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _safe_pn(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", "", str(value or "")).strip().strip(" .")
    if not value:
        raise ValueError("PartNumber is empty")
    if any(ch in value for ch in '<>:"/\\|?*'):
        raise ValueError("PartNumber contains characters invalid for a Windows filename")
    return value


def _find_original(root: Path, data: dict) -> Path | None:
    original = data.get("original_image") or {}
    if isinstance(original, dict):
        recorded = original.get("file")
        if recorded:
            path = resolve_recorded_path(root, recorded)
            if path and path.exists():
                return path
    ref = str(data.get("source_reference") or "").strip()
    for folder in (root / "input_PN", root / "PN_input", root / "input"):
        if not folder.exists():
            continue
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGES and p.stem.casefold() == ref.casefold():
                return p
    return None


def _find_final(root: Path, data: dict) -> Path | None:
    recorded = str((data.get("image_optimization") or {}).get("file") or "").strip()
    if recorded:
        p = resolve_recorded_path(root, recorded)
        if p and p.exists():
            return p
        fallback = root / "Final" / Path(recorded.replace("\\", "/")).name
        if fallback.exists():
            return fallback
    pn = str(data.get("part_number") or "").strip()
    if pn:
        p = root / "Final" / f"{pn}.webp"
        if p.exists():
            return p
    return None


def _find_candidate(root: Path, data: dict) -> Path | None:
    ref = str(data.get("source_reference") or "").strip()
    pn = str(data.get("part_number") or "").strip()
    candidates = []
    for stem in (ref, pn):
        if not stem:
            continue
        candidates.extend([
            root / "output" / f"{stem}_canvas.png",
            root / "output" / f"{stem}_regen.png",
            root / "output" / f"{stem}.png",
        ])
    for p in candidates:
        if p.exists():
            return p
    return None


def _phase3_state(root: Path, pn: str) -> tuple[Path | None, dict | None]:
    if not pn:
        return None, None
    path = root / "phase3_outputs" / f"{pn}.json"
    if not path.exists():
        return None, None
    try:
        return path, _read_json(path)
    except Exception:
        return path, None


def _seo_summary(state: dict | None) -> dict:
    if not state:
        return {
            "available": False,
            "score": None,
            "seo_status": None,
            "disposition": None,
            "publishable": False,
            "keyword_density": None,
            "keyword_density_target": None,
            "word_count": None,
            "word_count_target": None,
            "structure_pass": None,
            "fact_safety_pass": None,
            "semantic_audit_status": None,
            "tone_status": None,
            "tone_naturalness": None,
        }
    validation = state.get("validation") or {}
    structure = validation.get("structure_contract") or {}
    measured = structure.get("measured") or {}
    safety = validation.get("fact_safety") or {}
    semantic = validation.get("final_semantic_audit") or {}
    scorecard = state.get("evaluation_scorecard") or {}
    tone = scorecard.get("tone") or {}
    return {
        "available": True,
        "score": validation.get("final_seo_score"),
        "seo_status": validation.get("seo_status"),
        "disposition": validation.get("disposition"),
        "publishable": bool(validation.get("publishable")),
        "keyword_density": measured.get("keyword_density"),
        "keyword_density_target": measured.get("keyword_density_target"),
        "word_count": measured.get("word_count"),
        "word_count_target": measured.get("word_count_target"),
        "structure_pass": structure.get("passed"),
        "fact_safety_pass": safety.get("passed"),
        "semantic_audit_status": semantic.get("status"),
        "tone_status": tone.get("status"),
        "tone_naturalness": tone.get("naturalness_score"),
    }


def _datasheet_summary(root: Path, data: dict) -> dict:
    ds = data.get("datasheet") or {}
    recorded = str(ds.get("file") or "").strip()
    pdf = None
    if recorded:
        p = resolve_recorded_path(root, recorded)
        if p and p.exists():
            pdf = p
        else:
            fallback = root / "datasheets" / Path(recorded.replace("\\", "/")).name
            if fallback.exists():
                pdf = fallback
    status = str(ds.get("status") or "pending")
    return {
        "status": status,
        "found": bool(pdf and status == "completed"),
        "pdf_name": pdf.name if pdf else None,
        "pdf_path": str(pdf) if pdf else None,
        "verified_exact_match": bool(ds.get("verified_exact_match")),
    }


def diagnose_audit(root: Path, data: dict, p3_state: dict | None) -> list[dict]:
    """Return actionable, non-mutating current-state diagnostics, not historical failure strings."""
    pn = str(data.get('part_number') or '').strip()
    problems = []
    def add(code, detail, action):
        problems.append({'code': code, 'detail': detail, 'action': action})
    if not pn:
        add('PART_NUMBER_MISSING', 'No canonical Part Number is confirmed.', 'Review original marking / correct PN')
        return problems
    final = _find_final(root, data)
    if not final:
        iv = data.get('identity_validation') or {}
        if str(iv.get('status') or '').lower() in ('rejected', 'failed', 'retry_required'):
            add('IMAGE_IDENTITY_REJECTED', 'Validator rejected image: ' + str(iv.get('rejection_reasons') or iv.get('issues') or iv.get('last_error') or 'unspecified'),
                'Review candidate and click Accept Image, or request regeneration')
        else:
            add('FINAL_IMAGE_MISSING', f'Final/{pn}.webp is missing or metadata does not reference it.', 'Complete Phase 1 or accept candidate in Audit')
    ds = data.get('datasheet') or {}
    ds_status = str(ds.get('status') or 'pending')
    if ds_status not in P2_TERMINAL:
        action = 'Attach exact PDF or authorize Sales-only in Audit' if ds_status == 'web_error' else 'Complete/resume Phase 2 or attach exact PDF'
        add('DATASHEET_'+ds_status.upper(), f'Current datasheet status: {ds_status}; last_error={ds.get("last_error") or "none"}', action)
    if ds_status == 'sales_only_no_datasheet' and not ds.get('sales_only_authorized'):
        add('SALES_ONLY_NOT_AUTHORIZED', 'Sales-only continuation has no explicit admin authorization.', 'Review datasheet decision')
    if not p3_state:
        add('PHASE3_OUTPUT_MISSING', f'phase3_outputs/{pn}.json is missing.', 'Press Start to resume the pending Phase 3 job')
    product_path = root / 'products' / f'{pn}.json'
    if not product_path.is_file():
        add('INTEGRATED_PRODUCT_MISSING', f'products/{pn}.json is missing.', 'Rebuild canonical snapshot after completing the phases')
    if p3_state and product_path.is_file():
        try:
            assert_upstream_category_consistency(data, phase3=p3_state, integrated=_read_json(product_path))
        except (CategoryConsistencyError, ValueError, OSError, json.JSONDecodeError) as exc:
            add('CATEGORY_OR_CANONICAL_MISMATCH', str(exc), 'Resolve selected category and rebuild dependent content; never force approval')
    return problems


def _classification(root: Path, data: dict, p3_state: dict | None) -> tuple[str, str]:
    reasons = diagnose_audit(root, data, p3_state)
    if reasons:
        return 'AUDIT_NEEDED', f"{reasons[0]['code']}: {reasons[0]['detail']}"
    return 'FINALIZED', 'Finalized'


def list_audit_items(root: Path) -> list[dict]:
    root = Path(root).resolve()
    items = []
    for meta in sorted((root / "metadata").glob("*.json")):
        try:
            data = _read_json(meta)
        except Exception:
            continue
        pn = str(data.get("part_number") or "").strip()
        p3_path, p3 = _phase3_state(root, pn)
        klass, title = _classification(root, data, p3)
        diagnostics = diagnose_audit(root, data, p3)
        original = _find_original(root, data)
        final = _find_final(root, data)
        candidate = _find_candidate(root, data)
        ds = _datasheet_summary(root, data)
        seo = _seo_summary(p3)
        audit = data.get("admin_audit") or {}
        items.append({
            "metadata_path": str(meta),
            "source_reference": str(data.get("source_reference") or meta.stem),
            "part_number": pn or None,
            "classification": klass,
            "title": title,
            "diagnostics": diagnostics,
            "original_path": str(original) if original else None,
            "final_path": str(final) if final else None,
            "candidate_path": str(candidate) if candidate else None,
            "datasheet": ds,
            "seo": seo,
            "admin_status": str(audit.get("status") or "PENDING_REVIEW"),
            "admin_approved": str(audit.get("status") or "").upper() == "APPROVED",
            "phase3_path": str(p3_path) if p3_path else None,
        })
    # Human attention first, then normal finalized products.
    items.sort(key=lambda x: (0 if x["classification"] == "AUDIT_NEEDED" else 1, x.get("part_number") or x["source_reference"]))
    return items


def _archive_dir(root: Path, source_ref: str, reason: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_ref = re.sub(r"[^A-Za-z0-9._-]+", "_", source_ref or "unknown")
    safe_reason = re.sub(r"[^A-Za-z0-9._-]+", "_", reason or "audit")
    path = root / "audit_history" / f"{stamp}_{safe_ref}_{safe_reason}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _move_if_exists(path: Path, archive: Path, label: str | None = None) -> Path | None:
    if not path.exists():
        return None
    target_dir = archive / (label or "artifacts")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    if target.exists():
        target = target_dir / f"{path.stem}__duplicate{path.suffix}"
    shutil.move(str(path), str(target))
    return target


def _copy_if_exists(path: Path, target_dir: Path) -> Path | None:
    if not path.exists():
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / path.name
    shutil.copy2(path, target)
    return target


def _deep_replace(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new)
    if isinstance(value, list):
        return [_deep_replace(v, old, new) for v in value]
    if isinstance(value, dict):
        return {k: _deep_replace(v, old, new) for k, v in value.items()}
    return value


def _cache_prior_phase3(root: Path, old_pn: str, archive: Path) -> dict:
    cache_dir = archive / "prior_phase3"
    result = {"json": None, "html": None}
    for ext in ("json", "html"):
        p = root / "phase3_outputs" / f"{old_pn}.{ext}"
        copied = _copy_if_exists(p, cache_dir)
        if copied:
            result[ext] = str(copied)
    return result


def _reset_datasheet(data: dict) -> None:
    ds = data.setdefault("datasheet", {})
    defaults = {
        "status": "pending",
        "searched_part_number": None,
        "matched_part_number": None,
        "verified_exact_match": False,
        "identity_status": "NOT_SEARCHED",
        "manufacturer": None,
        "manufacturer_country": None,
        "manufacturer_country_status": "NOT_SEARCHED",
        "identity_source": None,
        "document_source": None,
        "source_url": None,
        "file": None,
        "mouser_part_number": None,
        "ambiguity_flag": None,
        "ambiguity_source": None,
        "alternative_manufacturers": [],
        "ambiguity_selection_reason": None,
        "source_trace": [],
        "source_states": {},
        "last_error": None,
        "started_at": None,
        "completed_at": None,
        "updated_at": None,
    }
    ds.clear(); ds.update(deepcopy(defaults))
    data["manufacturer"] = None
    data["country"] = None
    data["package"] = {
        "value": None, "source": None, "attribute_name": None,
        "status": "unresolved", "resolved_by": None,
        "exact_part_number_match": False, "sources_tried": [], "updated_at": None,
    }
    data["phase2_history"] = []


def _invalidate_image(root: Path, data: dict, archive: Path) -> None:
    final = _find_final(root, data)
    if final:
        _move_if_exists(final, archive, "old_final")
    ref = str(data.get("source_reference") or "")
    pn = str(data.get("part_number") or "")
    for stem in {ref, pn}:
        if not stem:
            continue
        for p in (root / "output" / f"{stem}_regen.png", root / "output" / f"{stem}_canvas.png", root / "output" / f"{stem}.png"):
            _move_if_exists(p, archive, "old_image_work")
    regen = data.setdefault("regeneration", {})
    regen.update({"status": "pending", "attempts": 0, "attempt_history": [], "last_error": None, "completed_at": None, "prompt_level": 0})
    identity = data.setdefault("identity_validation", {})
    identity.update({"status": "pending", "pass": None, "issues": [], "rejection_reasons": [], "last_error": None, "completed_at": None})
    data.setdefault("logo", {}).update({"status": "pending", "last_error": None, "completed_at": None})
    data.setdefault("image_optimization", {}).update({"status": "pending", "file": None, "last_error": None, "completed_at": None})


def _reconcile_prepared_image_checkpoint(root: Path, data: dict) -> None:
    """Recover a V1.0/V1.1 OCR-failed item whose regenerated candidate is already good.

    If identity validation already passed and an output candidate exists, the admin's
    manually supplied PN should resume at logo/finalization rather than spend another
    image generation/identity call.
    """
    candidate = _find_candidate(root, data)
    identity = data.get("identity_validation") or {}
    if candidate and (identity.get("pass") is True or str(identity.get("status") or "").lower() in {"completed", "manual_override"}):
        data.setdefault("regeneration", {})["status"] = "completed"
        data["identity_validation"]["status"] = "completed" if identity.get("status") != "manual_override" else "manual_override"


def _invalidate_phase3(root: Path, pn: str, archive: Path, *, keep_cache: bool = False) -> dict:
    cache = _cache_prior_phase3(root, pn, archive) if keep_cache else {"json": None, "html": None}
    for ext in ("json", "html"):
        _move_if_exists(root / "phase3_outputs" / f"{pn}.{ext}", archive, "old_phase3_outputs")
    _move_if_exists(root / "products" / f"{pn}.json", archive, "old_products")
    _move_if_exists(root / "work" / "content" / pn, archive, "old_work")
    return cache


def _invalidate_fact_extraction(root: Path, pn: str, archive: Path) -> None:
    _move_if_exists(root / "work" / "fact_extraction" / pn, archive, "old_work")


def _rename_final_if_present(root: Path, data: dict, old_pn: str, new_pn: str) -> None:
    final = _find_final(root, data)
    if not final:
        return
    target = root / "Final" / f"{new_pn}.webp"
    if target.exists() and target.resolve() != final.resolve():
        raise FileExistsError(f"Final target already exists: {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if final.resolve() != target.resolve():
        final.rename(target)
    data.setdefault("image_optimization", {})["file"] = portable_path(root, target)


def _replace_pn_in_active_small_artifacts(root: Path, old_pn: str, new_pn: str) -> None:
    """Rename/replace only active lightweight artifacts; invalid technical caches are archived."""
    for folder, ext in ((root / "products", "json"),):
        old = folder / f"{old_pn}.{ext}"
        if not old.exists():
            continue
        try:
            data = _deep_replace(_read_json(old), old_pn, new_pn)
            new = folder / f"{new_pn}.{ext}"
            _write_json(new, data)
            old.unlink(missing_ok=True)
        except Exception:
            pass


def _admin_defaults() -> dict:
    return {
        "status": "PENDING_REVIEW",
        "classification": None,
        "selected_issues": [],
        "previous_part_number": None,
        "corrected_part_number": None,
        "previous_datasheet_status": None,
        "previous_no_datasheet": False,
        "force_phase1": False,
        "force_phase2": False,
        "force_seo": False,
        "force_fact_extraction": False,
        "prior_phase3_cache": {"json": None, "html": None},
        "last_decision_at": None,
        "ready_bundle": None,
        "history": [],
        "last_error": None,
    }


def ensure_admin_audit(data: dict) -> dict:
    audit = data.setdefault("admin_audit", {})
    defaults = _admin_defaults()
    for k, v in defaults.items():
        if k not in audit:
            audit[k] = deepcopy(v)
    return audit


def stage_ready_for_upload(root: Path, meta_path: Path, data: dict) -> Path:
    """Compatibility wrapper; V3 staging is the canonical bundle builder."""
    return build_canonical_bundle(root, meta_path, data)


def apply_batch_category(root: Path, metadata_path: Path, data: dict, category_key: str) -> dict:
    """Apply the explicit UI batch category and invalidate category-dependent outputs.

    A category change is a content change: it affects the title, SEO, internal links,
    technical-fact priorities and WooCommerce taxonomy. Existing WordPress products
    are never silently reclassified by this helper.
    """
    root = Path(root).resolve()
    metadata_path = Path(metadata_path).resolve()
    old_key = get_category_key(data)
    # Validate/normalize the requested key without mutating persisted metadata.
    new_key = str(category_context(category_key).get("key") or category_key).strip()
    category_mismatch = False
    pn_for_check = get_part_number(data)
    if old_key == new_key and pn_for_check:
        p3_path = root / "phase3_outputs" / f"{pn_for_check}.json"
        integrated_path = root / "products" / f"{pn_for_check}.json"
        if p3_path.is_file() or integrated_path.is_file():
            try:
                p3_doc = _read_json(p3_path) if p3_path.is_file() else None
                integrated_doc = _read_json(integrated_path) if integrated_path.is_file() else None
                assert_upstream_category_consistency(data, phase3=p3_doc, integrated=integrated_doc)
            except Exception:
                # Metadata can already carry the new category while stale P3 /
                # integrated artifacts still reflect a previous batch selection.
                category_mismatch = True
    if old_key == new_key and not category_mismatch:
        return {"changed": False, "blocked": False, "old_category": old_key, "new_category": new_key}

    publishing = data.get("publishing") or {}
    wordpress_product_id = str(publishing.get("wordpress_product_id") or "").strip()
    if wordpress_product_id:
        return {
            "changed": False,
            "blocked": True,
            "reason": "WORDPRESS_PRODUCT_ALREADY_EXISTS",
            "wordpress_product_id": wordpress_product_id,
            "old_category": old_key,
            "new_category": new_key,
        }

    pn = get_part_number(data)
    source_ref = get_source_reference(data) or metadata_path.stem
    phase3_state = data.get("phase3") or {}
    audit_state = data.get("admin_audit") or {}
    bundle_dir = root / "ready_for_upload" / pn if pn else None
    has_downstream = bool(
        (pn and (root / "phase3_outputs" / f"{pn}.json").exists())
        or (pn and (root / "phase3_outputs" / f"{pn}.html").exists())
        or (pn and (root / "products" / f"{pn}.json").exists())
        or (bundle_dir and bundle_dir.exists())
        or str(phase3_state.get("status") or "").lower() == "completed"
        or str(audit_state.get("status") or "").upper() == "APPROVED"
        or str(publishing.get("bundle_status") or "").upper() == "READY"
    )

    if has_downstream and pn:
        archive = _archive_dir(root, source_ref, f"category_change_{old_key}_to_{new_key}")
        _copy_if_exists(metadata_path, archive / "metadata_before")
        sync_category(data, new_key)

        # Preserve old outputs for audit/history; they must not be consumed under
        # the newly selected category.
        _invalidate_phase3(root, pn, archive, keep_cache=False)
        _invalidate_fact_extraction(root, pn, archive)
        invalidate_bundle(root, metadata_path, data, reason=f"category changed: {old_key} -> {new_key}")

        audit = ensure_admin_audit(data)
        audit["history"].append({
            "action": "BATCH_CATEGORY_CHANGED",
            "at": utc_now(),
            "part_number": pn,
            "previous_category": old_key,
            "selected_category": new_key,
            "archive": portable_path(root, archive),
        })
        audit.update({
            "status": "DISAPPROVED_PENDING_REPROCESS",
            "selected_issues": ["category_changed"],
            "previous_category_key": old_key,
            "selected_category_key": new_key,
            "force_phase1": False,
            "force_phase2": False,
            "force_seo": True,
            "force_fact_extraction": True,
            "ready_bundle": None,
            "last_decision_at": utc_now(),
            "last_error": None,
        })
        data.setdefault("phase3", {}).update({
            "status": "pending",
            "content_status": "pending",
            "json_file": None,
            "content_file": None,
            "last_error": None,
        })
        data.setdefault("publishing", {}).update({
            "release_allowed": False,
            "release_source": None,
            "bundle_status": "INVALIDATED",
            "bundle_path": None,
            "status": "NOT_STARTED",
            "successful": None,
            "wordpress_product_id": None,
            "wordpress_edit_url": None,
            "completed_with_warnings": False,
            "step_errors": {},
            "updated_at": utc_now(),
        })

    if not has_downstream:
        sync_category(data, new_key)
    if pn:
        data["product_title"] = deterministic_product_title(pn, new_key)
    save_admin_override(metadata_path, data)
    return {
        "changed": True,
        "blocked": False,
        "invalidated_downstream": has_downstream,
        "old_category": old_key,
        "new_category": new_key,
        "part_number": pn or None,
    }


def approve_item(root: Path, metadata_path: Path) -> dict:
    root = Path(root).resolve(); metadata_path = Path(metadata_path)
    data = _read_json(metadata_path)
    pn = str(data.get("part_number") or "").strip()
    p3_path, p3 = _phase3_state(root, pn)
    klass, _ = _classification(root, data, p3)
    if klass != "FINALIZED":
        raise RuntimeError("Audit Needed item cannot be approved until missing pipeline stages are completed")
    integrated_path = root / "products" / f"{pn}.json"
    integrated_doc = _read_json(integrated_path)
    assert_upstream_category_consistency(data, phase3=p3, integrated=integrated_doc)
    audit = ensure_admin_audit(data)
    audit["history"].append({"action": "APPROVE", "at": utc_now(), "part_number": pn})
    audit.update({"status": "APPROVED", "classification": "FINALIZED", "selected_issues": [], "last_decision_at": utc_now(), "last_error": None})
    save_admin_override(metadata_path, data)
    bundle = stage_ready_for_upload(root, metadata_path, data)
    # Persist the bundle path after staging so a failed copy never marks approval as upload-ready.
    data = _read_json(metadata_path)
    audit = ensure_admin_audit(data)
    audit["ready_bundle"] = portable_path(root, bundle)
    save_admin_override(metadata_path, data)
    return {"status": "APPROVED", "part_number": pn, "ready_bundle": str(bundle)}


def disapprove_item(root: Path, metadata_path: Path, issues: list[str], corrected_pn: str | None = None) -> dict:
    root = Path(root).resolve(); metadata_path = Path(metadata_path)
    issues = list(dict.fromkeys(str(x) for x in issues))
    unknown = set(issues) - ISSUES
    if unknown:
        raise ValueError(f"Unknown audit issue(s): {sorted(unknown)}")
    if not issues:
        raise ValueError("Select at least one disapproval reason")
    wrong_pn = "wrong_part_number" in issues
    if wrong_pn:
        # UI disables these; enforce the same contract in the service.
        issues = [x for x in issues if x not in {"wrong_data_sheet", "seo_content_regeneration_needed"}]
        corrected_pn = _safe_pn(corrected_pn or "")

    data = _read_json(metadata_path)
    old_pn = str(data.get("part_number") or "").strip()
    source_ref = str(data.get("source_reference") or metadata_path.stem)
    old_ds_status = str((data.get("datasheet") or {}).get("status") or "pending")
    old_no_ds = old_ds_status == "not_found_confirmed"
    archive = _archive_dir(root, source_ref, "+".join(issues))
    _copy_if_exists(metadata_path, archive / "metadata_before")

    audit = ensure_admin_audit(data)
    audit["history"].append({
        "action": "DISAPPROVE", "at": utc_now(), "part_number": old_pn or None,
        "issues": issues, "corrected_part_number": corrected_pn,
    })
    audit.update({
        "status": "DISAPPROVED_PENDING_REPROCESS",
        "selected_issues": issues,
        "previous_part_number": old_pn or None,
        "corrected_part_number": corrected_pn if wrong_pn else None,
        "previous_datasheet_status": old_ds_status,
        "previous_no_datasheet": old_no_ds,
        "force_phase1": "image_regeneration_needed" in issues,
        "force_phase2": wrong_pn or "wrong_data_sheet" in issues,
        "force_seo": wrong_pn or "wrong_data_sheet" in issues or "seo_content_regeneration_needed" in issues,
        "force_fact_extraction": "wrong_data_sheet" in issues,
        "ready_bundle": None,
        "last_decision_at": utc_now(),
        "last_error": None,
    })
    data.setdefault("publishing", {}).update({
        "release_allowed": False, "release_source": None,
        "bundle_status": "INVALIDATED", "bundle_path": None,
        "status": "NOT_STARTED", "successful": None,
        "wordpress_product_id": None, "wordpress_edit_url": None,
        "completed_with_warnings": False, "step_errors": {}, "updated_at": utc_now(),
    })

    # Any previous upload bundle is no longer authoritative.
    if old_pn:
        existing_bundle = root / "ready_for_upload" / old_pn
        if existing_bundle.exists():
            _move_if_exists(existing_bundle, archive, "old_ready_bundle")

    if wrong_pn:
        new_pn = corrected_pn
        if old_pn and old_pn.casefold() != new_pn.casefold():
            # Cache the previous SEO before invalidation. It is used only for the
            # explicit no-datasheet -> no-datasheet exception requested by admin.
            cache = _cache_prior_phase3(root, old_pn, archive)
            audit["prior_phase3_cache"] = cache
            if "image_regeneration_needed" not in issues:
                _rename_final_if_present(root, data, old_pn, new_pn)
            # Wrong-PN datasheet/facts/content are invalid; archive active artifacts.
            ds_file = _datasheet_summary(root, data).get("pdf_path")
            if ds_file:
                _move_if_exists(Path(ds_file), archive, "old_datasheet")
            _invalidate_fact_extraction(root, old_pn, archive)
            _invalidate_phase3(root, old_pn, archive, keep_cache=False)
            _move_if_exists(root / "products" / f"{old_pn}.json", archive, "old_products")
            _replace_pn_in_active_small_artifacts(root, old_pn, new_pn)
        elif not old_pn:
            audit["prior_phase3_cache"] = {"json": None, "html": None}

        data["part_number"] = new_pn
        data["product_title"] = deterministic_product_title(new_pn)
        data["ocr"].update({
            "status": "manual_override",
            "model": "ADMIN_AUDIT",
            "primary_code": new_pn,
            "part_number_segments": [new_pn],
            "part_number_confidence": "high",
            "image_source_decision": "original_dominant",
            "manual_override": True,
            "manual_authority": "ADMIN_AUDIT_ENTERED_PART_NUMBER",
            "notes": "PartNumber corrected manually in Admin Audit; OCR extraction is not rerun for this correction.",
            "last_error": None,
            "completed_at": utc_now(),
        })
        _reset_datasheet(data)
        if "image_regeneration_needed" in issues:
            _invalidate_image(root, data, archive)
        else:
            _reconcile_prepared_image_checkpoint(root, data)
        save_admin_override(metadata_path, data)
        metadata_path = rename_metadata_to_partnumber(root, metadata_path, data)
        state_path = root / "runtime_state" / f"{source_ref}.json"
        if state_path.exists():
            try:
                runtime = _read_json(state_path)
                runtime["part_number"] = new_pn
                runtime["metadata_path"] = str(metadata_path)
                _write_json(state_path, runtime)
            except Exception:
                pass
    else:
        pn = _safe_pn(old_pn) if old_pn else ""
        if "image_regeneration_needed" in issues:
            _invalidate_image(root, data, archive)
        if "wrong_data_sheet" in issues:
            ds_file = _datasheet_summary(root, data).get("pdf_path")
            if ds_file:
                _move_if_exists(Path(ds_file), archive, "old_datasheet")
            _invalidate_fact_extraction(root, pn, archive)
            _invalidate_phase3(root, pn, archive, keep_cache=False)
            _reset_datasheet(data)
        elif "seo_content_regeneration_needed" in issues:
            _invalidate_phase3(root, pn, archive, keep_cache=False)
        if "wrong_data_sheet" in issues:
            save_admin_override(metadata_path, data)
        else:
            save_admin_override(metadata_path, data)

    return {
        "status": "DISAPPROVED_PENDING_REPROCESS",
        "metadata_path": str(metadata_path),
        "part_number": get_part_number(data) or None,
        "issues": issues,
        "archive": str(archive),
    }


def _programmatic_replace_prior_seo(root: Path, meta_path: Path, data: dict) -> bool:
    audit = ensure_admin_audit(data)
    old_pn = str(audit.get("previous_part_number") or "").strip()
    new_pn = get_part_number(data)
    cache = audit.get("prior_phase3_cache") or {}
    cached_json = Path(cache["json"]) if cache.get("json") else None
    cached_html = Path(cache["html"]) if cache.get("html") else None
    if not old_pn or not new_pn or not cached_json or not cached_json.exists():
        return False
    state = _deep_replace(_read_json(cached_json), old_pn, new_pn)
    # Preserve the no-datasheet source contract for the newly corrected PN.
    source = state.setdefault("source", {})
    source.update({
        "datasheet_status": "NO_FULL_DATASHEET",
        "datasheet_path": None,
        "model_pdf_path": None,
        "pdf_window": None,
        "source_validation": "NO_FILE",
        "fact_status": "NOT_RUN",
        "useful_fact_count": 0,
        "facts_path": None,
        "primary_extraction_path": None,
        "fallback_extraction_path": None,
        "coverage_path": None,
        "pdf_calls": 0,
        "pdf_fallback_used": False,
        "priority_fact_coverage": None,
        "content_mode": "SALES_ONLY_NO_DATASHEET",
    })
    state.setdefault("identity", {})["part_number"] = new_pn
    state.setdefault("page", {})["product_title"] = deterministic_product_title(new_pn)
    out_dir = root / "phase3_outputs"; out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"{new_pn}.json"
    out_html = out_dir / f"{new_pn}.html"
    if cached_html and cached_html.exists():
        out_html.write_text(cached_html.read_text(encoding="utf-8").replace(old_pn, new_pn), encoding="utf-8")
    else:
        html_name = str((state.get("content") or {}).get("html_path") or "")
        if html_name:
            # A cached HTML is expected, but fail safe rather than invent content.
            return False
    state.setdefault("content", {})["html_path"] = out_html.name
    if isinstance(state.get("publishing"), dict):
        state["publishing"]["description_path"] = out_html.name
    _write_json(out_json, state)
    audit.update({
        "status": "READY_FOR_REAUDIT",
        "force_phase2": False,
        "force_seo": False,
        "force_fact_extraction": False,
        "last_error": None,
    })
    audit["history"].append({
        "action": "PROGRAMMATIC_PN_REPLACE_NO_DATASHEET_EXCEPTION",
        "at": utc_now(), "old_part_number": old_pn, "new_part_number": new_pn,
    })
    save_audit_phase_state(meta_path, data)
    return True


def accept_rejected_image(root: Path, metadata_path: Path, *, candidate: Path | None = None) -> dict:
    """Admin-authorized completion of an existing rejected candidate, without new AI calls.

    Preserves rejection history and writes a verifiable, branded, optimized final.
    Intended only while pipeline is idle (UI enforces that).
    """
    from image_optimizer import fit_to_canvas, optimize_final
    from logo_overlay import overlay_logo
    import os
    root = Path(root).resolve(); metadata_path = Path(metadata_path).resolve()
    data = _read_json(metadata_path)
    pn = _safe_pn(data.get('part_number') or '')
    if str((data.get('admin_audit') or {}).get('status') or '') == 'APPROVED':
        raise ValueError('Already approved: do not overwrite an approved product image')
    if _find_final(root, data):
        raise ValueError('Final image exists already. Do not overwrite an existing finalized image')
    status = str((data.get('identity_validation') or {}).get('status') or '').lower()
    if status not in ('rejected', 'failed', 'retry_required'):
        raise ValueError(f'Only rejected identity candidates can be manually accepted (status={status})')
    candidate = Path(candidate).resolve() if candidate else _find_candidate(root, data)
    if candidate is None or not candidate.is_file():
        raise FileNotFoundError('Regenerated canvas/candidate missing in output/. Restore the *_canvas.png or *_regen.png file')
    # File identity is tied to exactly this PN/reference to prevent arbitrary image injection.
    if candidate.stem not in {pn+'_canvas', pn+'_regen', str(data.get('source_reference') or '')+'_canvas', str(data.get('source_reference') or '')+'_regen'}:
        raise ValueError('Candidate filename does not match this product')
    from PIL import Image
    with Image.open(candidate) as img:
        img.verify()
    logo = root / 'assets' / 'store_logo.png'
    if not logo.is_file(): raise FileNotFoundError('Store logo missing')
    archive = _archive_dir(root, str(data.get('source_reference') or pn), 'admin_image_accept')
    _copy_if_exists(metadata_path, archive / 'metadata_before')
    prepared = root / 'output' / f'{pn}_admin_accepted_canvas.png'
    branded = root / 'output' / f'{pn}_admin_accepted_logo.png'
    prepared.parent.mkdir(parents=True,exist_ok=True)
    fit_to_canvas(candidate, prepared)
    overlay_logo(prepared, logo, branded, max_width=int(os.getenv('LOGO_MAX_WIDTH','260')), max_height=int(os.getenv('LOGO_MAX_HEIGHT','260')), margin=int(os.getenv('LOGO_MARGIN','40')))
    final = root / 'Final' / f'{pn}.webp'
    quality, size_kb = optimize_final(branded, final, int(os.getenv('FINAL_MIN_KB','50')), int(os.getenv('FINAL_MAX_KB','100')))
    import hashlib
    sha = hashlib.sha256(final.read_bytes()).hexdigest()
    now = utc_now()
    iv = data.setdefault('identity_validation', {})
    # Keep original status/reasons in provenance; do not pretend AI validated the image.
    original_rejection = {'status': iv.get('status'), 'issues': deepcopy(iv.get('issues') or []), 'rejection_reasons': deepcopy(iv.get('rejection_reasons') or []), 'last_error': iv.get('last_error')}
    iv['history'] = list(iv.get('history') or []) + [{'at': now, 'action': 'ADMIN_ACCEPTED_AFTER_REJECTION', 'previous': original_rejection, 'candidate': portable_path(root,candidate)}]
    iv.update({'status':'completed', 'pass': True, 'last_error':None, 'completed_at':now})
    data.setdefault('regeneration', {}).update({'status':'completed', 'last_error':None, 'completed_at':now})
    data.setdefault('logo', {}).update({'status':'completed', 'file': portable_path(root,logo), 'last_error':None, 'completed_at':now})
    data.setdefault('image_optimization', {}).update({'status':'completed', 'file':portable_path(root,final), 'format':'WEBP', 'width':1254,'height':1254,'quality':quality,'size_kb':round(size_kb,2), 'last_error':None,'completed_at':now})
    audit = ensure_admin_audit(data)
    audit.setdefault('history',[]).append({'at':now,'action':'ADMIN_ACCEPTED_REJECTED_IMAGE','part_number':pn,'candidate':portable_path(root,candidate),'final_sha256':sha,'previous_identity':original_rejection})
    if audit.get('status') == 'DISAPPROVED_PENDING_REPROCESS':
        remaining = [x for x in audit.get('selected_issues',[]) if x != 'image_regeneration_needed']
        audit['selected_issues'] = remaining
        audit['force_phase1'] = False
        if not remaining: audit['status'] = 'PENDING_REVIEW'
    save_admin_override(metadata_path,data)
    return {'part_number':pn, 'final_path':str(final), 'sha256':sha, 'candidate':str(candidate)}


def choose_no_datasheet_after_web_error(root: Path, metadata_path: Path) -> dict:
    """Explicit admin choice after source WEB_ERROR; never claim proven absence.

    Does not fabricate a PDF, content or approval; Phase 3 generates content on
    next Start. Keeping historical source states provides a complete audit trail.
    """
    root = Path(root).resolve()
    metadata_path = Path(metadata_path).resolve()
    data = _read_json(metadata_path)
    pn = _safe_pn(data.get("part_number") or "")
    ds = data.get("datasheet") or {}
    if ds.get("status") != "web_error":
        raise ValueError("Datasheet Doesn't Exist is available only for web_error items")
    if (data.get("admin_audit") or {}).get("status") == "APPROVED":
        raise ValueError("Cannot change an already approved product via this action")
    pdf = _datasheet_summary(root, data).get("pdf_path")
    local_pdf = root / "datasheets" / f"{pn}.pdf"
    if pdf or local_pdf.is_file():
        raise ValueError("An exact datasheet PDF is present; use the ordinary PDF route")
    if (root / "phase3_outputs" / f"{pn}.json").exists():
        raise ValueError("Existing Phase 3 output must be reviewed; sales-only action is not an overwrite")
    # A stale publishing bundle indicates contradictory state; do not touch it.
    if (root / "ready_for_upload" / pn).exists():
        raise ValueError("Existing publication bundle detected; review before changing datasheet state")
    at = utc_now()
    original_status = str(ds.get("status"))
    ds.update({
        "status": "sales_only_no_datasheet", "file": None,
        "sales_only_authorized": True, "sales_only_authorized_at": at,
        "sales_only_reason": "ADMIN_CHOICE_AFTER_WEB_ERROR; no PDF verified; does not prove datasheet absence",
        "document_source": None, "updated_at": at,
    })
    ds.setdefault("source_trace", []).append("ADMIN_SALES_ONLY_AFTER_WEB_ERROR")
    data["datasheet"] = ds
    audit = ensure_admin_audit(data)
    audit.update({"status": "DISAPPROVED_PENDING_REPROCESS", "classification": "AUDIT_NEEDED",
                  "force_phase1": False, "force_phase2": False,
                  "force_seo": True, "force_fact_extraction": False,
                  "ready_bundle": None, "last_decision_at": at, "last_error": None})
    audit["selected_issues"] = ["admin_sales_only_after_web_error"]
    audit["history"].append({"action": "ADMIN_SALES_ONLY_AFTER_WEB_ERROR", "at": at,
                             "part_number": pn, "previous_status": original_status,
                             "source_states": dict(ds.get("source_states") or {})})
    save_admin_override(metadata_path, data)
    return {"status": "SALES_ONLY_AUTHORIZED", "part_number": pn, "metadata_path": str(metadata_path)}


def attach_manual_datasheet(root: Path, metadata_path: Path, source_pdf: Path) -> dict:
    """Attach an admin-supplied exact datasheet and queue a fresh technical Phase 3 run.

    The admin is the identity authority for this action. The PDF is validated as a
    readable PDF, copied to datasheets/<PN>.pdf, metadata is updated atomically,
    and stale Phase-3/fact artifacts are archived so the next Start rebuilds them.
    """
    root = Path(root).resolve()
    metadata_path = Path(metadata_path).resolve()
    source_pdf = Path(source_pdf).resolve()
    if source_pdf.suffix.lower() != ".pdf" or not source_pdf.exists() or not source_pdf.is_file():
        raise ValueError("Drop/select a valid PDF file")
    try:
        reader = PdfReader(str(source_pdf))
        page_count = len(reader.pages)
    except Exception as exc:
        raise ValueError(f"PDF cannot be read: {exc}") from exc
    if page_count < 1:
        raise ValueError("PDF has no readable pages")

    data = _read_json(metadata_path)
    pn = _safe_pn(data.get("part_number") or "")
    source_ref = str(data.get("source_reference") or pn)
    archive = _archive_dir(root, source_ref, "manual_datasheet_attach")
    _copy_if_exists(metadata_path, archive / "metadata_before")

    # Any previous PDF/content is no longer authoritative.
    current_pdf = _datasheet_summary(root, data).get("pdf_path")
    target = root / "datasheets" / f"{pn}.pdf"
    if current_pdf:
        current = Path(current_pdf)
        if current.exists() and current.resolve() != source_pdf and current.resolve() != target.resolve():
            _move_if_exists(current, archive, "old_datasheet")
    if target.exists() and target.resolve() != source_pdf:
        _move_if_exists(target, archive, "old_datasheet")
    _invalidate_fact_extraction(root, pn, archive)
    _invalidate_phase3(root, pn, archive, keep_cache=False)

    target.parent.mkdir(parents=True, exist_ok=True)
    if source_pdf.resolve() != target.resolve():
        shutil.copy2(source_pdf, target)

    ds = data.setdefault("datasheet", {})
    ds.update({
        "status": "completed",
        "searched_part_number": pn,
        "matched_part_number": pn,
        "verified_exact_match": True,
        "identity_status": "EXACT_PART_NUMBER_FOUND",
        "identity_source": "ADMIN_AUDIT_MANUAL",
        "document_source": "ADMIN_AUDIT_MANUAL",
        "source_url": None,
        "file": portable_path(root, target),
        "last_error": None,
        "completed_at": utc_now(),
        "updated_at": utc_now(),
    })
    data.setdefault("phase2_history", []).append({
        "at": utc_now(),
        "status": "completed",
        "source": "ADMIN_AUDIT_MANUAL",
        "part_number": pn,
        "file": portable_path(root, target),
        "pages": page_count,
    })

    audit = ensure_admin_audit(data)
    selected = [x for x in (audit.get("selected_issues") or []) if x != "manual_datasheet_added"]
    selected.append("manual_datasheet_added")
    audit.update({
        "status": "DISAPPROVED_PENDING_REPROCESS",
        "classification": "AUDIT_NEEDED",
        "selected_issues": selected,
        "force_phase1": False,
        "force_phase2": False,
        "force_seo": True,
        "force_fact_extraction": True,
        "ready_bundle": None,
        "last_decision_at": utc_now(),
        "last_error": None,
    })
    audit["history"].append({
        "action": "MANUAL_DATASHEET_ATTACHED",
        "at": utc_now(),
        "part_number": pn,
        "file": portable_path(root, target),
        "pages": page_count,
    })
    save_admin_override(metadata_path, data)
    return {
        "status": "MANUAL_DATASHEET_ATTACHED",
        "part_number": pn,
        "datasheet_path": str(target),
        "pages": page_count,
        "metadata_path": str(metadata_path),
    }


def post_phase2_admin_hook(root: Path, meta_path: Path) -> dict:
    """Called after Phase 2 reaches a terminal state.

    Returns a routing decision for the orchestrator:
      * handled_locally=True => do not call Phase 3 (special no-datasheet exception)
      * otherwise force flags tell Phase 3 whether to regenerate.
    """
    root = Path(root).resolve(); meta_path = Path(meta_path)
    data = _read_json(meta_path)
    audit = ensure_admin_audit(data)
    ds_status = str((data.get("datasheet") or {}).get("status") or "")
    wrong_pn_pending = (
        audit.get("status") == "DISAPPROVED_PENDING_REPROCESS"
        and "wrong_part_number" in (audit.get("selected_issues") or [])
    )
    if wrong_pn_pending and bool(audit.get("previous_no_datasheet")) and ds_status == "not_found_confirmed":
        if _programmatic_replace_prior_seo(root, meta_path, data):
            return {"handled_locally": True, "reason": "NO_DATASHEET_TO_NO_DATASHEET_PN_REPLACE"}
    return {
        "handled_locally": False,
        "force_seo": bool(audit.get("force_seo")),
        "force_fact_extraction": bool(audit.get("force_fact_extraction")),
    }


def mark_phase3_reprocessed(root: Path, meta_path: Path) -> None:
    data = _read_json(meta_path)
    audit = ensure_admin_audit(data)
    if audit.get("status") == "DISAPPROVED_PENDING_REPROCESS":
        audit.update({
            "status": "READY_FOR_REAUDIT",
            "force_phase2": False,
            "force_seo": False,
            "force_fact_extraction": False,
            "last_error": None,
        })
        audit["history"].append({"action": "REPROCESS_COMPLETED", "at": utc_now()})
    save_audit_phase_state(meta_path, data)


def mark_phase1_reprocessed_if_image_only(meta_path: Path) -> None:
    data = _read_json(meta_path)
    audit = ensure_admin_audit(data)
    issues = set(audit.get("selected_issues") or [])
    if audit.get("status") == "DISAPPROVED_PENDING_REPROCESS" and bool(audit.get("force_phase1")):
        audit["force_phase1"] = False
        audit["last_error"] = None
        audit["history"].append({"action": "IMAGE_REPROCESS_COMPLETED", "at": utc_now()})
        if issues == {"image_regeneration_needed"}:
            audit["status"] = "READY_FOR_REAUDIT"
        save_audit_phase_state(meta_path, data)


def prepare_pn_input_metadata(root: Path, image: Path) -> tuple[Path, dict]:
    root = Path(root).resolve(); image = Path(image).resolve()
    pn = _safe_pn(image.stem)
    meta_path, data = load_or_create(root, pn)
    existing_pn = str(data.get("part_number") or "").strip()
    if existing_pn and existing_pn.casefold() != pn.casefold():
        raise RuntimeError(f"PN_input filename {pn} conflicts with existing metadata PartNumber {existing_pn}")
    data["part_number"] = pn
    data["product_title"] = deterministic_product_title(pn)
    data["source_reference"] = pn
    source_folder = image.parent.name if image.parent.name in {"input_PN", "PN_input"} else "input_PN"
    data["original_image"] = {
        "file": portable_path(root, image),
        "source": source_folder,
        "part_number_authority": "USER_FILENAME",
        "note": f"Original image with the confirmed PartNumber filename '{image.name}' is stored in {source_folder}; OCR PartNumber extraction was skipped.",
    }
    data.setdefault("ocr", {}).update({
        "status": "manual_override",
        "model": "PN_INPUT_FILENAME",
        "primary_code": pn,
        "part_number_segments": [pn],
        "part_number_layout": "single_line",
        "part_number_confidence": "high",
        "image_source_decision": "original_dominant",
        "manual_override": True,
        "manual_authority": "PN_INPUT_FILENAME",
        "notes": f"PartNumber supplied by filename in {source_folder}; OCR API call intentionally skipped.",
        "last_error": None,
        "completed_at": utc_now(),
    })
    save(meta_path, data)
    meta_path = rename_metadata_to_partnumber(root, meta_path, data)
    return meta_path, data


def find_pn_input_images(root: Path) -> list[Path]:
    """Discover trusted-PN images from both supported folder spellings.

    Some deployed worktrees use PN_input/ while newer V4 worktrees use input_PN/.
    Both are valid inputs; an existing but empty canonical folder must not hide
    files placed in the compatibility folder.
    """
    root = Path(root)
    found = []
    seen = set()
    for folder in (root / "input_PN", root / "PN_input"):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGES:
                continue
            key = str(path.resolve()).casefold()
            if key not in seen:
                seen.add(key)
                found.append(path)
    return sorted(found, key=lambda p: (p.stem.casefold(), p.parent.name.casefold(), p.name.casefold()))
