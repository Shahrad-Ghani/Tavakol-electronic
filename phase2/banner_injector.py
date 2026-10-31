from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from pypdf._page import PageObject
from pypdf.annotations import Link

MARKER_KEY = "/TavakolDatasheetBanner"
MARKER_VALUE = "CatalogAutomationAgent-V4"


def has_banner(pdf_path: Path) -> bool:
    try:
        r = PdfReader(str(pdf_path))
        return str((r.metadata or {}).get(MARKER_KEY) or "") == MARKER_VALUE
    except Exception:
        return False


def inject_banner(pdf_path: Path, banner_path: Path, target_url: str) -> bool:
    """Add the store banner above page 1 and link the banner rectangle to target_url.

    The transform is idempotent: PDFs written by this function carry a metadata marker.
    Returns True only when the file was changed.
    """
    pdf_path = Path(pdf_path)
    banner_path = Path(banner_path)
    if has_banner(pdf_path):
        return False
    if not banner_path.exists():
        raise FileNotFoundError(f"Datasheet banner missing: {banner_path}")

    reader = PdfReader(str(pdf_path))
    if not reader.pages:
        raise ValueError(f"PDF has no pages: {pdf_path}")
    first = reader.pages[0]
    page_w = float(first.mediabox.width)
    page_h = float(first.mediabox.height)

    img = Image.open(banner_path).convert("RGB")
    ratio = img.width / img.height
    banner_h = page_w / ratio
    bio = io.BytesIO()
    img.save(bio, format="PDF", resolution=72.0)
    bio.seek(0)
    bpage = PdfReader(bio).pages[0]
    bw, bh = float(bpage.mediabox.width), float(bpage.mediabox.height)
    scale = page_w / bw

    new_first = PageObject.create_blank_page(width=page_w, height=page_h + banner_h)
    new_first.merge_transformed_page(first, Transformation().translate(tx=0, ty=0))
    new_first.merge_transformed_page(bpage, Transformation().scale(scale, scale).translate(tx=0, ty=page_h))

    writer = PdfWriter()
    writer.add_page(new_first)
    writer.add_annotation(page_number=0, annotation=Link(rect=(0, page_h, page_w, page_h + banner_h), url=target_url))
    for page in reader.pages[1:]:
        writer.add_page(page)
    metadata = dict(reader.metadata or {})
    metadata[MARKER_KEY] = MARKER_VALUE
    writer.add_metadata({str(k): str(v) for k, v in metadata.items() if v is not None})

    fd, tmp = tempfile.mkstemp(prefix=pdf_path.stem + ".banner.", suffix=".pdf", dir=str(pdf_path.parent))
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            writer.write(f)
        os.replace(tmp, pdf_path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


def inject_batch(
    datasheets_dir: Path,
    banner_path: Path,
    target_url: str,
    *,
    output_dir: Path | None = None,
) -> dict:
    """Create branded copies while leaving Phase 2's authoritative PDFs untouched.

    When output_dir is omitted, legacy in-place behavior is retained for callers
    that explicitly depend on it. The integrated orchestrator always supplies a
    separate output directory.
    """
    source_dir = Path(datasheets_dir)
    destination_dir = Path(output_dir) if output_dir is not None else source_dir
    destination_dir.mkdir(parents=True, exist_ok=True)
    result = {"changed": [], "skipped": [], "errors": {}, "output_dir": str(destination_dir.resolve())}
    for pdf in sorted(source_dir.glob("*.pdf"), key=lambda p: p.name.casefold()):
        try:
            target = destination_dir / pdf.name
            if output_dir is not None:
                # Rebuild from the pristine source every run. Never stack banners
                # or accidentally feed a previously branded file into extraction.
                shutil.copy2(pdf, target)
            if inject_banner(target, banner_path, target_url):
                result["changed"].append(pdf.name)
            else:
                result["skipped"].append(pdf.name)
        except Exception as exc:
            result["errors"][pdf.name] = f"{type(exc).__name__}: {exc}"
    return result
