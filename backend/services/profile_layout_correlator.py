"""
Correlates CandidateProfile fields (as keyed by synthetic_profile_layout.py's
profile-relative block ids) to the real block ids of the document the
profile was imported from (profile.layout_document — see
docx_layout_extractor.py / pdf_layout_extractor.py), so
ResumeGenerationAgent's synthetic-id patches can be re-applied to the real
document instead of only ever producing the `optimized_resume` dict used for
the API/DB/UI.

Both sides are matched by TEXT, not any existing shared id — CandidateProfileAgent
extracted each profile field from the very document docx/pdf_layout_extractor
parses, so this is matching text against itself (pre-ranking, pre-optimization),
not matching against LLM-tailored text the way the old docx_resume_renderer.py's
fuzzy search did. That's what makes a real match failure rare enough to gate on,
rather than a routine occurrence.
"""

import logging
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from schemas.resume_layout import LayoutSection, ResumeLayoutDocument, SectionRole, TextBlock

logger = logging.getLogger(__name__)

# Below this similarity, a profile field is treated as having no reliable
# real-document counterpart and is left uncorrelated rather than risking a
# wrong match — see CorrelationResult.match_rate for the overall confidence
# gate this feeds into.
#
# 0.55, not something stricter: CandidateProfileAgent extracts profile fields
# via an LLM, which realistically cleans up/rewords bullets even under a
# "don't invent" instruction (fixing tense, spelling out numbers, swapping
# synonyms) — it was never instructed to copy verbatim. Measured directly:
# a real, mildly-reworded bullet pair ("2M+ transactions per day" vs.
# "2 million transactions daily", same fact, same length) scores 0.667 on
# difflib.SequenceMatcher — comfortably above 0.55, while genuinely unrelated
# bullets in the same test scored 0.20-0.33. 0.7 was rejecting realistic
# extractions as "no match" with no real gain in false-positive safety.
_MATCH_THRESHOLD = 0.55

_SKILLS_HEADING_KEYWORDS = ("skill", "technical", "technolog", "tools")


@dataclass
class CorrelationResult:
    # Profile-relative synthetic block id -> real document block id.
    block_id_map: dict[str, str] = field(default_factory=dict)
    # matched / correlatable fields. Excludes "skills", which has no single
    # original text to match against (see _find_skills_block) and so isn't a
    # signal about how reliable the rest of the correlation is.
    match_rate: float = 0.0
    matched_count: int = 0
    total_count: int = 0


def correlate_profile_to_layout(ranked_profile: dict, layout: ResumeLayoutDocument) -> CorrelationResult:
    all_blocks = [block for section in layout.sections for block in section.blocks]
    used_block_ids: set[str] = set()
    block_id_map: dict[str, str] = {}
    total = 0
    matched = 0

    def try_match(synthetic_id: str, text: str) -> None:
        nonlocal total, matched
        if not text or not text.strip():
            logger.debug("correlate: %s skipped — no original text to match against", synthetic_id)
            return
        total += 1
        block, ratio = _best_match(text, all_blocks, used_block_ids)
        if block is not None and ratio >= _MATCH_THRESHOLD:
            block_id_map[synthetic_id] = block.block_id
            used_block_ids.add(block.block_id)
            matched += 1
            logger.debug("correlate: %s -> %s (ratio=%.2f)", synthetic_id, block.block_id, ratio)
        else:
            logger.debug(
                "correlate: %s did NOT match (best_candidate=%s, best_ratio=%.2f, threshold=%.2f)",
                synthetic_id, block.block_id if block else None, ratio, _MATCH_THRESHOLD,
            )

    try_match("headline", ranked_profile.get("headline") or "")
    try_match("summary", ranked_profile.get("summary") or "")

    for i, entry in enumerate(ranked_profile.get("work_experience") or []):
        for j, bullet in enumerate(entry.get("bullets") or []):
            try_match(f"work_experience[{i}].bullets[{j}]", bullet or "")

    for i, project in enumerate(ranked_profile.get("projects") or []):
        try_match(f"projects[{i}].description", project.get("description") or "")

    skills_block = _find_skills_block(layout, used_block_ids)
    if skills_block is not None:
        block_id_map["skills"] = skills_block.block_id
        logger.debug("correlate: skills -> %s", skills_block.block_id)
    else:
        logger.debug("correlate: skills did NOT match — no single-block skills section found")

    match_rate = (matched / total) if total else 0.0
    logger.info(
        "correlate_profile_to_layout: matched %d/%d correlatable fields (%.0f%%)%s",
        matched, total, match_rate * 100, "" if total else " (nothing to correlate)",
    )
    return CorrelationResult(block_id_map=block_id_map, match_rate=match_rate, matched_count=matched, total_count=total)


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _best_match(text: str, blocks: list[TextBlock], used_block_ids: set[str]) -> tuple[TextBlock | None, float]:
    target = _normalize(text)
    if not target:
        return None, 0.0

    best_block, best_ratio = None, 0.0
    for block in blocks:
        if block.block_id in used_block_ids:
            continue
        ratio = SequenceMatcher(None, _normalize(block.text), target).ratio()
        if ratio > best_ratio:
            best_block, best_ratio = block, ratio
    return best_block, best_ratio


def _find_skills_block(layout: ResumeLayoutDocument, used_block_ids: set[str]) -> TextBlock | None:
    """
    Finds the single real block representing "the skills section" so the
    LLM's freshly-synthesized skills list can be written back in place.

    PDF layouts may already carry role=SKILLS from gemini_vision_layout_agent.py.
    DOCX layouts never carry section roles (docx_layout_extractor.py doesn't
    classify them), so this falls back to a heading-keyword heuristic. Either
    way, only a section with exactly one un-claimed, non-heading content
    block is used — a multi-block skills section (e.g. one line per category)
    has no single place to put one consolidated list, so it's left
    uncorrelated (skills still shows up correctly in optimized_resume for the
    API/DB/UI; it just won't be rewritten in-place in that document) rather
    than guessed at.
    """
    for section in layout.sections:
        if not _is_skills_section(section):
            continue
        content_blocks = [
            block for block in section.blocks
            if block.block_id not in used_block_ids and not is_heading_block(block)
        ]
        if len(content_blocks) == 1:
            return content_blocks[0]
    return None


def _is_skills_section(section: LayoutSection) -> bool:
    if section.role == SectionRole.SKILLS:
        return True
    heading = section.blocks[0] if section.blocks else None
    return heading is not None and is_heading_block(heading) and _mentions_skills(heading.text)


def is_heading_block(block: TextBlock) -> bool:
    """Public since resume_section_order.py reuses this same style-based
    heading check to classify docx section headings."""
    style_name = (block.docx_anchor.style_name or "") if block.docx_anchor else ""
    return style_name.lower().startswith("heading") or style_name.lower() == "title"


def _mentions_skills(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _SKILLS_HEADING_KEYWORDS)
