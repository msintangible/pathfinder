"""
PDF Renderer — writes an already-patched ResumeLayoutDocument back into the
candidate's original PDF bytes via PyMuPDF redact-and-overlay.

Purely mechanical, mirroring docx_renderer_v2.py's boundary: no patch-
matching or text logic lives here, only "given a finalized block.text per
position, put it there." A block's real embedded font is extracted from the
source PDF itself (see _FontResolver) and reused when redrawing it, so
rewritten text keeps the candidate's actual font wherever the source PDF
embeds one; only a font the source PDF never embedded (rare — e.g. a
standard Base-14 font referenced by name only, not embedded as file data)
falls back to a PyMuPDF Base-14 substitute. That fallback is an accepted,
surfaced limitation — every substituted or overflow-truncated block is
reported back via `low_confidence_block_ids` rather than silently degrading.
Only blocks whose text actually changed pay either cost — see
_changed_block_ids — so an edit to one bullet doesn't also re-render every
untouched block on the page.

A plain white-rectangle overlay would leave the old text still extractable
underneath it, defeating ATS parseability — add_redact_annot + apply_
redactions() actually strips the old glyphs before the new text is drawn.
"""

import logging
import os
import tempfile
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

# Once a block can't be shrunk any further, its box grows downward — one
# minimum-size line at a time, since insert_textbox only ever needs whole
# extra lines, not fractional height — pushing every block below it down the
# same page by the same amount, rather than truncating immediately.
_GROWTH_STEP = _MIN_FONT_SIZE * _LINE_HEIGHT_FACTOR
# Growth never crosses into this margin at the bottom of the page, so pushed
# content can never render outside the printable area.
_BOTTOM_MARGIN = 36.0


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

    all_blocks_by_page: dict[int, list[TextBlock]] = {}
    for section in layout.sections:
        for block in section.blocks:
            if block.pdf_anchor is not None:
                all_blocks_by_page.setdefault(block.pdf_anchor.page_number, []).append(block)

    document = fitz.open(stream=original_bytes, filetype="pdf")
    resolver = _FontResolver(document)
    try:
        low_confidence: list[str] = []
        for page_number, page_blocks in all_blocks_by_page.items():
            if not any(block.block_id in changed_block_ids for block in page_blocks):
                continue  # nothing on this page changed — leave it untouched entirely

            page = document[page_number]
            # Read each block's real embedded font before apply_redactions()
            # touches the page, so extraction never has to guess whether
            # redaction affected font resources.
            resolver.prime(page)
            low_confidence.extend(_render_page(page, page_blocks, changed_block_ids, resolver))

        pdf_bytes = document.tobytes()
    finally:
        resolver.cleanup()
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


@dataclass
class _BlockRenderPlan:
    block_id: str
    original_rect: fitz.Rect
    final_rect: fitz.Rect
    text: str
    fontname: str
    fontfile: str | None
    fontsize: float
    low_confidence: bool
    truncated: bool


