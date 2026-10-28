from pathlib import Path

from pypdf import PdfReader, PdfWriter

from phase2.banner_injector import MARKER_KEY, MARKER_VALUE, inject_banner

ROOT = Path(__file__).resolve().parents[1]


def test_datasheet_banner_is_added_linked_and_idempotent(tmp_path):
    pdf = tmp_path / "TEST123.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with pdf.open("wb") as fh:
        writer.write(fh)

    original_h = float(PdfReader(str(pdf)).pages[0].mediabox.height)
    changed = inject_banner(pdf, ROOT / "assets" / "banner.png", "https://tavakolelectronic.com/")
    assert changed is True

    reader = PdfReader(str(pdf))
    assert str((reader.metadata or {}).get(MARKER_KEY)) == MARKER_VALUE
    assert float(reader.pages[0].mediabox.height) > original_h
    annots = reader.pages[0].get("/Annots") or []
    assert annots
    urls = []
    for ref in annots:
        obj = ref.get_object()
        action = obj.get("/A")
        if action and action.get("/URI"):
            urls.append(str(action.get("/URI")))
    assert "https://tavakolelectronic.com/" in urls

    assert inject_banner(pdf, ROOT / "assets" / "banner.png", "https://tavakolelectronic.com/") is False
