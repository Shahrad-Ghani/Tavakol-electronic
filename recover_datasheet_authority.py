"""Altimate V1.0.1: restore proven human datasheet decisions overwritten by Phase2.

Default dry-run; --apply writes ONLY audited, previously WEB_ERROR metadata.
No approvals, content, files or historical records are deleted or regenerated.
For a manually attached PDF, the human audit event is authoritative for PN;
this script verifies the file and page count, not document contents/markings.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from datasheet_authority_history import (
    MANUAL_PDF_ACTION, SALES_ONLY_ACTIONS, latest_admin_datasheet_decision,
)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _decision(data: dict, pn: str):
    return latest_admin_datasheet_decision(data, pn)


def _check_pdf(path: Path) -> tuple[bool, str]:
    try:
        if not path.is_file() or path.stat().st_size < 100:
            return False, "PDF_MISSING_OR_TOO_SMALL"
        with path.open("rb") as file:
            if file.read(5) != b"%PDF-":
                return False, "PDF_SIGNATURE_INVALID"
        reader = PdfReader(str(path), strict=False)
        pages = len(reader.pages)
        if pages < 1:
            return False, "PDF_HAS_NO_PAGES"
        return True, f"PDF_READABLE_{pages}_PAGES"
    except Exception as exc:
        return False, f"PDF_UNREADABLE_{type(exc).__name__}: {exc}"


def propose(root: Path, path: Path, data: dict) -> tuple[str, str, dict | None]:
    pn = str(data.get("part_number") or "").strip()
    if not pn or pn.casefold() != path.stem.casefold():
        return "SKIP", "PN_FILENAME_MISMATCH_OR_MISSING", None
    if (data.get("datasheet") or {}).get("status") != "web_error":
        return "SKIP", "NOT_WEB_ERROR", None
    event = _decision(data, pn)
    if not event:
        return "MANUAL_REVIEW", "NO_UNREVOKED_ADMIN_DATASHEET_DECISION", None

    result = json.loads(json.dumps(data))
    ds = result.setdefault("datasheet", {})
    audit = result.get("admin_audit") or {}
    changed_at = now()
    if event.get("action") == MANUAL_PDF_ACTION:
        path_value = str(event.get("file") or "")
        if path_value and Path(path_value.replace('\\','/')).name.casefold() != f"{pn}.pdf".casefold():
            return "MANUAL_REVIEW", "HISTORICAL_PDF_FILENAME_MISMATCH", None
        target = root / "datasheets" / f"{pn}.pdf"
        valid, why = _check_pdf(target)
        if not valid:
            return "MANUAL_REVIEW", why, None
        ds.update({
            "status": "completed", "file": f"datasheets/{pn}.pdf",
            "searched_part_number": pn, "matched_part_number": pn,
            "verified_exact_match": True, "identity_status": "EXACT_PART_NUMBER_FOUND",
            "identity_source": "ADMIN_AUDIT_MANUAL", "document_source": "ADMIN_AUDIT_MANUAL",
            "last_error": None, "updated_at": changed_at,
        })
        kind = "RESTORE_MANUAL_PDF"
        note = why + "; physical PN/content still requires admin review"
    elif event.get("action") in SALES_ONLY_ACTIONS:
        target = root / "datasheets" / f"{pn}.pdf"
        if target.is_file():
            return "MANUAL_REVIEW", "PDF_EXISTS_CONFLICTS_WITH_SALES_ONLY", None
        ds.update({
            "status": "sales_only_no_datasheet", "file": None,
            "sales_only_authorized": True,
            "sales_only_authorized_at": event.get("at") or changed_at,
            "sales_only_reason": "ADMIN_CHOICE_AFTER_WEB_ERROR; does not prove absence",
            "document_source": None, "last_error": None, "updated_at": changed_at,
        })
        kind, note = "RESTORE_SALES_ONLY", "previous human authorization present"
    else:
        return "MANUAL_REVIEW", "UNSUPPORTED_DECISION", None

    # No automatic approval, no reprocessing of finished SEO content, no
    # modification to the selected category / PN / publication snapshot.
    result.setdefault("phase2_history", []).append({
        "event": "ALTIMATE_V1_0_1_RECOVER_ADMIN_AUTHORITY", "at": changed_at,
        "part_number": pn, "restored_status": ds["status"],
        "source_action": event["action"], "previous_status": "web_error",
    })
    if audit.get("status") == "APPROVED":
        note += "; EXISTING_APPROVAL_UNCHANGED_VERIFY_BUNDLE"
    return kind, note, result


def run(root: Path, *, apply: bool = False, report: Path | None = None) -> list[dict[str, str]]:
    root = root.resolve()
    if not (root / 'metadata').is_dir():
        raise FileNotFoundError(f"metadata folder missing: {root}")
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup_dir = root / 'audit_history' / f'Altimate_V1_0_1_recovery_{stamp}'
    rows: list[dict[str, str]] = []
    for path in sorted((root / 'metadata').glob('*.json')):
        pn = path.stem
        try:
            source = path.read_bytes()
            data = json.loads(source.decode('utf-8-sig'))
            if (data.get('datasheet') or {}).get('status') != 'web_error':
                continue
            kind, why, proposal = propose(root, path, data)
            row = {'part_number': pn, 'action': kind, 'explanation': why}
            rows.append(row)
            if apply and proposal is not None:
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_dir / path.name)
                # File-specific temp names and replace; never touch unrelated files.
                fd, temp_name = tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=str(path.parent))
                try:
                    with os.fdopen(fd, 'w', encoding='utf-8') as file:
                        json.dump(proposal,file,indent=2,ensure_ascii=False)
                        file.write('\n')
                        file.flush(); os.fsync(file.fileno())
                    os.replace(temp_name,path)
                finally:
                    if os.path.exists(temp_name): os.unlink(temp_name)
        except Exception as exc:
            rows.append({'part_number':pn,'action':'ERROR','explanation':f'{type(exc).__name__}: {exc}'})
    if report:
        report.parent.mkdir(parents=True,exist_ok=True)
        with report.open('w',encoding='utf-8-sig',newline='') as out:
            writer=csv.DictWriter(out,fieldnames=['part_number','action','explanation'])
            writer.writeheader();writer.writerows(rows)
    from collections import Counter
    counts=Counter(r['action'] for r in rows)
    print('MODE:', 'APPLY' if apply else 'DRY-RUN (NO CHANGES)')
    print('ROOT:', root)
    print('RESULTS:', dict(counts))
    for r in rows:
        if r['action'] in ('RESTORE_MANUAL_PDF','RESTORE_SALES_ONLY','ERROR'):
            print(f" {r['action']:21} {r['part_number']:22} {r['explanation']}")
    if apply:
        print('BACKUPS:', backup_dir if backup_dir.exists() else 'no files changed')
    print('No products were automatically approved or published.')
    return rows


def main():
    parser=argparse.ArgumentParser(description='Recover historically human-authorized datasheet decisions, preserving audit/publishing state')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--apply',action='store_true')
    group.add_argument('--dry-run',action='store_true')
    parser.add_argument('--report',type=Path,help='Optional CSV report file path')
    args=parser.parse_args()
    run(args.root,apply=args.apply,report=args.report)

if __name__=='__main__':
    main()
