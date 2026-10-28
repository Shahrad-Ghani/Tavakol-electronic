from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.metadata_v3 import utcnow
from metadata_manager import save_admin_override

REQUIRED_STEPS = (
    "image",
    "title_content",
    "datasheet",
    "attributes",
    "category",
    "short_description",
    "snippet",
    "sku",
    "focus_keyword",
    "save_draft",
)


def _atomic_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


class PublisherStateStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.folder = self.root / "runtime_state" / "publisher"
        self.folder.mkdir(parents=True, exist_ok=True)

    def path(self, pn: str) -> Path:
        return self.folder / f"{pn}.json"

    def load(self, pn: str) -> dict[str, Any]:
        path = self.path(pn)
        if not path.exists():
            now = utcnow()
            return {
                "schema_version": "3.0",
                "part_number": pn,
                "status": "NOT_STARTED",
                "successful": None,
                "wordpress_product_id": None,
                "wordpress_edit_url": None,
                "steps": {step: {"status": "pending", "error": None, "updated_at": None} for step in REQUIRED_STEPS},
                "started_at": None,
                "completed_at": None,
                "updated_at": now,
            }
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("steps", {})
        # Migrate V4.0.4's mislabeled permalink step to the actual Snippet step.
        if "permalink" in data["steps"] and "snippet" not in data["steps"]:
            data["steps"]["snippet"] = data["steps"].pop("permalink")
        for step in REQUIRED_STEPS:
            data["steps"].setdefault(step, {"status": "pending", "error": None, "updated_at": None})
        return data

    def save(self, pn: str, data: dict[str, Any]) -> dict[str, Any]:
        data["schema_version"] = "3.0"
        data["part_number"] = pn
        data["updated_at"] = utcnow()
        _atomic_json(self.path(pn), data)
        return data

    def begin(self, pn: str) -> dict[str, Any]:
        data = self.load(pn)
        if data.get("wordpress_product_id"):
            return data
        data["status"] = "RUNNING"
        data["successful"] = None
        data["started_at"] = data.get("started_at") or utcnow()
        return self.save(pn, data)

    def record_step(self, pn: str, step: str, *, success: bool, error: str | None = None, detail: Any = None) -> dict[str, Any]:
        if step not in REQUIRED_STEPS:
            raise ValueError(f"Unknown publisher step: {step}")
        data = self.load(pn)
        entry = data["steps"][step]
        entry.update({
            "status": "success" if success else "failed",
            "error": None if success else str(error or "unknown error"),
            "updated_at": utcnow(),
        })
        if detail is not None:
            entry["detail"] = detail
        return self.save(pn, data)

    def finalize_draft(self, pn: str, *, post_id: str, edit_url: str) -> dict[str, Any]:
        data = self.load(pn)
        data["wordpress_product_id"] = str(post_id)
        data["wordpress_edit_url"] = edit_url
        all_ok = all((data.get("steps", {}).get(step) or {}).get("status") == "success" for step in REQUIRED_STEPS)
        data["successful"] = all_ok
        data["status"] = "DRAFT_SAVED" if all_ok else "DRAFT_SAVED_WITH_WARNINGS"
        data["completed_at"] = utcnow()
        return self.save(pn, data)

    def mark_failed(self, pn: str, error: str) -> dict[str, Any]:
        data = self.load(pn)
        data["status"] = "FAILED"
        data["successful"] = False
        data["error"] = str(error)
        data["completed_at"] = utcnow()
        return self.save(pn, data)

    def mark_existing_site(self, pn: str, *, post_id: str, edit_url: str) -> dict[str, Any]:
        data = self.load(pn)
        data['wordpress_product_id'] = str(post_id)
        data['wordpress_edit_url'] = str(edit_url)
        data['status'] = 'EXISTING_SITE_SKIPPED'
        data['successful'] = None  # Existing ≠ published correctly by this batch.
        data['error'] = 'Existing WordPress product requires manual review; no duplicate was created'
        return self.save(pn, data)

    def duplicate_guard(self, pn: str) -> tuple[bool, dict[str, Any]]:
        data = self.load(pn)
        exists = bool(data.get("wordpress_product_id")) or data.get("status") in {"DRAFT_SAVED", "DRAFT_SAVED_WITH_WARNINGS"}
        return exists, data


def sync_publisher_summary_to_metadata(root: Path, pn: str, publisher_state: dict[str, Any]) -> None:
    meta_path = Path(root) / "metadata" / f"{pn}.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    steps = publisher_state.get("steps") or {}
    step_errors = {k: v.get("error") for k, v in steps.items() if v.get("status") == "failed"}
    pub = meta.setdefault("publishing", {})
    pub.update({
        "status": publisher_state.get("status") or "NOT_STARTED",
        "successful": publisher_state.get("successful"),
        "wordpress_product_id": publisher_state.get("wordpress_product_id"),
        "wordpress_edit_url": publisher_state.get("wordpress_edit_url"),
        "completed_with_warnings": publisher_state.get("status") == "DRAFT_SAVED_WITH_WARNINGS",
        "step_errors": step_errors,
        "updated_at": utcnow(),
    })
    save_admin_override(meta_path, meta)
