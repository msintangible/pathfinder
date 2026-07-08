import fitz
import pytest

from schemas.resume_layout import LayoutSection, PdfAnchor, ResumeLayoutDocument, RunSpan, TextBlock
from services.pdf_layout_extractor import extract_pdf_layout
from services.pdf_renderer_v2 import PdfRenderError, render_pdf


def _make_pdf(lines: list[str]) -> bytes:
    document = fitz.open()
    page = document.new_page()
    for index, text in enumerate(lines):
        page.insert_text((72, 100 + index * 20), text, fontsize=11)
    buffer = document.tobytes()
    document.close()
    return buffer


def _blank_pdf() -> bytes:
    document = fitz.open()
    document.new_page()
    buffer = document.tobytes()
    document.close()
    return buffer


def _pdf_layout(block_id: str, text: str, x0: float, y0: float, x1: float, y1: float,
                font_name: str = "Helvetica", font_size: float = 11.0) -> ResumeLayoutDocument:
    anchor = PdfAnchor(page_number=0, x0=x0, y0=y0, x1=x1, y1=y1, font_name=font_name, font_size=font_size)
    block = TextBlock(block_id=block_id, kind="paragraph", text=text, runs=[RunSpan(text=text)], pdf_anchor=anchor)
    return ResumeLayoutDocument(source_format="pdf", sections=[LayoutSection(section_id="s0", blocks=[block])])


def _first_span(pdf_bytes: bytes) -> dict:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    span = document[0].get_text("dict")["blocks"][0]["lines"][0]["spans"][0]
    document.close()
    return span


def test_rejects_non_pdf_layout():
    layout = ResumeLayoutDocument(source_format="docx", sections=[])
    with pytest.raises(PdfRenderError):
        render_pdf(_blank_pdf(), layout)


def test_replaces_text_and_old_text_is_not_extractable_afterward():
    source_bytes = _make_pdf(["Old text here."])
    layout = extract_pdf_layout(source_bytes)
    layout.sections[0].blocks[0].text = "New text here."

    result = render_pdf(source_bytes, layout)

    rendered = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    page_text = rendered[0].get_text()
    rendered.close()

    assert "New text here." in page_text
    assert "Old text here." not in page_text


def test_unmodified_block_text_is_still_present_after_render():
    source_bytes = _make_pdf(["Jane Doe", "Senior Engineer"])
    layout = extract_pdf_layout(source_bytes)

    result = render_pdf(source_bytes, layout)

    rendered = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    page_text = rendered[0].get_text()
    rendered.close()

    assert "Jane Doe" in page_text
    assert "Senior Engineer" in page_text


def test_font_substitution_is_flagged_low_confidence():
    # Real PDFs carry embedded/subsetted font names (e.g. "ABCDEF+Calibri"),
    # never PyMuPDF's own "helv"/"cour"/"tiro" shorthand, so any block that's
    # actually rewritten hits this, not as an edge case.
    source_bytes = _make_pdf(["Some text."])
    layout = extract_pdf_layout(source_bytes)
    block_id = layout.sections[0].blocks[0].block_id
    layout.sections[0].blocks[0].text = "Some rewritten text."

    result = render_pdf(source_bytes, layout)

    assert block_id in result.low_confidence_block_ids


def test_unchanged_block_is_skipped_entirely_keeping_its_original_font():
    # Phase D: a block whose text didn't change must never be redacted or
    # redrawn at all, so it keeps its real original font instead of being
    # silently swapped to a Base-14 substitute along with the edited blocks.
    source_bytes = _make_pdf(["Jane Doe", "Senior Engineer"])
    layout = extract_pdf_layout(source_bytes)
    layout.sections[0].blocks[0].text = "Rewritten Name"
    # blocks[1] ("Senior Engineer") is left untouched.

    result = render_pdf(source_bytes, layout)

    unchanged_block_id = layout.sections[0].blocks[1].block_id
    assert unchanged_block_id not in result.low_confidence_block_ids


def test_shrinks_font_to_fit_when_text_is_too_wide_at_original_size():
    text = "This line needs a smaller font to fit."
    original_size = 14.0
    full_width = fitz.get_text_length(text, fontname="helv", fontsize=original_size)
    narrow_width = full_width * 0.6  # too narrow at 14pt, but fits comfortably once shrunk

    layout = _pdf_layout("page[0].block[0].line[0]", text, x0=72, y0=100, x1=72 + narrow_width, y1=114,
                          font_size=original_size)

    result = render_pdf(_blank_pdf(), layout)
    span = _first_span(result.pdf_bytes)

    assert span["text"] == text  # fits without truncation
    assert span["size"] < original_size  # had to shrink to get there


def test_truncates_with_ellipsis_when_even_min_font_size_does_not_fit():
    text = "This sentence is far too long to ever fit in a tiny box no matter the font size."
    layout = _pdf_layout("page[0].block[0].line[0]", text, x0=72, y0=100, x1=92, y1=114)  # 20pt wide

    result = render_pdf(_blank_pdf(), layout)
    span = _first_span(result.pdf_bytes)

    assert span["text"] != text
    assert span["text"].endswith("...")
    assert result.low_confidence_block_ids == ["page[0].block[0].line[0]"]


def test_wrapped_bullet_rewrite_replaces_all_original_lines_not_just_one():
    # A bullet that wraps across 3 lines in the original document — the bug
    # this guards against: the old per-line extraction could only ever place
    # a full rewritten sentence on ONE of those lines, leaving the other
    # lines' original wording sitting untouched right next to it.
    original = "Developed and deployed new ASP.NET backend and React TypeScript frontend features using Redux."
    document = fitz.open()
    page = document.new_page()
    rect = fitz.Rect(72, 100, 72 + 195, 200)
    page.insert_textbox(rect, original, fontsize=11)
    source_bytes = document.tobytes()
    document.close()

    layout = extract_pdf_layout(source_bytes)
    assert len(layout.sections[0].blocks) == 1  # confirms this is exercising the one-block-per-bullet path
    layout.sections[0].blocks[0].text = "Built RESTful APIs using ASP.NET and React, deployed with Redux state management."

    result = render_pdf(source_bytes, layout)
    rendered = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    page_text = " ".join(rendered[0].get_text().split())  # normalize the wrapped-line newlines
    rendered.close()

    assert "Built RESTful APIs using ASP.NET and React, deployed with Redux state management." in page_text
    # None of the original sentence's distinctive words survive anywhere on
    # the page — if they did, that's the old bug: a stale, un-rewritten line
    # sitting next to the new text.
    assert "new ASP.NET backend" not in page_text
    assert "frontend features using Redux" not in page_text


def test_text_that_fits_at_original_size_is_not_shrunk_or_truncated():
    text = "Short."
    # y1-y0=20 gives an 11pt line its real vertical room — insert_textbox's
    # own line-height needs more than a bare 11pt-tall box (see _fits).
    layout = _pdf_layout("page[0].block[0].line[0]", text, x0=72, y0=100, x1=300, y1=120, font_size=11.0)

    result = render_pdf(_blank_pdf(), layout)
    span = _first_span(result.pdf_bytes)

    assert span["text"] == text
    assert span["size"] == pytest.approx(11.0)
