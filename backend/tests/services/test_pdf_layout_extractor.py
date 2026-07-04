import fitz
import pytest

from services.pdf_layout_extractor import PdfLayoutExtractionError, extract_pdf_layout


def _make_pdf(lines_per_page: list[list[str]]) -> bytes:
    """lines_per_page: one list of lines per page, e.g. [["Jane Doe", "Engineer"]]."""
    document = fitz.open()
    for lines in lines_per_page:
        page = document.new_page()
        for index, text in enumerate(lines):
            page.insert_text((72, 100 + index * 20), text, fontsize=11)
    buffer = document.tobytes()
    document.close()
    return buffer


def _all_blocks(layout):
    return [block for section in layout.sections for block in section.blocks]


def test_source_format_is_pdf():
    source = _make_pdf([["Jane Doe"]])
    layout = extract_pdf_layout(source)
    assert layout.source_format == "pdf"


def test_extracts_one_block_per_line():
    source = _make_pdf([["First line.", "Second line."]])
    layout = extract_pdf_layout(source)
    blocks = _all_blocks(layout)
    assert [b.text for b in blocks] == ["First line.", "Second line."]


def test_blocks_are_kind_paragraph():
    source = _make_pdf([["First line."]])
    layout = extract_pdf_layout(source)
    assert _all_blocks(layout)[0].kind == "paragraph"


def test_role_defaults_to_other():
    source = _make_pdf([["First line."]])
    layout = extract_pdf_layout(source)
    assert layout.sections[0].role.value == "other"


def test_block_ids_encode_page_and_are_unique():
    source = _make_pdf([["First line.", "Second line."]])
    layout = extract_pdf_layout(source)
    blocks = _all_blocks(layout)
    assert all(b.block_id.startswith("page[0].block[") for b in blocks)
    assert len({b.block_id for b in blocks}) == len(blocks)


def test_multiple_pages_produce_one_section_each():
    source = _make_pdf([["Page one line."], ["Page two line."]])
    layout = extract_pdf_layout(source)
    assert len(layout.sections) == 2
    assert layout.sections[0].blocks[0].text == "Page one line."
    assert layout.sections[1].blocks[0].text == "Page two line."
    assert layout.sections[1].blocks[0].pdf_anchor.page_number == 1


def test_pdf_anchor_records_bbox_and_font():
    source = _make_pdf([["First line."]])
    layout = extract_pdf_layout(source)
    anchor = _all_blocks(layout)[0].pdf_anchor
    assert anchor.page_number == 0
    assert anchor.font_name == "Helvetica"
    assert anchor.font_size == pytest.approx(11.0)
    assert anchor.x1 > anchor.x0
    assert anchor.y1 > anchor.y0


def test_captures_run_text():
    source = _make_pdf([["Built scalable APIs."]])
    layout = extract_pdf_layout(source)
    runs = _all_blocks(layout)[0].runs
    assert len(runs) == 1
    assert runs[0].text == "Built scalable APIs."
    assert runs[0].font_name == "Helvetica"


def test_blank_page_produces_no_section():
    document = fitz.open()
    document.new_page()
    source = document.tobytes()
    document.close()

    layout = extract_pdf_layout(source)

    assert layout.sections == []


def test_invalid_pdf_bytes_raise_extraction_error():
    with pytest.raises(PdfLayoutExtractionError):
        extract_pdf_layout(b"not a pdf")
