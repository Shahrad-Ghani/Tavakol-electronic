from pathlib import Path, PurePosixPath
import json
import os
import re
from datetime import datetime, timezone
from functools import lru_cache
from copy import deepcopy
import threading

from jsonschema import Draft202012Validator

from api_accounting import new_accounting_record
from core.metadata_v3 import SCHEMA_VERSION, deterministic_product_title, sync_identity, sync_release_gate, sync_category, get_category_key, utcnow

CURRENT_PROMPT_VERSION = "v5.0-economy-first-reference-lock"
CURRENT_PRECHECK_PROMPT_VERSION = "v1.2-visual-geometry-profile-selector"
CURRENT_IDENTITY_VALIDATOR_PROMPT_VERSION = "v2-structural-fallback-gate"
CURRENT_OCR_PROMPT_VERSION = "v4.0-dual-image-cropped-fallback-ocr"
_METADATA_WRITE_LOCK = threading.RLock()
WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def utc_now():
    return utcnow()


def metadata_path(root: Path, filename_stem: str):
    return root / "metadata" / f"{filename_stem}.json"


def portable_path(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def resolve_recorded_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return root.joinpath(*PurePosixPath(value.replace("\\", "/")).parts)


def _find_by_reference(root: Path, ref_stem: str):
    direct = metadata_path(root, ref_stem)
    if direct.exists():
        return direct
    meta_dir = root / "metadata"
    if not meta_dir.exists():
        return None
    for path in meta_dir.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("source_reference") or data.get("img_refrence_name") or "") == ref_stem:
            return path
    return None


