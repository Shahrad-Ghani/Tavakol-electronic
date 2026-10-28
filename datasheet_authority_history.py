"""Read authoritative human datasheet decisions from legacy and current Audit history.

History is chronological. A later wrong-PN/datasheet rejection revokes earlier
human authority until a fresh explicit action is recorded. This module only
interprets decisions; it never changes or approves a product.
"""
from __future__ import annotations

from typing import Any

SALES_ONLY_ACTIONS = frozenset({
    "ADMIN_SALES_ONLY_AFTER_WEB_ERROR",
    "AUTHORIZE_SALES_ONLY_WITHOUT_DATASHEET",  # Integrated V4 legacy
})
MANUAL_PDF_ACTION = "MANUAL_DATASHEET_ATTACHED"
DECISIONS = SALES_ONLY_ACTIONS | {MANUAL_PDF_ACTION}
INVALIDATION_ISSUES = frozenset({"wrong_part_number", "wrong_data_sheet"})


def latest_admin_datasheet_decision(data: dict[str, Any], pn: str) -> dict[str, Any] | None:
    """Return the latest still-valid, PN-specific human datasheet decision.

    DISAPPROVE with identity/datasheet invalidation resets previous authority;
    other review events (including later APPROVE) cannot magically restore it.
    A decision recorded for another PN is never authority for this PN.
    """
    history = (data.get("admin_audit") or {}).get("history") or []
    if not isinstance(history, list):
        return None
    chosen = None
    for item in history:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or "")
        event_pn = str(item.get("part_number") or "").strip()
        pn_matches = bool(event_pn) and event_pn.casefold() == pn.strip().casefold()
        if action == "DISAPPROVE":
            issues = item.get("issues") or item.get("selected_issues") or []
            if isinstance(issues, str):
                issues = [issues]
            if isinstance(issues, (list, tuple, set)) and INVALIDATION_ISSUES.intersection(issues):
                if pn_matches or not event_pn:
                    chosen = None
        elif action in DECISIONS and pn_matches:
            chosen = item
    return chosen
