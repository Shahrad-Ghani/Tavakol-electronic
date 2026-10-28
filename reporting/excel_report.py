from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from phase4.publisher_state import PublisherStateStore, REQUIRED_STEPS
from phase3_fact_extraction.mosfet_specs import resolve_for_product

HEADERS = [
    "PN",
    "P1 Precheck",
    "P1 Regeneration",
    "P1 Identity Validation",
    "P1 OCR",
    "P1 Logo",
    "P1 Image Optimization",
    "P2 Datasheet",
    "P2 Package",
    "P3 Fact Extraction",
    "P3 Content",
    "P3 SEO Validator",
    "P3 Tone Editor",
    "P3 Semantic Audit",
    "Admin Audit",
    "MOSFET Specs",
    "Phase 4",
]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _identity_status(meta: dict[str, Any]) -> str:
    block = meta.get("identity_validation") or {}
    status = str(block.get("status") or "pending")
    if status == "completed":
        return "passed" if block.get("pass") is True else "failed"
    return status


def _package_status(meta: dict[str, Any]) -> str:
    package = meta.get("package") or {}
    value = str(package.get("value") or "").strip()
    if value:
        source = str(package.get("source") or "unknown")
        return f"resolved: {value} [{source}]"
    return str(package.get("status") or "unresolved")


def _validator_status(meta: dict[str, Any]) -> str:
    p3 = meta.get("phase3") or {}
    score = p3.get("seo_score")
    publishable = p3.get("validator_publishable")
    if score is None and publishable is None:
        return "not_started"
    return f"score={score if score is not None else '-'}; publishable={publishable}"


def _admin_status(meta: dict[str, Any]) -> str:
    audit = meta.get("admin_audit") or {}
    status = str(audit.get("status") or "PENDING_REVIEW")
    classification = str(audit.get("classification") or "-")
    return f"{status}/{classification}"


def _phase4_status(store: PublisherStateStore, pn: str) -> str:
    state = store.load(pn)
    steps = state.get("steps") or {}
    all_required_ok = all((steps.get(step) or {}).get("status") == "success" for step in REQUIRED_STEPS)
    return "successful" if state.get("successful") is True and all_required_ok else "unsuccessful"


def _mosfet_status(root: Path, meta: dict[str, Any], pn: str) -> str:
    category = meta.get('category') if isinstance(meta.get('category'),dict) else {}
    if category.get('key') != 'mosfet':
        return 'N/A'
    specs = (meta.get('phase3') or {}).get('mosfet_specs') or resolve_for_product(root, pn, 'mosfet')
    names = ('channel_type','vds','id_continuous')
    detail = ', '.join(f'{k}={(specs.get(k) or {}).get("value") or "MISSING"}' for k in names)
    missing = [k for k in names if not (specs.get(k) or {}).get('value')]
    return f'{detail}; NEEDS_ADMIN={"|".join(missing)}' if missing else detail


def collect_rows(root: Path) -> list[list[Any]]:
    root = Path(root).resolve()
    store = PublisherStateStore(root)
    rows: list[list[Any]] = []
    for meta_path in sorted((root / "metadata").glob("*.json"), key=lambda p: p.stem.casefold()):
        try:
            meta = _read_json(meta_path)
        except Exception:
            continue
        pn = str(meta.get("part_number") or "").strip() or meta_path.stem
        p3 = meta.get("phase3") or {}
        rows.append([
            pn,
            str((meta.get("precheck") or {}).get("status") or "pending"),
            str((meta.get("regeneration") or {}).get("status") or "pending"),
            _identity_status(meta),
            str((meta.get("ocr") or {}).get("status") or "pending"),
            str((meta.get("logo") or {}).get("status") or "pending"),
            str((meta.get("image_optimization") or {}).get("status") or "pending"),
            str((meta.get("datasheet") or {}).get("status") or "pending"),
            _package_status(meta),
            str(p3.get("facts_status") or "not_started"),
            str(p3.get("content_status") or "not_started"),
            _validator_status(meta),
            str(p3.get("tone_status") or "not_started"),
            str(p3.get("semantic_audit_status") or "not_started"),
            _admin_status(meta),
            _mosfet_status(root, meta, pn),
            _phase4_status(store, pn),
        ])
    return rows


def generate_report(root: Path, output_dir: Path | None = None) -> Path:
    root = Path(root).resolve()
    output_dir = Path(output_dir or (root / "reports")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{datetime.now().strftime('%Y-%m-%d')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Pipeline Report"
    ws.append(HEADERS)
    for row in collect_rows(root):
        ws.append(row)

    header_fill = PatternFill("solid", fgColor="1F4E78")
    header_font = Font(color="FFFFFF", bold=True)
    green_fill = PatternFill("solid", fgColor="C6EFCE")
    red_fill = PatternFill("solid", fgColor="FFC7CE")
    thin = Side(style="thin", color="D9E1F2")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    phase4_col = HEADERS.index("Phase 4") + 1
    package_col = HEADERS.index("P2 Package") + 1
    mosfet_col = HEADERS.index("MOSFET Specs") + 1
    for row_idx in range(2, ws.max_row + 1):
        status = str(ws.cell(row=row_idx, column=phase4_col).value or "")
        fill = green_fill if status == "successful" else red_fill
        for col_idx in range(1, ws.max_column + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = fill
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=True)

        # V3.1 exception: unresolved package does not make Phase 4 unsuccessful.
        # Flag only the package cell in red while preserving the Phase 4 outcome.
        package_cell = ws.cell(row=row_idx, column=package_col)
        package_text = str(package_cell.value or "").strip().casefold()
        if package_text == "unresolved" or package_text.startswith("unresolved"):
            package_cell.fill = red_fill
        if 'NEEDS_ADMIN=' in str(ws.cell(row=row_idx,column=mosfet_col).value or ''):
            ws.cell(row=row_idx,column=mosfet_col).fill = red_fill

    widths = [18, 16, 18, 22, 14, 14, 22, 22, 42, 20, 18, 28, 18, 20, 28, 60, 16]
    for i, width in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 32
    wb.save(output)
    return output