def _new_record(ref_stem: str, category: str = "IC"):
    regen_model = os.getenv("REGENERATION_MODEL", "gpt-image-2-2026-04-21")
    precheck_model = os.getenv("PRECHECK_MODEL", "gpt-5.4-nano-2026-03-17")
    validator_model = os.getenv("IDENTITY_VALIDATOR_MODEL", "gpt-5.4-nano-2026-03-17")
    ocr_model = os.getenv("OCR_MODEL_PRIMARY", "gpt-5.6-luna")
    now = utc_now()
    rec = {
        "schema_version": SCHEMA_VERSION,
        "product_id": ref_stem,
        "product_type": category or "ic",
        "category": {},
        "source_reference": ref_stem,
        "part_number": None,
        "product_title": None,
        "manufacturer": None,
        "country": None,
        "original_image": {"file": None, "source": "input", "part_number_authority": "OCR", "note": None},
        "precheck": {
            "status": "pending", "model": precheck_model, "prompt_version": CURRENT_PRECHECK_PROMPT_VERSION,
            "visible_leads_state": None, "visible_lead_count": None, "lead_state_confidence": None,
            "irregular_geometry": None, "irregular_features": [], "irregular_confidence": None,
            "selected_addendums": [], "prompt_profile": None, "high_risk": False, "risk_tier": "economy_first",
            "risk_reasons": [], "regeneration_route": "economy-first-primary",
            "recommended_regeneration_model": os.getenv("REGENERATION_PRIMARY_MODEL", regen_model),
            "recommended_regeneration_quality": os.getenv("REGENERATION_PRIMARY_QUALITY", "low"),
            "notes": None, "last_error": None, "completed_at": None,
        },
        "regeneration": {
            "status": "pending", "model": regen_model, "quality": None, "route": None,
            "routing_mode": "economy-first-cheap-then-structural-fallback-v1", "prompt_version": CURRENT_PROMPT_VERSION,
            "prompt_level": 0, "prompt_profile": None, "prompt_addendums": [], "attempts": 0,
            "attempt_history": [], "last_error": None, "completed_at": None,
        },
        "identity_validation": {
            "status": "pending", "model": validator_model, "prompt_version": CURRENT_IDENTITY_VALIDATOR_PROMPT_VERSION,
            "pass": None, "package_geometry": None, "lead_structure": None, "body_color_consistency": None,
            "holes_tabs_features": None, "markings_consistency": None, "invented_or_removed_features": None,
            "commercial_quality_ok": None, "identity_confidence": None, "issues": [], "rejection_reasons": [],
            "history": [], "last_error": None, "completed_at": None,
        },
        "ocr": {
            "status": "pending", "model": ocr_model, "prompt_version": CURRENT_OCR_PROMPT_VERSION,
            "visible_lines_original": [], "visible_lines_regenerated": [], "visible_lines": [], "primary_code": None,
            "part_number_segments": [], "part_number_layout": None, "part_number_confidence": "unreadable",
            "image_source_decision": "uncertain", "secondary_codes": [], "comparison_conflicts": [],
            "manufacturer_marking": None, "country_marking": None, "notes": None, "last_error": None,
            "completed_at": None,
        },
        "logo": {"status": "pending", "file": None, "last_error": None, "completed_at": None},
        "image_optimization": {
            "status": "pending", "format": None, "width": None, "height": None, "size_kb": None, "quality": None,
            "file": None, "last_error": None, "completed_at": None,
        },
        "datasheet": {
            "status": "pending", "searched_part_number": None, "matched_part_number": None,
            "verified_exact_match": False, "identity_status": "NOT_SEARCHED", "manufacturer": None,
            "manufacturer_country": None, "manufacturer_country_status": "NOT_SEARCHED", "identity_source": None,
            "document_source": None, "source_url": None, "file": None, "mouser_part_number": None,
            "ambiguity_flag": None, "ambiguity_source": None, "alternative_manufacturers": [],
            "ambiguity_selection_reason": None, "source_trace": [], "source_states": {}, "last_error": None,
            "started_at": None, "completed_at": None, "updated_at": None,
        },
        "package": {
            "value": None, "source": None, "attribute_name": None, "status": "unresolved", "resolved_by": None,
            "exact_part_number_match": False, "sources_tried": [], "updated_at": None,
        },
        "phase2_history": [],
        "phase3": {
            "status": "not_started", "facts_status": "not_started", "content_status": "not_started",
            "json_file": None, "content_file": None, "seo_score": None, "validator_publishable": None,
            "tone_status": None, "seo_agent_status": None, "seo_title": None, "meta_description": None, "slug": None, "semantic_audit_status": None, "package_fallback_attempted": False, "updated_at": None,
        },
        "admin_audit": {
            "status": "PENDING_REVIEW", "classification": None, "selected_issues": [], "previous_part_number": None,
            "corrected_part_number": None, "previous_datasheet_status": None, "previous_no_datasheet": False,
            "force_phase1": False, "force_phase2": False, "force_seo": False, "force_fact_extraction": False,
            "prior_phase3_cache": {"json": None, "html": None}, "last_decision_at": None, "ready_bundle": None,
            "history": [], "last_error": None,
        },
        "publishing": {
            "release_allowed": False, "release_source": None, "bundle_status": "NOT_BUILT", "bundle_path": None,
            "status": "NOT_STARTED", "successful": None, "wordpress_product_id": None, "wordpress_edit_url": None,
            "completed_with_warnings": False, "step_errors": {}, "updated_at": None,
        },
        "diagnostics": {"api_accounting": new_accounting_record(), "legacy": {}},
        "created_at": now,
        "updated_at": now,
    }
    sync_category(rec, category)
    return rec


