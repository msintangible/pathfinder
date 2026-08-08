"""
Schemas for the Resume Layout Model.

Structure, style, and content are kept separate: TextBlock.text is the only
field an editing LLM should ever read or write. anchor/runs (docx_anchor,
pdf_anchor, RunSpan.hyperlink_url) were designed for real-document parsing
and in-place editing, which was removed (see the 2026-08 dead-code cleanup)
— synthetic_profile_layout.py is the only builder of this shape now, and
always leaves those fields at their defaults. Kept as-is pending a follow-up
simplification pass.
"""

from enum import Enum

from pydantic import BaseModel


class SectionRole(str, Enum):
    HEADER_CONTACT = "header_contact"
    SUMMARY = "summary"
    SKILLS = "skills"
    WORK_EXPERIENCE_ENTRY = "work_experience_entry"
    EDUCATION_ENTRY = "education_entry"
    PROJECT_ENTRY = "project_entry"
    CERTIFICATIONS = "certifications"
    OTHER = "other"


class RunSpan(BaseModel):
    """One style-carrying sub-span of a TextBlock's text, in document order."""
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    font_name: str | None = None
    font_size: float | None = None
    # Set when this run is wrapped in a w:hyperlink element (docx only).
    # python-docx's paragraph.runs silently excludes hyperlink-wrapped runs,
    # so docx_layout_extractor.iter_run_targets() walks paragraph content
    # directly instead — see that function's docstring. patch_engine.py pins
    # any run with a hyperlink_url to its original text rather than rewriting
    # it, since python-docx can't recreate a w:hyperlink relationship here.
    hyperlink_url: str | None = None


class DocxAnchor(BaseModel):
    """
    Positional identity of a TextBlock within a python-docx Document.

    Exactly one of paragraph_index or the table_index/row_index/col_index
    trio is set, depending on whether the block came from a body paragraph
    or a table cell.
    """
    paragraph_index: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    col_index: int | None = None
    cell_paragraph_index: int | None = None
    style_name: str | None = None


class PdfAnchor(BaseModel):
    """Positional identity of a TextBlock within a PDF page (populated by the
    PDF layout extractor; unused for DOCX documents)."""
    page_number: int
    x0: float
    y0: float
    x1: float
    y1: float
    font_name: str | None = None
    font_size: float | None = None


class TextBlock(BaseModel):
    block_id: str
    kind: str  # "paragraph" | "bullet" | "table_cell"
    text: str
    runs: list[RunSpan] = []
    docx_anchor: DocxAnchor | None = None
    pdf_anchor: PdfAnchor | None = None


class LayoutSection(BaseModel):
    section_id: str
    role: SectionRole = SectionRole.OTHER
    blocks: list[TextBlock] = []


class ResumeLayoutDocument(BaseModel):
    source_format: str  # "docx" | "pdf"
    sections: list[LayoutSection] = []


class ContentPatch(BaseModel):
    """One wording change from the optimization LLM. This is the *only*
    channel the LLM has to affect a document — see patch_engine.py, which is
    the sole component permitted to turn these into updated TextBlock runs."""
    block_id: str
    new_text: str
