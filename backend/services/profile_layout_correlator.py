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

# PDF blocks have no paragraph style to check (see is_heading_block), so a
# heading there is instead recognized structurally: real section headers
# ("Education", "Technical Skills") are short and entirely bold, unlike a
# content line that merely starts with a bold label ("Developer Tools: AWS,
# Postman, ..."), which mixes a bold run with plain ones.
_MAX_PDF_HEADING_WORDS = 5


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
    # Real block ids of extra, unclaimed skills-section blocks beyond the
    # primary one mapped under block_id_map["skills"] — see _find_skills_block.
    skills_overflow_block_ids: list[str] = field(default_factory=list)


def correlate_profile_to_layout(ranked_profile: dict, layout: ResumeLayoutDocument) -> CorrelationResult:
    all_blocks = [block for section in layout.sections for block in section.blocks]
    total = 0

    fields: list[tuple[str, str]] = []

    def collect(synthetic_id: str, text: str) -> None:
        nonlocal total
        if not text or not text.strip():
            logger.debug("correlate: %s skipped — no original text to match against", synthetic_id)
            return
        total += 1
        fields.append((synthetic_id, text))

    collect("headline", ranked_profile.get("headline") or "")
    collect("summary", ranked_profile.get("summary") or "")

    for i, entry in enumerate(ranked_profile.get("work_experience") or []):
        for j, bullet in enumerate(entry.get("bullets") or []):
            collect(f"work_experience[{i}].bullets[{j}]", bullet or "")

    for i, project in enumerate(ranked_profile.get("projects") or []):
        collect(f"projects[{i}].description", project.get("description") or "")

    block_id_map, matched = _assign_best_matches(fields, all_blocks)
    used_block_ids = set(block_id_map.values())

    skills_block, skills_overflow = _find_skills_blocks(layout, used_block_ids)
    if skills_block is not None:
        block_id_map["skills"] = skills_block.block_id
        logger.debug("correlate: skills -> %s", skills_block.block_id)
        if skills_overflow:
            logger.debug(
                "correlate: skills section has %d extra block(s) beyond the primary — flagged as overflow: %s",
                len(skills_overflow), [b.block_id for b in skills_overflow],
            )
    else:
        logger.debug("correlate: skills did NOT match — no skills section with a content block found")

    match_rate = (matched / total) if total else 0.0
    logger.info(
        "correlate_profile_to_layout: matched %d/%d correlatable fields (%.0f%%)%s",
        matched, total, match_rate * 100, "" if total else " (nothing to correlate)",
    )
    return CorrelationResult(
        block_id_map=block_id_map,
        match_rate=match_rate,
        matched_count=matched,
        total_count=total,
        skills_overflow_block_ids=[b.block_id for b in skills_overflow],
    )


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _assign_best_matches(fields: list[tuple[str, str]], blocks: list[TextBlock]) -> tuple[dict[str, str], int]:
    """
    Assigns each (synthetic_id, text) field to at most one block, globally
    picking the highest-ratio available (field, block) pair first rather than
    resolving fields one at a time in declaration order. Declaration-order
    greedy lets an earlier field claim a block it matches only decently,
    starving a later field that would have matched that same block far
    better — global assignment can only match equal-or-more fields than that
    for the same threshold and input, since it never lets a weak claim block
    a strong one.
    """
    normalized_field_texts = [_normalize(text) for _, text in fields]
    normalized_block_texts = [_normalize(block.text) for block in blocks]

    candidates: list[tuple[float, int, int]] = []
    for field_index, field_text in enumerate(normalized_field_texts):
        if not field_text:
            continue
        for block_index, block_text in enumerate(normalized_block_texts):
            ratio = SequenceMatcher(None, block_text, field_text).ratio()
            if ratio >= _MATCH_THRESHOLD:
                candidates.append((ratio, field_index, block_index))

    # Highest ratio first; index order as a deterministic tiebreak so equal-
    # ratio candidates resolve the same way every time.
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))

    block_id_map: dict[str, str] = {}
    matched_field_indices: set[int] = set()
    matched_block_indices: set[int] = set()
    for ratio, field_index, block_index in candidates:
        if field_index in matched_field_indices or block_index in matched_block_indices:
            continue
        synthetic_id, _ = fields[field_index]
        block = blocks[block_index]
        block_id_map[synthetic_id] = block.block_id
        matched_field_indices.add(field_index)
        matched_block_indices.add(block_index)
        logger.debug("correlate: %s -> %s (ratio=%.2f)", synthetic_id, block.block_id, ratio)

    for field_index, (synthetic_id, _) in enumerate(fields):
        if field_index not in matched_field_indices:
            logger.debug("correlate: %s did NOT match (threshold=%.2f)", synthetic_id, _MATCH_THRESHOLD)

    return block_id_map, len(matched_field_indices)


def _find_skills_blocks(layout: ResumeLayoutDocument, used_block_ids: set[str]) -> tuple[TextBlock | None, list[TextBlock]]:
    """
    Finds the real block(s) representing "the skills section" so the LLM's
    freshly-synthesized skills list can be written back in place.

    PDF layouts may already carry role=SKILLS from gemini_vision_layout_agent.py.
    DOCX layouts never carry section roles (docx_layout_extractor.py doesn't
    classify them), so this falls back to a heading-keyword heuristic. The
    first un-claimed, non-heading content block (document order) becomes the
    primary block that receives the full consolidated skills list; any
    further content blocks in that same section (e.g. one line per category,
    or a table) are returned as overflow so the caller can blank them rather
    than leave stale pre-optimization skill text sitting next to the new list.
    """
    for section in layout.sections:
        if not _is_skills_section(section):
            continue
        content_blocks = [
            block for block in section.blocks
            if block.block_id not in used_block_ids and not is_heading_block(block)
        ]
        if content_blocks:
            return content_blocks[0], content_blocks[1:]
    return None, []


def _is_skills_section(section: LayoutSection) -> bool:
    if section.role == SectionRole.SKILLS:
        return True
    heading = section.blocks[0] if section.blocks else None
    return heading is not None and is_heading_block(heading) and _mentions_skills(heading.text)


def is_heading_block(block: TextBlock) -> bool:
    """Public since resume_section_order.py reuses this same heading check
    to classify docx *and* pdf section headings.

    DOCX carries an actual paragraph style to check. PDF has no such
    metadata, so a heading there is recognized structurally instead — see
    _MAX_PDF_HEADING_WORDS.
    """
    if block.docx_anchor is not None:
        style_name = block.docx_anchor.style_name or ""
        return style_name.lower().startswith("heading") or style_name.lower() == "title"
    if block.pdf_anchor is not None:
        return (
            bool(block.runs)
            and all(run.bold for run in block.runs)
            and len(block.text.split()) <= _MAX_PDF_HEADING_WORDS
        )
    return False


def _mentions_skills(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _SKILLS_HEADING_KEYWORDS)
