"""
Infers the candidate's original section order from profile.layout_document,
so the generic Jinja2 fallback template (resume_renderer.py / resume.html)
at least preserves the candidate's own section ordering even when
profile_layout_correlator.py's confidence gate rejects real in-place editing
(or there's no source document to correlate against at all). The fallback
still can't reproduce the original fonts/spacing — that's the in-place
renderers' job — but section order is a structural signal parsing already
gives us for free, so there's no reason the fallback should ignore it.
"""

import logging

from pydantic import ValidationError

from schemas.resume_layout import LayoutSection, ResumeLayoutDocument, SectionRole
from services.profile_layout_correlator import is_heading_block

logger = logging.getLogger(__name__)

# resume.html renders these sections — order here is the fallback
# used for a section role/heading resume_section_order.py can't confidently
# classify, and for any section this document simply lacks a heading for.
DEFAULT_SECTION_ORDER = [
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "certifications",
    "awards",
    "leadership",
    "volunteering",
    "publications",
    "interests",
    "references",
]

_SECTION_KEYWORDS = {
    "summary": ("summary", "profile", "objective"),
    "skills": ("skill", "technical", "technolog", "tools"),
    "experience": ("experience", "employment", "work history"),
    "projects": ("project",),
    "education": ("education", "university", "degree"),
    "certifications": ("certification", "certificate", "credential"),
    "awards": ("award", "achievement", "honor", "honour"),
    "leadership": ("leadership",),
    "volunteering": ("volunteer", "volunteering"),
    "publications": ("publication", "research"),
    "interests": ("interest",),
    "references": ("reference",),
}

_ROLE_TO_SECTION = {
    SectionRole.SUMMARY: "summary",
    SectionRole.SKILLS: "skills",
    SectionRole.WORK_EXPERIENCE_ENTRY: "experience",
    SectionRole.PROJECT_ENTRY: "projects",
}


def infer_section_order(layout_document: dict | None) -> list[str]:
    if not layout_document:
        logger.debug("section_order: no layout_document — using default order")
        return list(DEFAULT_SECTION_ORDER)

    try:
        layout = ResumeLayoutDocument.model_validate(layout_document)
    except ValidationError:
        logger.warning("section_order: layout_document failed to validate — using default order", exc_info=True)
        return list(DEFAULT_SECTION_ORDER)

    order: list[str] = []
    for section in layout.sections:
        kind = _classify_section(section)
        if kind is not None and kind not in order:
            order.append(kind)

    for kind in DEFAULT_SECTION_ORDER:
        if kind not in order:
            order.append(kind)

    logger.debug("section_order: inferred %s from layout_document", order)
    return order


def _classify_section(section: LayoutSection) -> str | None:
    mapped_role = _ROLE_TO_SECTION.get(section.role)
    if mapped_role is not None:
        return mapped_role

    heading = section.blocks[0] if section.blocks else None
    if heading is None or not is_heading_block(heading):
        return None

    lowered = heading.text.lower()
    for kind, keywords in _SECTION_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return kind
    return None
