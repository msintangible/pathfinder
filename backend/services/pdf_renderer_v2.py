"""
PDF Renderer — writes an already-patched ResumeLayoutDocument back into the
candidate's original PDF bytes via PyMuPDF redact-and-overlay.

Purely mechanical, mirroring docx_renderer_v2.py's boundary: no patch-
matching or text logic lives here, only "given a finalized block.text per
position, put it there." PDF has no paragraph model to write into, so unlike
the DOCX renderer this can't preserve the original font — insert_text/
insert_textbox only support PyMuPDF's built-in Base-14 fonts, so any
embedded/subsetted font in the source PDF (the common case) is substituted,
not reproduced. That's an accepted, surfaced limitation (see the structure-
preserving resume plan) — every substituted or overflow-truncated block is
reported back via `low_confidence_block_ids` rather than silently degrading.
Only blocks whose text actually changed pay this cost — see
_changed_block_ids — so an edit to one bullet doesn't also re-render every
untouched block on the page in a different font.

A plain white-rectangle overlay would leave the old text still extractable
underneath it, defeating ATS parseability — add_redact_annot + apply_
redactions() actually strips the old glyphs before the new text is drawn.
"""

import logging
from dataclasses import dataclass, field

import fitz

from schemas.resume_layout import ResumeLayoutDocument, TextBlock
from services.pdf_layout_extractor import extract_pdf_layout

logger = logging.getLogger(__name__)

# PyMuPDF's shorthand codes for the 14 fonts insert_text can draw without an
# embedded font file.
_BASE14_FONTS = {"helv", "heit", "hebo", "hebi", "cour", "coit", "cobo", "cobi", "tiro", "tiit", "tibo", "tibi"}
_FONT_SUBSTITUTES = {
    "helvetica": "helv", "arial": "helv",
    "times": "tiro", "timesnewroman": "tiro",
    "courier": "cour", "couriernew": "cour",
}
_DEFAULT_FONT = "helv"

_MIN_FONT_SIZE = 6.0
_SHRINK_STEP = 0.5
# Base-14 fonts only support Latin-1/WinAnsi encoding through insert_text's
# default encoding — the Unicode ellipsis character (U+2026) isn't in that
# range and silently corrupts on insert, so this uses the plain ASCII form.
_ELLIPSIS = "..."
# Passed explicitly to both our own wrap-height math and insert_textbox's
# lineheight= argument, so the two agree on how tall a wrapped line is —
# leaving it to each side's own default would let them silently drift apart.
_LINE_HEIGHT_FACTOR = 1.15


class PdfRenderError(Exception):
    pass


@dataclass
class PdfRenderResult:
    pdf_bytes: bytes
    low_confidence_block_ids: list[str] = field(default_factory=list)


def render_pdf(original_bytes: bytes, layout: ResumeLayoutDocument) -> PdfRenderResult:
    if layout.source_format != "pdf":
        raise PdfRenderError(f"Expected a pdf-sourced layout, got source_format={layout.source_format!r}")

    changed_block_ids = _changed_block_ids(original_bytes, layout)

    document = fitz.open(stream=original_bytes, filetype="pdf")
    try:
        blocks_by_page: dict[int, list[TextBlock]] = {}
        for section in layout.sections:
            for block in section.blocks:
                if block.pdf_anchor is not None and block.block_id in changed_block_ids:
                    blocks_by_page.setdefault(block.pdf_anchor.page_number, []).append(block)

        low_confidence: list[str] = []
        for page_number, blocks in blocks_by_page.items():
            page = document[page_number]
            for block in blocks:
                anchor = block.pdf_anchor
                page.add_redact_annot((anchor.x0, anchor.y0, anchor.x1, anchor.y1), fill=(1, 1, 1))
            page.apply_redactions()

            for block in blocks:
                if _write_block(page, block):
                    low_confidence.append(block.block_id)

        pdf_bytes = document.tobytes()
    finally:
        document.close()

    return PdfRenderResult(pdf_bytes=pdf_bytes, low_confidence_block_ids=low_confidence)


