import io

import docx
import pytest

from services.docx_text_extractor import DocxExtractionError, extract_docx_text


def _make_docx(paragraphs: list[str]) -> bytes:
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_extracts_paragraph_text_joined_with_blank_lines():
    docx_bytes = _make_docx(["Jane Doe", "Senior Backend Engineer"])

    text = extract_docx_text(docx_bytes)

    assert text == "Jane Doe\n\nSenior Backend Engineer"


def test_skips_empty_paragraphs():
    docx_bytes = _make_docx(["Jane Doe", "", "   ", "Senior Backend Engineer"])

    text = extract_docx_text(docx_bytes)

    assert text == "Jane Doe\n\nSenior Backend Engineer"


def test_raises_on_garbage_bytes():
    with pytest.raises(DocxExtractionError):
        extract_docx_text(b"not a docx file")


def test_raises_on_a_zip_that_is_not_a_docx_package():
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("hello.txt", "not a docx")

    with pytest.raises(DocxExtractionError):
        extract_docx_text(buffer.getvalue())
