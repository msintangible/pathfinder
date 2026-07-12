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


def _make_two_column_pdf() -> bytes:
    """Two separate blocks with overlapping y-ranges but far apart in x — a
    side-by-side layout _page_is_single_column must flag as unsafe to
    reflow. Needs each column's text to wrap onto 2+ lines in its own
    insert_textbox region — PyMuPDF's own block segmentation merges
    same-baseline single-line text across a gap into one combined block
    otherwise, which would defeat the point of this fixture."""
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(50, 100, 250, 200), "Left column bullet text goes here for testing.", fontsize=11)
    page.insert_textbox(fitz.Rect(320, 100, 520, 200), "Right column text goes here for testing.", fontsize=11)
    buffer = document.tobytes()
    document.close()
    return buffer


def _make_pdf_with_real_embedded_font(text: str) -> bytes:
    """Unlike _make_pdf (which uses a Base-14 font referenced by name only,
    exactly like insert_text's default — never truly embedded), this embeds
    real font *file* data into the page via insert_font(fontbuffer=...), the
    same way a genuine source PDF (e.g. a LaTeX/Overleaf export) embeds its
    real fonts — so get_fonts() reports a real ext (e.g. "ttf"), not "n/a".
    Uses insert_textbox with a generous rect (not a single insert_text
    point) so a slightly longer rewrite still has real room to fit,
    isolating "was the font substituted" from "did it get truncated"."""
    document = fitz.open()
    page = document.new_page()
    font_buffer = fitz.Font(fontname="china-s").buffer
    page.insert_font(fontname="EmbeddedTestFont", fontbuffer=font_buffer)
    page.insert_textbox(fitz.Rect(72, 100, 500, 130), text, fontsize=11, fontname="EmbeddedTestFont")
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


def test_real_embedded_font_is_used_instead_of_base14_substitute():
    # When the source PDF genuinely embeds the font (e.g. a LaTeX/Overleaf
    # export), a rewritten block must use that real font instead of falling
    # back to a Base-14 substitute — so it should no longer be flagged
    # low-confidence purely for a font swap. The extracted anchor is always
    # tight around the *original* glyphs regardless of container size (see
    # pdf_layout_extractor.py), so the rewrite is kept the same length as
    # the original to isolate "was the font substituted" from "did it fit".
    source_bytes = _make_pdf_with_real_embedded_font("Some text.")
    layout = extract_pdf_layout(source_bytes)
    block_id = layout.sections[0].blocks[0].block_id
    layout.sections[0].blocks[0].text = "Some info."

    result = render_pdf(source_bytes, layout)

    assert block_id not in result.low_confidence_block_ids


def test_rewritten_text_renders_correctly_with_real_embedded_font():
    source_bytes = _make_pdf_with_real_embedded_font("Old text here.")
    layout = extract_pdf_layout(source_bytes)
    layout.sections[0].blocks[0].text = "New text here."  # same length as original, avoids fit concerns

    result = render_pdf(source_bytes, layout)

    rendered = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    page_text = rendered[0].get_text()
    rendered.close()

    assert "New text here." in page_text
    assert "Old text here." not in page_text


def test_base14_fallback_still_used_when_source_has_no_embedded_font():
    # _make_pdf uses a Base-14 font referenced by name only (get_fonts()
    # reports ext="n/a" for it) — there's genuinely nothing to extract, so
    # this must still fall back to a Base-14 substitute, not fail.
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


def test_growth_pushes_unchanged_blocks_below_it_down():
    source_bytes = _make_pdf(["Short bullet.", "Second unchanged line."])
    layout = extract_pdf_layout(source_bytes)
    first_block, second_block = layout.sections[0].blocks
    original_second_y0 = second_block.pdf_anchor.y0

    # Force growth: rewrite the first block to far more text than its tight
    # original single-line box could ever hold at any font size, so the
    # unchanged second block must be pushed down to make room.
    first_block.text = (
        "This is a much longer replacement sentence that will definitely need "
        "to wrap across several extra lines and grow well past its original "
        "single-line box."
    )

    result = render_pdf(source_bytes, layout)

    rendered_layout = extract_pdf_layout(result.pdf_bytes)
    rendered_blocks = [b for section in rendered_layout.sections for b in section.blocks]
    matches = [b for b in rendered_blocks if "Second unchanged line." in b.text]

    assert len(matches) == 1  # rendered once — not left behind at its old spot too
    assert matches[0].pdf_anchor.y0 > original_second_y0  # pushed down, not overlapped


def test_multicolumn_page_disables_growth_and_leaves_the_other_column_untouched():
    source_bytes = _make_two_column_pdf()
    layout = extract_pdf_layout(source_bytes)
    left_block = next(b for b in layout.sections[0].blocks if "Left column" in b.text)

    # Far too long for the original tight single-line box — on a single-
    # column page this would grow; here it must truncate instead, since
    # growing could shift the unrelated right-hand column incorrectly.
    left_block.text = (
        "This replacement is far too long for the original tight single-line "
        "box and would need real growth to avoid truncation."
    )

    result = render_pdf(source_bytes, layout)

    assert left_block.block_id in result.low_confidence_block_ids
    rendered = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    page_text = rendered[0].get_text()
    rendered.close()
    assert "Right column text goes here for testing." in page_text  # untouched column survives, unmoved


def test_growth_lets_narrow_block_avoid_truncation_when_room_allows():
    # 20pt wide is far too narrow at any font size, but with the whole rest
    # of the page free below it, growing downward (wrapping one or two
    # words per line) fits the full text without ever truncating. (Still
    # flagged low-confidence for the unrelated reason that _blank_pdf() has
    # no real embedded font to reuse — see test_font_substitution_is_
    # flagged_low_confidence — so this only asserts the text wasn't cut.)
    text = "This sentence is far too long to ever fit in a tiny box no matter the font size."
    layout = _pdf_layout("page[0].block[0].line[0]", text, x0=72, y0=100, x1=92, y1=114)

    result = render_pdf(_blank_pdf(), layout)

    rendered = fitz.open(stream=result.pdf_bytes, filetype="pdf")
    page_text = " ".join(rendered[0].get_text().split())
    rendered.close()
    # At 20pt wide, PyMuPDF's own wrapping can split mid-word onto separate
    # lines (inserting incidental whitespace at the break when get_text()
    # rejoins them) — comparing with whitespace stripped confirms every
    # character survived untruncated without being sensitive to exactly
    # where those wrap-induced breaks fall.
    assert "..." not in page_text
    assert text.replace(" ", "") in page_text.replace(" ", "")


def test_truncates_with_ellipsis_when_growth_is_also_exhausted():
    text = "This sentence is far too long to ever fit in a tiny box no matter the font size."
    # y1 already at/past the page's bottom growth limit, so there's no room
    # left to grow into — this must still fall back to truncation exactly
    # like before growth existed, rather than erroring or drawing nothing.
    layout = _pdf_layout("page[0].block[0].line[0]", text, x0=72, y0=796, x1=92, y1=810)

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