def _add_missing_nested(target: dict, defaults: dict):
    for key, value in defaults.items():
        if key not in target:
            target[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _add_missing_nested(target[key], value)


@lru_cache(maxsize=1)
def _schema_validator() -> Draft202012Validator:
    schema_path = Path(__file__).resolve().with_name("metadata_schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _validate_metadata(data: dict):
    if os.getenv("METADATA_SCHEMA_VALIDATE", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    errors = sorted(_schema_validator().iter_errors(data), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise ValueError(f"Metadata schema validation failed at {path}: {first.message}")


def _normalize_legacy_metadata(data: dict):
    """Normalize old prompt/routing values. Kept for V2 migration compatibility."""
    precheck = data.setdefault("precheck", {})
    regen = data.setdefault("regeneration", {})
    if precheck.get("risk_tier") in {"normal", "high", None}:
        precheck["risk_tier"] = "economy_first"
    if precheck.get("regeneration_route") in {"normal-economy", "high-risk-fidelity", "retry-fidelity", None}:
        precheck["regeneration_route"] = "economy-first-primary"
    if precheck.get("recommended_regeneration_quality") not in {"low", "medium", "high", "auto", None}:
        precheck["recommended_regeneration_quality"] = os.getenv("REGENERATION_PRIMARY_QUALITY", "low")
    route_map = {"normal-economy": "economy-first-primary", "high-risk-fidelity": "strict-fallback", "retry-fidelity": "strict-fallback"}
    if regen.get("route") in route_map:
        regen["route"] = route_map[regen["route"]]
    for item in regen.get("attempt_history") or []:
        if "safe_zone_pass" in item and "logo_zone_clear" not in item:
            item["logo_zone_clear"] = bool(item.pop("safe_zone_pass"))
        if "safe_zone_occupancy" in item and "logo_zone_occupancy" not in item:
            item["logo_zone_occupancy"] = item.pop("safe_zone_occupancy")


def _normalize_integrated_identity(data: dict):
    ocr = data.setdefault("ocr", {})
    ocr.setdefault("manufacturer_marking", None)
    ocr.setdefault("country_marking", None)
    ds = data.get("datasheet") if isinstance(data.get("datasheet"), dict) else {}
    if ds.get("verified_exact_match") is True:
        data["manufacturer"] = ds.get("manufacturer")
        data["country"] = ds.get("manufacturer_country")
        return
    if data.get("manufacturer") and not ocr.get("manufacturer_marking"):
        ocr["manufacturer_marking"] = data.get("manufacturer")
    if data.get("country") and not ocr.get("country_marking"):
        ocr["country_marking"] = data.get("country")
    data["manufacturer"] = None
    data["country"] = None


def _migrate_legacy_record(data: dict, ref_stem: str, category: str = "IC") -> dict:
    if data.get("schema_version") == SCHEMA_VERSION and "part_number" in data:
        return data
    old = deepcopy(data)
    out = _new_record(str(old.get("img_refrence_name") or old.get("source_reference") or ref_stem), old.get("category") or category)
    pn = str(old.get("part_number") or old.get("PartNumber") or "").strip() or None
    out["product_id"] = old.get("product_id") or ref_stem
    out["source_reference"] = old.get("source_reference") or old.get("img_refrence_name") or ref_stem
    out["part_number"] = pn
    sync_category(out, old.get("product_type") or old.get("category") or category)
    out["product_title"] = deterministic_product_title(pn, get_category_key(out)) if pn else None
    out["manufacturer"] = old.get("manufacturer")
    out["country"] = old.get("country")
    out["original_image"] = deepcopy(old.get("original_image") or old.get("original_imag") or out["original_image"])
    for key in ("precheck", "regeneration", "identity_validation", "ocr", "logo", "image_optimization", "datasheet", "admin_audit"):
        if isinstance(old.get(key), dict):
            _add_missing_nested(old[key], out[key])
            out[key] = deepcopy(old[key])
    # Old Phase-2 package lived inside datasheet.package. Promote it once.
    old_pkg = (old.get("datasheet") or {}).pop("package", None) if isinstance(old.get("datasheet"), dict) else None
    if isinstance(old_pkg, dict) and old_pkg.get("value"):
        out["package"].update({
            "value": old_pkg.get("value"), "source": old_pkg.get("source") or "mouser",
            "attribute_name": old_pkg.get("attribute_name"), "status": "resolved", "resolved_by": "phase2",
            "exact_part_number_match": bool(old_pkg.get("exact_part_number_match")), "updated_at": old.get("datasheet",{}).get("updated_at"),
        })
    out["phase2_history"] = deepcopy(old.get("phase2_history") or [])
    if isinstance(old.get("phase3"), dict):
        out["phase3"].update(deepcopy(old["phase3"]))
    if isinstance(old.get("publishing"), dict):
        out["publishing"].update(deepcopy(old["publishing"]))
    api = old.get("api_accounting") or ((old.get("diagnostics") or {}).get("api_accounting")) or new_accounting_record()
    out["diagnostics"]["api_accounting"] = deepcopy(api)
    out["diagnostics"]["legacy"] = {
        "status": deepcopy(old.get("status") or {}),
        "output": deepcopy(old.get("output") or {}),
        "legacy_name": old.get("name"),
        "legacy_part_number_key": old.get("PartNumber"),
    }
    out["created_at"] = old.get("created_at") or out["created_at"]
    _normalize_legacy_metadata(out)
    _normalize_integrated_identity(out)
    return out


def load_or_create(root: Path, ref_stem: str, category="IC"):
    path = _find_by_reference(root, ref_stem)
    if path is not None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        data = _migrate_legacy_record(raw, ref_stem, category)
    else:
        path = metadata_path(root, ref_stem)
        data = _new_record(ref_stem, category)
    defaults = _new_record(ref_stem, category)
    for key, value in defaults.items():
        if key not in data:
            data[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(data.get(key), dict):
            _add_missing_nested(data[key], value)
    _normalize_legacy_metadata(data)
    _normalize_integrated_identity(data)
    sync_identity(data)
    sync_release_gate(data)
    save(path, data)
    return path, data


def _canonicalize_before_write(data: dict) -> dict:
    payload = deepcopy(data)
    if payload.get("schema_version") != SCHEMA_VERSION or "part_number" not in payload:
        payload = _migrate_legacy_record(payload, str(payload.get("source_reference") or payload.get("img_refrence_name") or payload.get("product_id") or "UNKNOWN"))
    payload["schema_version"] = SCHEMA_VERSION
    sync_identity(payload)
    sync_release_gate(payload)
    payload["updated_at"] = utc_now()
    # Legacy aliases are never persisted in V3.
    for key in ("PartNumber", "name", "img_refrence_name", "original_imag", "status", "output", "api_accounting"):
        payload.pop(key, None)
    if isinstance(payload.get("datasheet"), dict):
        payload["datasheet"].pop("package", None)
    return payload


def _atomic_write_metadata(path: Path, data: dict):
    payload = _canonicalize_before_write(data)
    _validate_metadata(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f'.{threading.get_ident()}.tmp')
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return payload


def _same_metadata_identity(a: dict, b: dict) -> bool:
    aref = str(a.get("source_reference") or a.get("img_refrence_name") or "")
    bref = str(b.get("source_reference") or b.get("img_refrence_name") or "")
    if aref != bref:
        return False
    apn = str(a.get("part_number") or a.get("PartNumber") or "").strip().casefold()
    bpn = str(b.get("part_number") or b.get("PartNumber") or "").strip().casefold()
    return apn == bpn


def _phase2_has_started(data: dict) -> bool:
    ds = data.get("datasheet") if isinstance(data.get("datasheet"), dict) else {}
    return bool(ds.get("updated_at") or ds.get("started_at") or str(ds.get("status") or "pending") not in {"", "pending"})


def _is_explicit_admin_update(existing: dict, incoming: dict) -> bool:
    """Human Audit actions append provenance; concurrent worker snapshots do not.

    Audit is only used while the workers are idle. Protect new decisions from
    late Phase-1 snapshots, but allow explicit PN correction or invalidate flows.
    """
    old_history = (existing.get('admin_audit') or {}).get('history') or []
    new_history = (incoming.get('admin_audit') or {}).get('history') or []
    if len(new_history) <= len(old_history):
        return False
    recent = new_history[-1] if new_history else {}
    return str(recent.get('action') or '') in {
        'APPROVE', 'DISAPPROVE', 'ADMIN_ACCEPTED_REJECTED_IMAGE',
        'ADMIN_SALES_ONLY_AFTER_WEB_ERROR', 'MANUAL_DATASHEET_ATTACHED',
        'PROGRAMMATIC_PN_REPLACE_NO_DATASHEET_EXCEPTION',
    }


def _merge_phase2_owned_fields(existing: dict, incoming_phase1: dict) -> dict:
    existing = _migrate_legacy_record(existing, str(existing.get("source_reference") or existing.get("img_refrence_name") or "UNKNOWN"))
    incoming_phase1 = _migrate_legacy_record(incoming_phase1, str(incoming_phase1.get("source_reference") or incoming_phase1.get("img_refrence_name") or "UNKNOWN"))
    merged = deepcopy(incoming_phase1)
    if _is_explicit_admin_update(existing, incoming_phase1):
        return merged
    if not _same_metadata_identity(existing, incoming_phase1):
        old_pn = str(existing.get('part_number') or '').strip()
        new_pn = str(incoming_phase1.get('part_number') or '').strip()
        if old_pn and new_pn and old_pn.casefold() != new_pn.casefold():
            raise ValueError('PN_IDENTITY_CHANGED_DURING_CONCURRENT_SAVE: review identity before overwriting')
    # Later phases and human decisions must never be overwritten by a stale P1 snapshot.
    if _phase2_has_started(existing):
        for key in ("datasheet", "package", "manufacturer", "country", "phase2_history"):
            merged[key] = deepcopy(existing.get(key))
    for key in ("phase3", "admin_audit", "publishing", "diagnostics"):
        if key in existing:
            merged[key] = deepcopy(existing[key])
    # Product title is derived from canonical identity/category, not from a worker snapshot.
    merged['category'] = deepcopy(existing.get('category') or incoming_phase1.get('category'))
    merged['product_type'] = existing.get('product_type') or incoming_phase1.get('product_type')
    return merged


def _sync_mapping_in_place(target: dict, source: dict):
    for key in list(target.keys()):
        if key not in source:
            del target[key]
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _sync_mapping_in_place(target[key], value)
        else:
            target[key] = deepcopy(value)


def save(path: Path, data):
    """Canonical Phase-1 save, merge-safe with concurrent Phase 2 writes."""
    path = Path(path)
    with _METADATA_WRITE_LOCK:
        merged = deepcopy(data)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
                merged = _merge_phase2_owned_fields(existing, merged)
            except (ValueError, json.JSONDecodeError):
                raise
        persisted = _atomic_write_metadata(path, merged)
        if isinstance(data, dict):
            _sync_mapping_in_place(data, persisted)


def save_admin_override(path: Path, data: dict):
    path = Path(path)
    with _METADATA_WRITE_LOCK:
        persisted = _atomic_write_metadata(path, deepcopy(data))
        if isinstance(data, dict):
            _sync_mapping_in_place(data, persisted)


def save_audit_phase_state(path: Path, data: dict):
    """Persist just the audit decision from an asynchronously completing phase.

    Phase1 and Phase3 may finish simultaneously; copying an entire stale JSON
    at this point would erase updated image or content checkpoints.
    """
    path = Path(path)
    with _METADATA_WRITE_LOCK:
        latest = json.loads(path.read_text(encoding='utf-8')) if path.exists() else deepcopy(data)
        latest['admin_audit'] = deepcopy((data.get('admin_audit') or {}))
        persisted = _atomic_write_metadata(path, latest)
        if isinstance(data, dict):
            _sync_mapping_in_place(data, persisted)


def save_phase2(path: Path, phase2_data: dict):
    path = Path(path)
    with _METADATA_WRITE_LOCK:
        incoming = _migrate_legacy_record(phase2_data, str(phase2_data.get("source_reference") or phase2_data.get("img_refrence_name") or "UNKNOWN"))
        if path.exists():
            latest_raw = json.loads(path.read_text(encoding="utf-8"))
            latest = _migrate_legacy_record(latest_raw, str(latest_raw.get("source_reference") or latest_raw.get("img_refrence_name") or "UNKNOWN"))
            if _same_metadata_identity(latest, incoming):
                # An in-flight Phase2 request can finish AFTER a human attaches
                # a PDF or authorizes Sales-only. Never let that stale result
                # erase the human decision or an already verified PDF.
                from phase2.metadata_state import protected_datasheet_authority
                protected, protection_reason = protected_datasheet_authority(latest, path.parent.parent)
                audit = latest.get("admin_audit") or {}
                force_replacement = bool(audit.get("force_phase2")) and audit.get("status") == "DISAPPROVED_PENDING_REPROCESS"
                if protected and not force_replacement:
                    _sync_mapping_in_place(phase2_data, latest)
                    return
                merged = deepcopy(latest)
                for key in ("datasheet", "package", "manufacturer", "country", "phase2_history"):
                    merged[key] = deepcopy(incoming.get(key))
            else:
                # Phase2 cannot change canonical Part Number. This is a stale
                # response for a different identity, not an authorized correction.
                _sync_mapping_in_place(phase2_data, latest)
                return
        else:
            merged = deepcopy(incoming)
        persisted = _atomic_write_metadata(path, merged)
        if isinstance(phase2_data, dict):
            _sync_mapping_in_place(phase2_data, persisted)


def save_phase3(path: Path, phase3_data: dict):
    """Merge-safe Phase 3 write.

    Phase 3 owns its summary and may fill the canonical package only when Phase 2
    left it unresolved. Phase 2 identity/datasheet fields remain authoritative.
    """
    path = Path(path)
    with _METADATA_WRITE_LOCK:
        incoming = _migrate_legacy_record(
            phase3_data,
            str(phase3_data.get("source_reference") or phase3_data.get("product_id") or "UNKNOWN"),
        )
        if path.exists():
            latest_raw = json.loads(path.read_text(encoding="utf-8"))
            latest = _migrate_legacy_record(
                latest_raw,
                str(latest_raw.get("source_reference") or latest_raw.get("product_id") or "UNKNOWN"),
            )
            if _same_metadata_identity(latest, incoming):
                merged = deepcopy(latest)
                merged["phase3"] = deepcopy(incoming.get("phase3") or {})
                merged["product_title"] = incoming.get("product_title") or merged.get("product_title")
                incoming_pkg = incoming.get("package") or {}
                latest_pkg = latest.get("package") or {}
                if incoming_pkg.get("value") and not latest_pkg.get("value"):
                    merged["package"] = deepcopy(incoming_pkg)
            else:
                merged = deepcopy(incoming)
        else:
            merged = deepcopy(incoming)
        persisted = _atomic_write_metadata(path, merged)
        if isinstance(phase3_data, dict):
            _sync_mapping_in_place(phase3_data, persisted)


def _safe_part_number(value: str) -> str:
    value = re.sub(r"[\r\n\t]+", "", str(value or "")).strip().strip(" .")
    if not value:
        raise ValueError("PartNumber is empty")
    if any(ord(ch) < 32 for ch in value):
        raise ValueError("PartNumber contains control characters")
    if any(ch in value for ch in '<>:"/\\|?*'):
        raise ValueError(f"PartNumber contains characters invalid for a Windows filename: {value!r}")
    if value.upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"PartNumber is a reserved Windows filename: {value!r}")
    return value


def rename_metadata_to_partnumber(root: Path, current_path: Path, data):
    """Serialize PN promotion; refuse any cross-image PN collision before writing."""
    with _METADATA_WRITE_LOCK:
        part = _safe_part_number(data.get('part_number') or data.get('PartNumber') or '')
        target = metadata_path(root, part)
        data['part_number'] = part
        data['product_title'] = deterministic_product_title(part, get_category_key(data))
        if current_path.resolve() == target.resolve():
            save(current_path, data)
            return current_path
        if target.exists():
            existing = json.loads(target.read_text(encoding='utf-8'))
            existing_ref = existing.get('source_reference') or existing.get('img_refrence_name')
            data_ref = data.get('source_reference') or data.get('img_refrence_name')
            if existing_ref != data_ref:
                raise FileExistsError(f'Metadata target already exists for another reference: {target.name}')
        save(target, data)
        if current_path.exists() and current_path.resolve() != target.resolve():
            current_path.unlink()
        return target
