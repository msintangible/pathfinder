import io
import zipfile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError


class DocxExtractionError(Exception):
    pass


def extract_docx_text(docx_bytes: bytes) -> str:
    """Extract and concatenate paragraph text from a .docx file."""
    try:
        document = Document(io.BytesIO(docx_bytes))
    except (PackageNotFoundError, zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DocxExtractionError(f"Could not read DOCX: {exc}") from exc

    paragraphs = (p.text.strip() for p in document.paragraphs)
    return "\n\n".join(p for p in paragraphs if p)