def _changed_block_ids(original_bytes: bytes, layout: ResumeLayoutDocument) -> set[str]:
    """
    block_ids whose text differs from what's actually in original_bytes at
    that position. Re-extracting original_bytes (rather than trusting the
    caller's own pre-patch copy) keeps this self-contained and always
    correct relative to the file being rendered into — a block skipped here
    never touches add_redact_annot/insert_textbox at all, so its original
    font, size, and position are untouched by the Base-14 substitution the
    rest of this module accepts as a known limitation.
    """
    original_layout = extract_pdf_layout(original_bytes)
    original_text_by_id = {
        block.block_id: block.text for section in original_layout.sections for block in section.blocks
    }
    return {
        block.block_id
        for section in layout.sections
        for block in section.blocks
        if block.pdf_anchor is not None and block.text != original_text_by_id.get(block.block_id)
    }


def _write_block(page: fitz.Page, block: TextBlock) -> bool:
    """
    Draws block.text into its full original rect (which may span several
    original lines — see pdf_layout_extractor.py's per-paragraph grouping)
    via insert_textbox, which wraps automatically, instead of insert_text at
    a single point. A block that used to be one wrapped bullet spanning
    multiple original lines now gets the whole rewritten sentence, wrapped
    across that same multi-line area, rather than the sentence only ever
    being able to land on one of those lines.
    """
    anchor = block.pdf_anchor
    fontname, font_substituted = _resolve_font(anchor.font_name)
    original_size = anchor.font_size or 11.0
    rect = fitz.Rect(anchor.x0, anchor.y0, anchor.x1, anchor.y1)

    text, fontsize, truncated = _fit_text(block.text, fontname, original_size, rect)
    page.insert_textbox(rect, text, fontname=fontname, fontsize=fontsize, lineheight=_LINE_HEIGHT_FACTOR)

    if truncated:
        logger.warning("Truncated block %s to fit its original width/height", block.block_id)
    return font_substituted or truncated


def _resolve_font(font_name: str | None) -> tuple[str, bool]:
    """Returns (fontname, was_substituted). A source font counts as
    substituted unless it's literally one of PyMuPDF's own Base-14 codes —
    which extracted PDF font names (e.g. "ABCDEF+Calibri") never are, so
    this realistically flags every block, by design."""
    if font_name:
        normalized = font_name.lower().replace("-", "").replace(" ", "")
        if "+" in normalized:
            normalized = normalized.split("+", 1)[1]
        if normalized in _BASE14_FONTS:
            return normalized, False
        for key, mapped in _FONT_SUBSTITUTES.items():
            if key in normalized:
                return mapped, True
    return _DEFAULT_FONT, True


def _fits(text: str, fontname: str, fontsize: float, rect: fitz.Rect) -> bool:
    """
    Dry-run fit check on a throwaway page — insert_textbox is the ground
    truth for whether text wraps within rect at this size (its line-height/
    margin math isn't worth reverse-engineering, and a hand-rolled estimate
    that's even slightly off is dangerous here: insert_textbox draws
    *nothing at all*, not a partial fit, when text doesn't fit its rect).
    Discarded immediately, so this never leaves stray content anywhere.
    """
    scratch = fitz.open()
    try:
        page = scratch.new_page()
        rc = page.insert_textbox(rect, text, fontname=fontname, fontsize=fontsize, lineheight=_LINE_HEIGHT_FACTOR)
        return rc >= 0
    finally:
        scratch.close()


def _fit_text(text: str, fontname: str, fontsize: float, rect: fitz.Rect) -> tuple[str, float, bool]:
    """Shrink font size until text fits rect; truncate only as a last resort."""
    size = fontsize
    while size >= _MIN_FONT_SIZE:
        if _fits(text, fontname, size, rect):
            return text, size, False
        size -= _SHRINK_STEP

    truncated = _truncate_to_fit(text, fontname, _MIN_FONT_SIZE, rect)
    return truncated, _MIN_FONT_SIZE, True


def _truncate_to_fit(text: str, fontname: str, fontsize: float, rect: fitz.Rect) -> str:
    words = text.split()
    while words:
        candidate = " ".join(words) + _ELLIPSIS
        if _fits(candidate, fontname, fontsize, rect):
            return candidate
        words = words[:-1]
    return _ELLIPSIS
