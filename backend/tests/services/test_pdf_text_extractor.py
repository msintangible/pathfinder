import io

import pytest
from reportlab.pdfgen import canvas

from services.pdf_text_extractor import PDFExtractionError, extract_pdf_text


def _make_pdf(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    y = 800
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buffer.getvalue()


def test_extracts_text_from_single_page():
    pdf_bytes = _make_pdf(["Jane Doe", "Senior Software Engineer"])

    text = extract_pdf_text(pdf_bytes)

    assert "Jane Doe" in text
    assert "Senior Software Engineer" in text


def test_extracts_text_across_multiple_pages():
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    c.drawString(72, 800, "Page one content")
    c.showPage()
    c.drawString(72, 800, "Page two content")
    c.save()

    text = extract_pdf_text(buffer.getvalue())

    assert "Page one content" in text
    assert "Page two content" in text


def test_raises_on_corrupt_pdf():
    with pytest.raises(PDFExtractionError):
        extract_pdf_text(b"not a real pdf")
