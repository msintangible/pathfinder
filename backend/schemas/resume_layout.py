"""
ResumeLayoutModel — the document representation shared by both parsers
(DOCX, PDF — Phase 2) and both renderers (DOCX, PDF — Phase 5/6).

Separates a resume into the four concerns the layout-preservation plan is
built on:
    - metadata  (DocumentMetadata: source format, page count, filename)
    - structure (Section/Block tree)
    - styling   (BlockStyle, per block)
    - content   (Block.text/items)

Every block a later phase may need to target for an edit (Phase 3's
ContentPatch, Phase 4's Patch Engine) carries a stable `block_id` assigned
at parse time, so a patch can address "block_id: <id>" directly instead of
re-locating the block by fuzzy text matching — the failure mode
docx_resume_renderer.py's SequenceMatcher-based matching exists to work
around today.

This module defines the model only. Parsers, the optimizer, the patch
engine, and the renderers are wired up in later phases — nothing in the
existing pipeline (resume_generation_agent.py, resume_renderer.py,
docx_resume_renderer.py) reads or writes this yet.
"""

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class SourceFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


class BlockType(str, Enum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    BULLET_LIST = "bullet_list"
    EXPERIENCE_ENTRY = "experience_entry"
    TABLE = "table"
    IMAGE = "image"
    CONTACT_DETAILS = "contact_details"


def _new_block_id() -> str:
    return uuid.uuid4().hex


class BlockStyle(BaseModel):
    """
    Visual attributes a renderer needs to reproduce a block faithfully.
    All optional — each parser fills in only what its source format
    actually exposes (DOCX runs carry font/bold/italic directly; PDF
    extraction may only recover font size and position).
    """
    font_family: str | None = None
    font_size: float | None = None
    bold: bool = False
    italic: bool = False
    color: str | None = None
    alignment: str | None = None  # "left" | "center" | "right" | "justify"


class Block(BaseModel):
    """
    One editable unit of a resume.

    `items` holds the per-row/per-bullet text for BULLET_LIST and TABLE
    blocks (a table row is represented as a single delimited string per
    the plan's "basic" table support — no colspan/rowspan); `text` holds
    the single string for every other block type.
    """
    block_id: str = Field(default_factory=_new_block_id)
    type: BlockType
    text: str | None = None
    items: list[str] = []
    style: BlockStyle = Field(default_factory=BlockStyle)


class Section(BaseModel):
    """A named group of blocks, e.g. "Experience", "Education", "Projects"."""
    section_id: str = Field(default_factory=_new_block_id)
    title: str | None = None
    blocks: list[Block] = []


class ContactDetails(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = []


class DocumentMetadata(BaseModel):
    source_format: SourceFormat
    page_count: int | None = None
    original_filename: str | None = None


class ResumeLayoutModel(BaseModel):
    """
    The shared contract between both parsers and both renderers. Neither
    side may bypass this shape — that's what keeps PDF and DOCX
    interchangeable everywhere else in the pipeline (optimizer, patch
    engine, confidence engine).
    """
    metadata: DocumentMetadata
    header: ContactDetails = Field(default_factory=ContactDetails)
    sections: list[Section] = []

    def block_ids(self) -> set[str]:
        """All block_ids in this document. Phase 4's Patch Engine uses this to reject a patch that targets a block_id the document doesn't have."""
        return {block.block_id for section in self.sections for block in section.blocks}
