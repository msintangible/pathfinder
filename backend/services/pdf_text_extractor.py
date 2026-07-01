import io

from pypdf import PdfReader
from pypdf.errors import PdfReadError


class PDFExtractionError(Exception):
    pass


def extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract and concatenate text from every page of a PDF."""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise PDFExtractionError(f"Could not read PDF: {exc}") from exc

    return "\n\n".join(page.strip() for page in pages if page.strip())