def _render_page(
    page: fitz.Page, blocks: list[TextBlock], changed_block_ids: set[str], resolver: "_FontResolver"
) -> list[str]:
    """
    Renders every changed block on one page, top to bottom. A block that
    can't be shrunk to fit its original box grows downward instead of
    truncating immediately, pushing every block below it down the page by
    the same amount — including blocks whose own text never changed, since
    moving anything means erasing where it used to be and redrawing it. That
    reflow only ever happens on a page _page_is_single_column confirms is
    safe to shift vertically; on any other page, growth is capped at each
    block's own original height, which collapses this to today's
    shrink-then-truncate behavior — an unchanged block is still never
    touched at all in that case, since offset never moves off zero.
    """
    single_column = _page_is_single_column(blocks)
    page_bottom_limit = page.rect.height - _BOTTOM_MARGIN

    plans: list[_BlockRenderPlan] = []
    offset = 0.0
    for block in sorted(blocks, key=lambda b: b.pdf_anchor.y0):
        anchor = block.pdf_anchor
        original_rect = fitz.Rect(anchor.x0, anchor.y0, anchor.x1, anchor.y1)
        is_changed = block.block_id in changed_block_ids

        if not is_changed and offset == 0.0:
            continue  # never touched — keeps its real original font/position untouched

        rect = fitz.Rect(original_rect.x0, original_rect.y0 + offset, original_rect.x1, original_rect.y1 + offset)
        fontname, fontfile, font_substituted = resolver.resolve(anchor.font_name)

        # Every drawn block goes through the same fit check, changed or not:
        # insert_textbox's own internal margin requirements mean even a
        # block's *unmodified* text at its *original* size can fail to fit
        # a box sized by its own tight original glyph extents (zero slack
        # to begin with) — a moved-but-unchanged block needs this same
        # shrink/grow safety net, not just a bare, unverified redraw.
        max_y1 = max(page_bottom_limit, rect.y1) if single_column else rect.y1
        text, fontsize, final_rect, truncated = _fit_text(
            block.text, fontname, fontfile, anchor.font_size or 11.0, rect, max_y1
        )

        plans.append(_BlockRenderPlan(
            block_id=block.block_id, original_rect=original_rect, final_rect=final_rect, text=text,
            fontname=fontname, fontfile=fontfile, fontsize=fontsize,
            low_confidence=font_substituted or truncated, truncated=truncated,
        ))
        offset += max(0.0, final_rect.height - original_rect.height)

    for plan in plans:
        page.add_redact_annot((plan.original_rect.x0, plan.original_rect.y0,
                                plan.original_rect.x1, plan.original_rect.y1), fill=(1, 1, 1))
    if plans:
        page.apply_redactions()

    low_confidence_ids = []
    for plan in plans:
        page.insert_textbox(plan.final_rect, plan.text, fontname=plan.fontname, fontfile=plan.fontfile,
                             fontsize=plan.fontsize, lineheight=_LINE_HEIGHT_FACTOR)
        if plan.truncated:
            logger.warning("Truncated block %s to fit its original width/height", plan.block_id)
        if plan.low_confidence:
            low_confidence_ids.append(plan.block_id)
    return low_confidence_ids


def _page_is_single_column(blocks: list[TextBlock]) -> bool:
    """
    A page is safe to reflow vertically only if it has no side-by-side
    content — two blocks whose vertical ranges substantially overlap but
    whose horizontal ranges don't (a sidebar, or a two-column layout) would
    get shifted incorrectly by a uniform vertical push, since content to the
    side of a growing block has no reason to move at all. Same-line pairs
    like a job title on the left and its dates on the right share one y0/y1
    per block already (pdf_layout_extractor.py groups a whole line into one
    block), so they aren't flagged by this check — only genuinely separate
    columns are.
    """
    anchors = [block.pdf_anchor for block in blocks]
    for i, a in enumerate(anchors):
        for b in anchors[i + 1:]:
            shorter_height = min(a.y1 - a.y0, b.y1 - b.y0)
            if shorter_height <= 0:
                continue
            y_overlap = min(a.y1, b.y1) - max(a.y0, b.y0)
            if y_overlap > 0.5 * shorter_height:
                x_overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
                if x_overlap <= 0:
                    return False
    return True


