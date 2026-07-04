"""
Gemini vision agent that labels the semantic role (summary, skills,
work_experience_entry, ...) of each block on one PDF page.

Coordinate extraction (pdf_layout_extractor.py) can locate text but has no
way to know what it *means* — that's a visual/semantic judgment (heading
styling, column layout, spacing) that only a vision-capable model can make
cheaply. One call per page: a rendered page image, plus that page's already-
extracted blocks as grounding JSON, so the model labels blocks it can already
see the exact text of instead of re-reading (and risking transcribing) text
from the image itself.
"""

import json
import logging
import os
from pathlib import Path

import fitz
from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.resume_layout import LayoutSection, PageLabelingResult, ResumeLayoutDocument, TextBlock
from services.llm_output import LLMOutputError, parse_llm_json

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)


_SYSTEM_PROMPT = """You are labeling the sections of one resume page.

You are given the page as an image, and the exact text already extracted
from it as a list of blocks (block_id + text). Group these block ids into
sections and assign each section a role.

Rules:
- Every block_id given to you must appear in exactly one section.
- Do not invent block ids, and do not change block text.
- Preserve the top-to-bottom reading order of the page within each section.

Roles: header_contact, summary, skills, work_experience_entry,
education_entry, project_entry, certifications, other.

Schema:
{
  "sections": [
    {"role": string, "block_ids": [string]}
  ]
}"""


class GeminiVisionLayoutAgent:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def label_page(self, page_image: bytes, blocks: list[TextBlock]) -> dict:
        response = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                types.Part.from_bytes(data=page_image, mime_type="image/png"),
                self._build_grounding(blocks),
            ],
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return parse_llm_json(response.text, PageLabelingResult)

    async def label_document(self, pdf_bytes: bytes, layout: ResumeLayoutDocument) -> ResumeLayoutDocument:
        """
        Replaces pdf_layout_extractor.py's single unlabeled section per page
        with role-labeled section groupings, one label_page() call per page.

        A page whose response is missing or fails to validate keeps its
        original (unlabeled) section rather than losing that page's content —
        role labels are an enhancement on top of the deterministic extraction,
        not a requirement for it to be usable.
        """
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        try:
            labeled_sections: list[LayoutSection] = []
            for section in layout.sections:
                page_number = _page_number_of(section)
                if page_number is None:
                    labeled_sections.append(section)
                    continue

                page_image = document[page_number].get_pixmap().tobytes("png")
                try:
                    result = await self.label_page(page_image, section.blocks)
                    labeled_sections.extend(_apply_labels(section, result))
                except LLMOutputError:
                    logger.warning("Vision labeling response invalid for page %d — keeping it unlabeled", page_number)
                    labeled_sections.append(section)
        finally:
            document.close()

        return layout.model_copy(update={"sections": labeled_sections})

    def _build_grounding(self, blocks: list[TextBlock]) -> str:
        grounding = [{"block_id": block.block_id, "text": block.text} for block in blocks]
        return json.dumps(grounding)


def _page_number_of(section: LayoutSection) -> int | None:
    for block in section.blocks:
        if block.pdf_anchor is not None:
            return block.pdf_anchor.page_number
    return None


def _apply_labels(section: LayoutSection, result: dict) -> list[LayoutSection]:
    """Repartitions one page's flat block list into labeled sections per the
    model's groupings. Any block_id the model didn't mention (or invented)
    is handled fail-safe: real blocks it missed are kept in a trailing
    unlabeled section instead of silently dropped."""
    blocks_by_id = {block.block_id: block for block in section.blocks}
    covered: set[str] = set()
    labeled: list[LayoutSection] = []

    for index, labeled_section in enumerate(result["sections"]):
        blocks = [blocks_by_id[block_id] for block_id in labeled_section["block_ids"] if block_id in blocks_by_id]
        covered.update(block.block_id for block in blocks)
        if blocks:
            labeled.append(LayoutSection(
                section_id=f"{section.section_id}.labeled[{index}]",
                role=labeled_section["role"],
                blocks=blocks,
            ))

    leftover = [block for block in section.blocks if block.block_id not in covered]
    if leftover:
        labeled.append(LayoutSection(section_id=f"{section.section_id}.unlabeled", blocks=leftover))

    return labeled
