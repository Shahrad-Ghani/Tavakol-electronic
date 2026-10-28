import hashlib
import shutil
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def build_pdf_window(original_pdf, output_pdf, max_pages=5):
    """Create the exact first-page PDF artifact sent to Altimate V1 PDF extraction models.

    The original datasheet is never modified. When the document has more than
    max_pages, only the first max_pages are written. Shorter documents are
    byte-copied so the model still sees the complete source.
    """
    from pypdf import PdfReader, PdfWriter

    original_pdf = Path(original_pdf).resolve()
    output_pdf = Path(output_pdf).resolve()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(original_pdf), strict=False)
    total_pages = len(reader.pages)
    if total_pages < 1:
        raise RuntimeError(f'PDF contains no pages: {original_pdf}')

    sent_pages = min(int(max_pages), total_pages)
    if total_pages <= int(max_pages):
        shutil.copy2(original_pdf, output_pdf)
    else:
        writer = PdfWriter()
        for i in range(sent_pages):
            writer.add_page(reader.pages[i])
        with output_pdf.open('wb') as f:
            writer.write(f)

    return {
        'policy': 'FIRST_N_PAGES',
        'max_pages': int(max_pages),
        'original_pages': total_pages,
        'pages_sent_to_models': sent_pages,
        'truncated': total_pages > sent_pages,
        'original_pdf_sha256': sha256_file(original_pdf),
        'model_pdf_sha256': sha256_file(output_pdf),
        'model_pdf_filename': output_pdf.name,
    }
