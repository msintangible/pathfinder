"""
Builds a ResumeLayoutDocument from an uploaded PDF file.

PDF has no semantic structure — only positioned glyphs — so extraction here
is purely coordinate-based (line-level spans, in PyMuPDF's own reading
order). Section role labeling (SUMMARY, SKILLS, WORK_EXPERIENCE_ENTRY, etc.)
requires visual/semantic understanding that coordinates alone can't provide;
that's gemini_vision_layout_agent.py's job, not this module's. Every section
produced here is left with the default role=OTHER.
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


def _line_block(page_number: int, block_index: int, line_index: int, line: dict) -> TextBlock | None:
    spans = line.get("spans", [])
    text = "".join(span.get("text", "") for span in spans).strip()
    if not text:
        return None

    x0, y0, x1, y1 = line.get("bbox", (0.0, 0.0, 0.0, 0.0))
    first_span = spans[0] if spans else {}
    return TextBlock(
        block_id=f"page[{page_number}].block[{block_index}].line[{line_index}]",
        kind="paragraph",
        text=text,
        runs=_run_spans(spans),
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
                for line_index, line in enumerate(block.get("lines", [])):
                    text_block = _line_block(page_number, block_index, line_index, line)
                    if text_block is not None:
                        section.blocks.append(text_block)
            if section.blocks:
                sections.append(section)
    finally:
        document.close()

    return ResumeLayoutDocument(source_format="pdf", sections=sections)
