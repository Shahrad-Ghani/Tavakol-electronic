from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from jsonschema import Draft202012Validator

from . import core_runtime as core
from .country_registry import resolve_manufacturer_country
from .resolver_v43 import Result, exact
from core.package_resolution import apply_package_candidate
from core.metadata_v3 import get_part_number
from datasheet_authority_history import (
    MANUAL_PDF_ACTION, SALES_ONLY_ACTIONS, latest_admin_datasheet_decision,
)

TERMINAL_NO_RETRY = {"completed", "manual_required", "not_found_confirmed"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def product_part_number(data: Dict[str, Any]) -> str:
    return get_part_number(data)


def default_datasheet_state() -> Dict[str, Any]:
    return {
        "status": "pending", "searched_part_number": None, "matched_part_number": None,
        "verified_exact_match": False, "identity_status": "NOT_SEARCHED", "manufacturer": None,
        "manufacturer_country": None, "manufacturer_country_status": "NOT_SEARCHED", "identity_source": None,
        "document_source": None, "source_url": None, "file": None, "mouser_part_number": None,
        "ambiguity_flag": None, "ambiguity_source": None, "alternative_manufacturers": [],
        "ambiguity_selection_reason": None, "source_trace": [], "source_states": {}, "last_error": None,
        "started_at": None, "completed_at": None, "updated_at": None,
    }


def default_package_state() -> Dict[str, Any]:
    return {
        "value": None, "source": None, "attribute_name": None, "status": "unresolved", "resolved_by": None,
        "exact_part_number_match": False, "sources_tried": [], "updated_at": None,
    }


def ensure_phase2_shape(data: Dict[str, Any]) -> Dict[str, Any]:
    data.setdefault("phase2_history", [])
    ds = data.get("datasheet")
    if not isinstance(ds, dict):
        ds = {}; data["datasheet"] = ds
    for key, value in default_datasheet_state().items():
        ds.setdefault(key, deepcopy(value))
    # Promote legacy nested package exactly once.
    legacy_pkg = ds.pop("package", None)
    pkg = data.get("package")
    if not isinstance(pkg, dict):
        pkg = {}; data["package"] = pkg
    for key, value in default_package_state().items():
        pkg.setdefault(key, deepcopy(value))
    if isinstance(legacy_pkg, dict) and legacy_pkg.get("value") and not pkg.get("value"):
        apply_package_candidate(
            data, value=legacy_pkg.get("value"), source=(legacy_pkg.get("source") or "mouser"),
            resolved_by="phase2", exact_part_number_match=bool(legacy_pkg.get("exact_part_number_match")),
            attribute_name=legacy_pkg.get("attribute_name"),
        )
    ocr = data.setdefault("ocr", {})
    ocr.setdefault("manufacturer_marking", None); ocr.setdefault("country_marking", None)
    if ds.get("verified_exact_match") is True:
        data["manufacturer"] = ds.get("manufacturer"); data["country"] = ds.get("manufacturer_country")
    else:
        if data.get("manufacturer") and not ocr.get("manufacturer_marking"):
            ocr["manufacturer_marking"] = data.get("manufacturer")
        if data.get("country") and not ocr.get("country_marking"):
            ocr["country_marking"] = data.get("country")
        data["manufacturer"] = None; data["country"] = None
    return data


def relative_to_project(path: Path, project_root: Path) -> str:
    try: return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError: return path.as_posix()


def valid_pdf_from_state(data: Dict[str, Any], project_root: Path) -> bool:
    file_value = (data.get("datasheet") or {}).get("file")
    if not file_value: return False
    path = Path(str(file_value)); path = path if path.is_absolute() else project_root / path
    return core.is_existing_valid_pdf(path)


def historical_admin_datasheet_authority(data: Dict[str, Any], project_root: Path) -> tuple[bool, str]:
    """Prevent retrying web requests over an unrevoked human decision.

    Also recognizes older Integrated V4 Sales-only approvals, otherwise
    they would be overwritten again before the recovery tool is applied.
    """
    pn = product_part_number(data)
    if not pn:
        return False, ""
    event = latest_admin_datasheet_decision(data, pn)
    if not event:
        return False, ""
    action = event.get("action")
    local_pdf = project_root / "datasheets" / f"{pn}.pdf"
    if action == MANUAL_PDF_ACTION:
        recorded = str(event.get("file") or "")
        if recorded and Path(recorded.replace("\\", "/")).name.casefold() != f"{pn}.pdf".casefold():
            return True, "HISTORICAL_MANUAL_PDF_PATH_CONFLICT_REQUIRES_REVIEW"
        if core.is_existing_valid_pdf(local_pdf):
            return True, "HISTORICAL_MANUAL_PDF_EXISTS_REQUIRES_RECOVERY"
        return True, "HISTORICAL_MANUAL_PDF_MISSING_REQUIRES_REVIEW"
    if action in SALES_ONLY_ACTIONS:
        if local_pdf.is_file():
            return True, "HISTORICAL_SALES_ONLY_PDF_CONFLICT_REQUIRES_REVIEW"
        return True, "HISTORICAL_SALES_ONLY_REQUIRES_RECOVERY"
    return False, ""


def protected_datasheet_authority(data: Dict[str, Any], project_root: Path) -> tuple[bool, str]:
    ds = data.get("datasheet") or {}
    state = str(ds.get("status") or "").lower()
    if state == "completed" and valid_pdf_from_state(data, project_root):
        return True, "VALID_COMPLETED_PDF"
    if state == "sales_only_no_datasheet" and ds.get("sales_only_authorized") is True:
        return True, "ADMIN_AUTHORIZED_SALES_ONLY"
    # An approved checkpoint with lost datasheet is NOT eligible for an automatic
    # retry. It must be reconciled explicitly, without mutating its approval.
    if (data.get("admin_audit") or {}).get("status") == "APPROVED":
        return True, "APPROVED_REQUIRES_HUMAN_RECONCILIATION"
    return historical_admin_datasheet_authority(data, project_root)


def is_phase2_eligible(data: Dict[str, Any], project_root: Path, *, retry_not_found: bool=False, retry_manual: bool=False) -> tuple[bool, str]:
    ensure_phase2_shape(data)
    pn = product_part_number(data)
    if not pn: return False, "NO_PART_NUMBER"
    # PN readiness replaces the old stale status.regenpic summary. Phase 2 may run while Phase 1 finishes logo/optimization.
    regen_status = str((data.get("regeneration") or {}).get("status") or "")
    if regen_status not in {"completed"} and not pn:
        return False, "PHASE1_NOT_READY"
    ds = data["datasheet"]
    searched = str(ds.get("searched_part_number") or "").strip(); state = str(ds.get("status") or "pending")
    if searched and not exact(searched, pn):
        # A real PN correction explicitly invalidates stale search checkpoints.
        return True, "PART_NUMBER_CHANGED"
    audit = data.get("admin_audit") or {}
    explicitly_forced = bool(audit.get("force_phase2")) and audit.get("status") == "DISAPPROVED_PENDING_REPROCESS"
    if not explicitly_forced:
        protected, why = protected_datasheet_authority(data, project_root)
        if protected: return False, why
    if state == "completed":
        if searched and exact(searched, pn) and valid_pdf_from_state(data, project_root): return False, "COMPLETED_VALID"
        return True, "COMPLETED_BUT_FILE_OR_IDENTITY_INVALID"
    if state == "web_error" and not retry_manual: return False, "WEB_ERROR_AWAITING_ADMIN_DECISION"
    if state == "not_found_confirmed" and not retry_not_found: return False, "NOT_FOUND_CONFIRMED_CACHED"
    if state == "manual_required" and not retry_manual: return False, "MANUAL_REQUIRED_CACHED"
    if state == "sales_only_no_datasheet": return False, "SALES_ONLY_NOT_RETRYABLE_WITHOUT_NEW_ADMIN_DECISION"
    return True, state.upper() if state else "PENDING"


def invalidate_stale_datasheet(data: Dict[str, Any], reason: str) -> None:
    ensure_phase2_shape(data)
    old = data["datasheet"]; old_file = old.get("file"); old_searched = old.get("searched_part_number")
    data["datasheet"] = default_datasheet_state(); data["datasheet"].update({"status":"invalidated","last_error":reason,"updated_at":utc_now()})
    if old_file or old_searched:
        data.setdefault("phase2_history", []).append({"event":"datasheet_invalidated","reason":reason,"searched_part_number":old_searched,"file":old_file,"at":utc_now()})
    data["package"] = default_package_state(); data["package"]["status"] = "invalidated"; data["package"]["updated_at"] = utc_now()
    data["manufacturer"] = None; data["country"] = None


def mark_searching(data: Dict[str, Any], pn: str) -> None:
    ensure_phase2_shape(data)
    data["datasheet"] = default_datasheet_state(); data["datasheet"].update({
        "status":"searching","searched_part_number":pn,"identity_status":"SEARCHING",
        "manufacturer_country_status":"PENDING_EXACT_IDENTITY","started_at":utc_now(),"updated_at":utc_now(),
    })
    data["package"] = default_package_state(); data["package"]["sources_tried"] = ["mouser","datasheet4u","alldatasheet"]
    data["manufacturer"] = None; data["country"] = None


def _mapped_status(result: Result) -> str:
    return {"DOWNLOADED":"completed","ALREADY_EXISTS":"completed","ALLDATASHEET_MANUAL_DOWNLOAD_REQUIRED":"manual_required",
            "NOT_FOUND_CONFIRMED":"not_found_confirmed","UNRESOLVED_SOURCE_ERROR":"web_error",
            "IDENTITY_FOUND_DATASHEET_UNRESOLVED":"identity_found_unresolved","UNRESOLVED":"failed",
            "AMBIGUOUS_EXACT_MATCH":"identity_found_unresolved"}.get(result.status,"failed")


def apply_result(data: Dict[str, Any], result: Result, *, project_root: Path, destination: Path) -> None:
    ensure_phase2_shape(data)
    current_pn = product_part_number(data); mapped = _mapped_status(result)
    matched = str(result.matched_part_number or "").strip(); verified_exact = bool(matched and current_pn and exact(matched,current_pn))
    if verified_exact:
        manufacturer = str(result.manufacturer or "").strip() or None
        if manufacturer:
            country, country_status = resolve_manufacturer_country(manufacturer); identity_status="EXACT_PART_NUMBER_FOUND"
        else:
            country, country_status = None, "NOT_RESOLVED_NO_MANUFACTURER"; identity_status="EXACT_PART_NUMBER_FOUND_MANUFACTURER_UNRESOLVED"
    else:
        manufacturer=None; country=None; country_status="NOT_APPLICABLE_NO_EXACT_PART_NUMBER"
        identity_status="EXACT_PART_NUMBER_NOT_FOUND" if mapped=="not_found_confirmed" else "EXACT_PART_NUMBER_UNRESOLVED"
    local_file=None
    if mapped=="completed" and core.is_existing_valid_pdf(destination): local_file=relative_to_project(destination,project_root)
    elif mapped=="completed":
        mapped="failed"; result.note=(result.note+" | " if result.note else "")+"completed_result_without_valid_local_pdf"
    source_states={dbg.source:dbg.state for dbg in (result.source_debug or []) if dbg.source}
    data["datasheet"].update({
        "status":mapped,"searched_part_number":current_pn,"matched_part_number":matched or None,"verified_exact_match":verified_exact,
        "identity_status":identity_status,"manufacturer":manufacturer,"manufacturer_country":country,
        "manufacturer_country_status":country_status,"identity_source":result.identity_source or None,
        "document_source":result.document_source or None,"source_url":result.datasheet_url or None,"file":local_file,
        "mouser_part_number":result.mouser_part_number or None,"ambiguity_flag":result.ambiguity_flag or None,
        "ambiguity_source":result.ambiguity_source or None,"alternative_manufacturers":list(result.alternative_manufacturers or []),
        "ambiguity_selection_reason":result.ambiguity_selection_reason or None,"source_trace":list(result.trace or []),
        "source_states":source_states,"last_error":None if mapped in {"completed","not_found_confirmed","manual_required"} else (result.note or result.status),
        "completed_at":utc_now(),"updated_at":utc_now(),
    })
    data["package"]["sources_tried"] = list(source_states.keys()) or ["mouser","datasheet4u","alldatasheet"]
    package_value = result.package_value or result.mouser_package
    package_source = result.package_source or ("mouser" if result.mouser_package else "")
    package_attribute = result.package_attribute or result.mouser_package_attribute
    if verified_exact and package_value:
        apply_package_candidate(data, value=package_value, source=(package_source or "mouser"), resolved_by="phase2",
                                exact_part_number_match=True, attribute_name=package_attribute or None)
    elif not data["package"].get("value"):
        data["package"].update({"status":"unresolved","updated_at":utc_now()})
    data["manufacturer"] = manufacturer if verified_exact else None; data["country"] = country if verified_exact else None


class MetadataStore:
    def __init__(self, project_root: Path, *, schema_path: Optional[Path]=None, save_callback: Optional[Callable[[Path,Dict[str,Any]],None]]=None):
        self.project_root=project_root; self.schema_path=schema_path; self.save_callback=save_callback; self._validator=None
        if schema_path and schema_path.exists():
            schema=json.loads(schema_path.read_text(encoding="utf-8")); Draft202012Validator.check_schema(schema); self._validator=Draft202012Validator(schema)
    def load(self,path:Path)->Dict[str,Any]:
        with path.open("r",encoding="utf-8-sig") as f: data=json.load(f)
        if not isinstance(data,dict): raise ValueError(f"Metadata root must be object: {path}")
        return ensure_phase2_shape(data)
    def save(self,path:Path,data:Dict[str,Any])->None:
        if self.save_callback is not None: self.save_callback(path,data); return
        if self._validator is not None:
            errors=sorted(self._validator.iter_errors(data),key=lambda e:list(e.path))
            if errors:
                first=errors[0]; where=".".join(str(p) for p in first.path) or "<root>"; raise ValueError(f"Metadata schema validation failed at {where}: {first.message}")
        path.parent.mkdir(parents=True,exist_ok=True); fd,tmp_name=tempfile.mkstemp(prefix=path.name+".",suffix=".tmp",dir=str(path.parent))
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:
                json.dump(data,f,ensure_ascii=False,indent=2); f.write("\n"); f.flush(); os.fsync(f.fileno())
            os.replace(tmp_name,path)
        except Exception:
            try: os.unlink(tmp_name)
            except OSError: pass
            raise
