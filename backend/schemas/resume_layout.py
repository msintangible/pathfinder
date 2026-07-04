"""
Schemas for the Resume Layout Model.

Structure, style, and content are kept separate: TextBlock.text is the only
field an editing LLM should ever read or write. Renderers use anchor + runs
to know where and how to write a change back into the original file. See
docx_layout_extractor.py for how DOCX documents are parsed into this shape.
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


class PageSectionLabel(BaseModel):
    """One semantic grouping of blocks on a page, as labeled by
    gemini_vision_layout_agent.py — every block_id on the page must appear in
    exactly one label."""
    role: SectionRole
    block_ids: list[str]


class PageLabelingResult(BaseModel):
    sections: list[PageSectionLabel]


class ContentPatch(BaseModel):
    """One wording change from the optimization LLM. This is the *only*
    channel the LLM has to affect a document — see patch_engine.py, which is
    the sole component permitted to turn these into updated TextBlock runs."""
    block_id: str
    new_text: str