class _FontResolver:
    """
    Resolves a block's real embedded font from the source PDF (extracted and
    written to a temp file once per unique font per render, then reused) so
    rewritten text keeps the candidate's actual font wherever the source PDF
    embeds one. Falls back to a Base-14 substitute only when the source PDF
    genuinely has no embedded font data for that name (e.g. a standard font
    referenced by name only) — never a hard failure.
    """

    def __init__(self, document: fitz.Document) -> None:
        self._document = document
        self._font_index: dict[str, int] = {}
        self._font_files: dict[int, str] = {}

    def prime(self, page: fitz.Page) -> None:
        """Builds this page's font-name -> xref index. Must run before
        apply_redactions() touches the page."""
        self._font_index = {}
        for xref, ext, _subtype, basefont, *_rest in page.get_fonts(full=True):
            if ext == "n/a":
                continue  # no embedded font file for this entry — nothing to extract
            clean = basefont.split("+", 1)[1] if "+" in basefont else basefont
            self._font_index[clean] = xref

    def resolve(self, font_name: str | None) -> tuple[str, str | None, bool]:
        """Returns (fontname, fontfile_path_or_None, was_substituted)."""
        resolved = self._resolve_embedded(font_name)
        if resolved is not None:
            xref, path = resolved
            return f"embedded{xref}", path, False
        fallback, substituted = _resolve_base14_font(font_name)
        return fallback, None, substituted

    def cleanup(self) -> None:
        for path in self._font_files.values():
            try:
                os.remove(path)
            except OSError:
                pass
        self._font_files = {}

    def _resolve_embedded(self, font_name: str | None) -> tuple[int, str] | None:
        if not font_name:
            return None
        xref = self._font_index.get(font_name)
        if xref is None:
            # PyMuPDF truncates a span's font name to a fixed buffer length,
            # so an exact match can miss even though the real (untruncated)
            # font name is right there in the page's own font index.
            for indexed_name, candidate_xref in self._font_index.items():
                if indexed_name.startswith(font_name):
                    xref = candidate_xref
                    break
        if xref is None:
            return None
        if xref not in self._font_files:
            try:
                _name, ext, _subtype, buffer = self._document.extract_font(xref)
            except Exception:
                return None
            if not buffer:
                return None
            fd, path = tempfile.mkstemp(suffix="." + ext)
            with os.fdopen(fd, "wb") as f:
                f.write(buffer)
            self._font_files[xref] = path
        return xref, self._font_files[xref]


def _resolve_base14_font(font_name: str | None) -> tuple[str, bool]:
    """Returns (fontname, was_substituted). A source font counts as
    substituted unless it's literally one of PyMuPDF's own Base-14 codes —
    which extracted PDF font names (e.g. "ABCDEF+Calibri") never are, so
    this realistically flags every block that reaches this fallback."""
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


def _fits(text: str, fontname: str, fontfile: str | None, fontsize: float, rect: fitz.Rect) -> bool:
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
        rc = page.insert_textbox(rect, text, fontname=fontname, fontfile=fontfile, fontsize=fontsize,
                                  lineheight=_LINE_HEIGHT_FACTOR)
        return rc >= 0
    finally:
        scratch.close()


def _fit_text(
    text: str, fontname: str, fontfile: str | None, fontsize: float, rect: fitz.Rect, max_y1: float
) -> tuple[str, float, fitz.Rect, bool]:
    """
    Shrink font size until text fits rect; if even _MIN_FONT_SIZE doesn't
    fit, grow rect downward one line at a time (capped at max_y1) before
    truncating as a genuinely last resort. Returns (text, fontsize,
    final_rect, truncated). Callers that can't safely grow (see
    _page_is_single_column) pass max_y1 == rect.y1, which skips the growth
    loop entirely and falls straight to today's truncate-at-original-size
    behavior.
    """
    size = fontsize
    while size >= _MIN_FONT_SIZE:
        if _fits(text, fontname, fontfile, size, rect):
            return text, size, rect, False
        size -= _SHRINK_STEP

    grown_rect = fitz.Rect(rect)
    while grown_rect.y1 < max_y1:
        grown_rect.y1 = min(grown_rect.y1 + _GROWTH_STEP, max_y1)
        if _fits(text, fontname, fontfile, _MIN_FONT_SIZE, grown_rect):
            return text, _MIN_FONT_SIZE, grown_rect, False

    truncated = _truncate_to_fit(text, fontname, fontfile, _MIN_FONT_SIZE, grown_rect)
    return truncated, _MIN_FONT_SIZE, grown_rect, True


def _truncate_to_fit(text: str, fontname: str, fontfile: str | None, fontsize: float, rect: fitz.Rect) -> str:
    words = text.split()
    while words:
        candidate = " ".join(words) + _ELLIPSIS
        if _fits(candidate, fontname, fontfile, fontsize, rect):
            return candidate
        words = words[:-1]
    return _ELLIPSIS
