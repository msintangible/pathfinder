"""
Patch Engine — the only component permitted to turn LLM-authored wording
changes into an updated ResumeLayoutDocument.

Per this project's architecture rule, the optimization LLM only ever emits
ContentPatch[] ({block_id, new_text} pairs) — never a modified layout model
directly. This module is the deterministic step that validates those patches
against a real ResumeLayoutDocument and applies them, redistributing each
block's new text across its existing RunSpans so per-run formatting (bold/
italic/font) survives a wording change. Renderers (docx_renderer_v2.py,
pdf_renderer_v2.py — later phases) only ever see the *already-patched*
document; they contain no patch-matching or redistribution logic of their
own.
"""

import logging
from dataclasses import dataclass, field

from schemas.resume_layout import ContentPatch, LayoutSection, ResumeLayoutDocument, RunSpan, SectionRole, TextBlock

logger = logging.getLogger(__name__)

# Checked in this order against a block's *original* text to detect the
# delimiter style a skills list was written in.
_SKILLS_SEPARATORS = [",", "|", ";", "•", "·"]


@dataclass
class PatchApplicationResult:
    document: ResumeLayoutDocument
    rejected_block_ids: list[str] = field(default_factory=list)


def apply_patches(document: ResumeLayoutDocument, patches: list[ContentPatch]) -> PatchApplicationResult:
    """Apply `patches` to a copy of `document`; the input document is never mutated."""
    patched = document.model_copy(deep=True)
    block_index: dict[str, tuple[LayoutSection, TextBlock]] = {
        block.block_id: (section, block)
        for section in patched.sections
        for block in section.blocks
    }

    rejected: list[str] = []
    for patch in patches:
        match = block_index.get(patch.block_id)
        if match is None:
            logger.warning("Rejecting patch for unknown block_id: %s", patch.block_id)
            rejected.append(patch.block_id)
            continue

        section, block = match
        block.runs = _redistribute(section, block, patch.new_text)
        block.text = patch.new_text

    return PatchApplicationResult(document=patched, rejected_block_ids=rejected)


def _redistribute(section: LayoutSection, block: TextBlock, new_text: str) -> list[RunSpan]:
    if section.role == SectionRole.SKILLS and len(block.runs) > 1:
        separator = _detect_separator(block.text)
        if separator is not None:
            return _redistribute_skills(block.runs, new_text, separator)

    if len(block.runs) <= 1:
        return _redistribute_single_run(block.runs, new_text)

    return _redistribute_multi_run(block.runs, new_text)


def _redistribute_single_run(runs: list[RunSpan], new_text: str) -> list[RunSpan]:
    if not runs:
        return [RunSpan(text=new_text)]
    return [runs[0].model_copy(update={"text": new_text})]


def _redistribute_multi_run(runs: list[RunSpan], new_text: str) -> list[RunSpan]:
    """Word-level alignment: each run keeps roughly the same *share* of words
    it held before, so a reworded bullet still lands on the same run
    boundaries (e.g. a bolded lead-in phrase stays bold)."""
    original_word_counts = [len(run.text.split()) for run in runs]
    total_original_words = sum(original_word_counts)
    new_words = new_text.split()

    if total_original_words == 0 or not new_words:
        logger.warning("Multi-run redistribution has nothing to align on — falling back to run 0")
        return _fallback_first_run(runs, new_text)

    allocation = _largest_remainder_allocation(original_word_counts, total_original_words, len(new_words))

    updated = []
    cursor = 0
    for run, count in zip(runs, allocation):
        words = new_words[cursor:cursor + count]
        cursor += count
        updated.append(run.model_copy(update={"text": " ".join(words)}))
    return updated


def _fallback_first_run(runs: list[RunSpan], new_text: str) -> list[RunSpan]:
    updated = [runs[0].model_copy(update={"text": new_text})]
    updated.extend(run.model_copy(update={"text": ""}) for run in runs[1:])
    return updated


def _largest_remainder_allocation(word_counts: list[int], total_words: int, new_total: int) -> list[int]:
    """Scale each run's original word share to integers summing exactly to
    new_total, using the largest-remainder method so no run's share drifts
    from simple truncation of the proportional split."""
    raw_shares = [count / total_words * new_total for count in word_counts]
    allocation = [int(share) for share in raw_shares]
    remainder = new_total - sum(allocation)

    by_leftover_share = sorted(range(len(raw_shares)), key=lambda i: raw_shares[i] - allocation[i], reverse=True)
    for i in by_leftover_share[:remainder]:
        allocation[i] += 1
    return allocation


def _detect_separator(text: str) -> str | None:
    for separator in _SKILLS_SEPARATORS:
        if separator in text:
            return separator
    return None


def _redistribute_skills(runs: list[RunSpan], new_text: str, separator: str) -> list[RunSpan]:
    """Cap-and-replace-in-place: one new item per existing run, in the
    section's detected separator style. Overflow items (more new items than
    runs) are appended into the last run rather than growing the run count;
    unused runs (fewer new items than runs) are cleared rather than left
    holding stale text."""
    new_items = [item.strip() for item in new_text.split(separator) if item.strip()]
    if not new_items:
        return _fallback_first_run(runs, new_text)

    effective_count = min(len(new_items), len(runs))
    updated = []
    for index, run in enumerate(runs):
        if index >= effective_count:
            updated.append(run.model_copy(update={"text": ""}))
        elif index == effective_count - 1:
            remaining = new_items[index:]
            updated.append(run.model_copy(update={"text": f"{separator} ".join(remaining)}))
        else:
            updated.append(run.model_copy(update={"text": f"{new_items[index]}{separator} "}))
    return updated
