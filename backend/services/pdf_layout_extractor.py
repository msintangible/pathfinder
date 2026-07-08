"""
Builds a ResumeLayoutDocument from an uploaded PDF file.

PDF has no semantic structure — only positioned glyphs — so extraction here
is purely coordinate-based, in PyMuPDF's own reading order. Section role
labeling (SUMMARY, SKILLS, WORK_EXPERIENCE_ENTRY, etc.) requires visual/
semantic understanding that coordinates alone can't provide; that's
gemini_vision_layout_agent.py's job, not this module's. Every section
produced here is left with the default role=OTHER.

One TextBlock is built per PyMuPDF *block* (get_text("dict")'s own paragraph
grouping), not per line: a single wrapped bullet spans multiple lines but is
one logical sentence, and profile_layout_correlator.py only ever has one
whole rewritten sentence to place. Splitting per line meant that sentence
could only ever land on one of the bullet's several lines — cramming the
whole rewrite into that one line's original (narrow) width, while the
bullet's other lines kept their un-patched original text right next to it.
pdf_renderer_v2.py takes the corresponding fix on the write side (rendering
into a block's full multi-line rect via insert_textbox instead of a single
insert_text point).
"""

import fitz

from schemas.resume_layout import LayoutSection, PdfAnchor, ResumeLayoutDocument, RunSpan, TextBlock

# PyMuPDF span flags bitfield: bit 1 = italic, bit 4 = bold.
_ITALIC_FLAG = 1 << 1
_BOLD_FLAG = 1 << 4


class PdfLayoutExtractionError(Exception):
    pass


def _run_spans(spans: list[dict]) -> list[RunSpan]:
    runs = []
    for span in spans:
        text = span.get("text", "")
        if not text:
            continue
        flags = span.get("flags", 0)
        runs.append(RunSpan(
            text=text,
            bold=bool(flags & _BOLD_FLAG),
            italic=bool(flags & _ITALIC_FLAG),
            font_name=span.get("font"),
            font_size=span.get("size"),
        ))
    return runs


def _paragraph_block(page_number: int, block_index: int, block: dict) -> TextBlock | None:
    lines = block.get("lines", [])
    line_texts = ["".join(span.get("text", "") for span in line.get("spans", [])).strip() for line in lines]
    text = " ".join(t for t in line_texts if t)
    if not text:
        return None

    all_spans = [span for line in lines for span in line.get("spans", []) if span.get("text", "")]
    x0, y0, x1, y1 = block.get("bbox", (0.0, 0.0, 0.0, 0.0))
    first_span = all_spans[0] if all_spans else {}
    return TextBlock(
        block_id=f"page[{page_number}].block[{block_index}]",
        kind="paragraph",
        text=text,
        runs=_run_spans(all_spans),
        pdf_anchor=PdfAnchor(
            page_number=page_number, x0=x0, y0=y0, x1=x1, y1=y1,
            font_name=first_span.get("font"), font_size=first_span.get("size"),
        ),
    )


def extract_pdf_layout(pdf_bytes: bytes) -> ResumeLayoutDocument:
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except (fitz.FileDataError, fitz.EmptyFileError) as exc:
        raise PdfLayoutExtractionError(f"Could not read PDF: {exc}") from exc

    sections: list[LayoutSection] = []
    try:
        for page_number, page in enumerate(document):
            section = LayoutSection(section_id=f"page_section[{page_number}]")
            page_dict = page.get_text("dict")
            for block_index, block in enumerate(page_dict.get("blocks", [])):
                if block.get("type") != 0:  # skip images/non-text blocks
                    continue
                text_block = _paragraph_block(page_number, block_index, block)
                if text_block is not None:
                    section.blocks.append(text_block)
            if section.blocks:
                sections.append(section)
    finally:
        document.close()

    return ResumeLayoutDocument(source_format="pdf", sections=sections)
