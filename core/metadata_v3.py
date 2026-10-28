from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import json

from core.category_registry import category_context, normalize_category_key, product_title

SCHEMA_VERSION = "3.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_pn(value: str | None) -> str:
    pn = str(value or "").strip()
    if not pn:
        raise ValueError("part_number is required")
    return pn


def get_category_key(data: Dict[str, Any]) -> str:
    block = data.get("category") if isinstance(data.get("category"), dict) else {}
    raw = block.get("key") or data.get("product_type") or "ic"
    return normalize_category_key(raw) or "ic"


def deterministic_product_title(part_number: str, category_key: str | None = None) -> str:
    return product_title(normalize_pn(part_number), normalize_category_key(category_key) or "ic")


def sync_category(data: Dict[str, Any], category_key: str | None = None) -> Dict[str, Any]:
    key = normalize_category_key(category_key) or get_category_key(data)
    ctx = category_context(key)
    data["product_type"] = key
    data["category"] = {
        "key": key,
        "display_name": ctx["display_name"],
        "title_prefix": ctx["title_prefix"],
        "density_phrase": ctx["density_phrase"],
        "slug_rule": ctx["slug_rule"],
        "category_url": ctx["category_url"],
        "wordpress": deepcopy(ctx["wordpress"]),
        "technical_focus": deepcopy(ctx.get("technical_focus") or []),
    }
    return data


def get_part_number(data: Dict[str, Any]) -> str:
    return str(data.get("part_number") or data.get("PartNumber") or "").strip()


def get_source_reference(data: Dict[str, Any]) -> str:
    return str(data.get("source_reference") or data.get("img_refrence_name") or data.get("product_id") or "").strip()


def stage_completed(block: Any, *, allow_manual_override: bool = False) -> bool:
    if not isinstance(block, dict):
        return False
    status = str(block.get("status") or "").strip().lower()
    allowed = {"completed"}
    if allow_manual_override:
        allowed.add("manual_override")
    return status in allowed


def image_finalized(data: Dict[str, Any]) -> bool:
    return stage_completed(data.get("image_optimization")) and bool((data.get("image_optimization") or {}).get("file"))


def phase1_status(data: Dict[str, Any]) -> str:
    required = (
        stage_completed(data.get("precheck")),
        stage_completed(data.get("regeneration")),
        bool((data.get("identity_validation") or {}).get("pass")) and stage_completed(data.get("identity_validation")),
        stage_completed(data.get("ocr"), allow_manual_override=True),
        stage_completed(data.get("logo")),
        image_finalized(data),
    )
    if all(required):
        return "completed"
    if get_part_number(data):
        return "pn_ready"
    return "in_progress"


def new_metadata(source_reference: str, *, product_id: Optional[str] = None, product_type: str = "IC") -> Dict[str, Any]:
    ref = str(source_reference or "").strip()
    now = utcnow()
    return {
        "schema_version": SCHEMA_VERSION,
        "product_id": product_id or ref,
        "product_type": normalize_category_key(product_type) or "ic",
        "category": {},
        "source_reference": ref,
        "part_number": None,
        "product_title": None,
        "manufacturer": None,
        "country": None,
        "original_image": {
            "file": None,
            "source": "input",
            "part_number_authority": "OCR",
            "note": None,
        },
        "precheck": {"status": "pending"},
        "regeneration": {"status": "pending", "attempt_history": []},
        "identity_validation": {"status": "pending", "pass": None, "history": []},
        "ocr": {"status": "pending", "primary_code": None},
        "logo": {"status": "pending", "file": None},
        "image_optimization": {"status": "pending", "file": None},
        "datasheet": {
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
        },
        "package": {
            "value": None,
            "source": None,
            "attribute_name": None,
            "status": "unresolved",
            "resolved_by": None,
            "exact_part_number_match": False,
            "sources_tried": [],
            "updated_at": None,
        },
        "phase2_history": [],
        "phase3": {
            "status": "not_started",
            "facts_status": "not_started",
            "content_status": "not_started",
            "json_file": None,
            "content_file": None,
            "seo_score": None,
            "validator_publishable": None,
            "tone_status": None,
            "seo_agent_status": None,
            "seo_title": None,
            "meta_description": None,
            "slug": None,
            "semantic_audit_status": None,
            "package_fallback_attempted": False,
            "updated_at": None,
        },
        "admin_audit": {
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
        },
        "publishing": {
            "release_allowed": False,
            "release_source": None,
            "bundle_status": "NOT_BUILT",
            "bundle_path": None,
            "status": "NOT_STARTED",
            "successful": None,
            "wordpress_product_id": None,
            "wordpress_edit_url": None,
            "completed_with_warnings": False,
            "step_errors": {},
            "updated_at": None,
        },
        "diagnostics": {
            "api_accounting": {},
            "legacy": {},
        },
        "created_at": now,
        "updated_at": now,
    }


def sync_identity(data: Dict[str, Any]) -> Dict[str, Any]:
    sync_category(data)
    pn = get_part_number(data)
    if pn:
        data["part_number"] = pn
        data["product_title"] = deterministic_product_title(pn, get_category_key(data))
    return data


def sync_release_gate(data: Dict[str, Any]) -> Dict[str, Any]:
    audit = data.get("admin_audit") or {}
    approved = audit.get("status") == "APPROVED" and audit.get("classification") == "FINALIZED"
    pub = data.setdefault("publishing", {})
    pub["release_allowed"] = bool(approved)
    pub["release_source"] = "ADMIN_AUDIT" if approved else None
    pub["updated_at"] = utcnow()
    return data


def save_metadata(path: Path, data: Dict[str, Any]) -> None:
    payload = deepcopy(data)
    payload["schema_version"] = SCHEMA_VERSION
    sync_identity(payload)
    sync_release_gate(payload)
    payload["updated_at"] = utcnow()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_metadata(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
