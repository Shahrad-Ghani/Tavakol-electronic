import hashlib
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from phase2.banner_injector import MARKER_KEY, MARKER_VALUE, inject_batch

ROOT = Path(__file__).resolve().parents[1]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_batch_banner_creates_branded_copy_without_mutating_source(tmp_path):
    source_dir = tmp_path / "datasheets"
    output_dir = tmp_path / "datasheets_branded"
    source_dir.mkdir()
    source_pdf = source_dir / "TEST123.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=595, height=842)
    with source_pdf.open("wb") as fh:
        writer.write(fh)
    original_hash = _sha(source_pdf)
    original_height = float(PdfReader(str(source_pdf)).pages[0].mediabox.height)

    result = inject_batch(
        source_dir,
        ROOT / "assets" / "banner.png",
        "https://tavakolelectronic.com/",
        output_dir=output_dir,
    )

    branded_pdf = output_dir / source_pdf.name
    assert result["errors"] == {}
    assert branded_pdf.is_file()
    assert _sha(source_pdf) == original_hash
    assert (PdfReader(str(source_pdf)).metadata or {}).get(MARKER_KEY) is None
    branded = PdfReader(str(branded_pdf))
    assert str((branded.metadata or {}).get(MARKER_KEY)) == MARKER_VALUE
    assert len(branded.pages) == 2
    assert float(branded.pages[0].mediabox.height) > original_height
