"""
Enforces the 2-page budget on the rendered resume PDF.

The generation prompt (resume_generation_agent.py) only controls wording,
never entry count, so a candidate with a long, relevant history can still
produce a resume over budget purely from how many experience/project
entries survive relevance_ranker.py's ranking. Rather than guess at a page
budget from word counts, this renders for real and trims until it fits.

Trimming is graduated, smallest cut first:
  1. Drop the single shortest bullet from the lowest-relevance entry that
     still has more than one bullet — usually recovers a line or two
     without losing an entire entry's keyword coverage.
  2. Only once no entry has a spare bullet left to trim, drop the whole
     lowest-relevance project, then the whole lowest-relevance experience
     entry — both sections are already sorted most-relevant-first (see
     relevance_ranker.py), so "last" is always the weakest one.
Repeats step 1 until it's exhausted before ever reaching step 2, so a
resume that's only slightly over budget loses a few weak bullets rather
than an entire project or job.
"""

import logging

import fitz

from services.resume_renderer import render_pdf

logger = logging.getLogger(__name__)

MAX_PAGES = 2


def count_pdf_pages(pdf_bytes: bytes) -> int:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count


def render_within_page_limit(optimized_resume: dict, max_pages: int = MAX_PAGES) -> tuple[bytes, dict]:
    """
    Renders optimized_resume, trimming (see module docstring for the
    graduated order) and re-rendering as needed. Returns (pdf_bytes, resume)
    using whichever resume was actually rendered, so callers persist/display
    exactly what the PDF shows — never the pre-trim version.
    """
    resume = optimized_resume
    pdf_bytes = render_pdf(resume)

    while count_pdf_pages(pdf_bytes) > max_pages:
        trimmed = _remove_weakest_bullet(resume) or _drop_lowest_relevance_entry(resume)
        if trimmed is None:
            logger.warning(
                "render_within_page_limit: still over %d page(s) with nothing left worth "
                "trimming — returning as-is rather than dropping everything",
                max_pages,
            )
            break
        resume = trimmed
        pdf_bytes = render_pdf(resume)

    return pdf_bytes, resume


def _remove_weakest_bullet(resume: dict) -> dict | None:
    """
    Finds the lowest-relevance entry (checking projects before experience,
    same section priority the old whole-entry trim used, and within a
    section checking the least-relevant entry first) that still has more
    than one bullet, and drops its single shortest bullet — a proxy for
    "least content-dense," the cheapest signal available here without
    threading keyword-match data into this module. Returns None once no
    entry has a spare bullet left, so the caller falls back to dropping a
    whole entry.
    """
    for section_key in ("projects", "experience"):
        entries = resume.get(section_key) or []
        for index in range(len(entries) - 1, -1, -1):  # least relevant first
            bullets = entries[index].get("bullets") or []
            if len(bullets) <= 1:
                continue
            weakest_index = min(range(len(bullets)), key=lambda i: len(bullets[i]))
            new_bullets = [bullet for i, bullet in enumerate(bullets) if i != weakest_index]
            new_entries = list(entries)
            new_entries[index] = {**entries[index], "bullets": new_bullets}
            return {**resume, section_key: new_entries}
    return None


def _drop_lowest_relevance_entry(resume: dict) -> dict | None:
    """Last resort: drop a whole entry once no entry has a spare bullet left to trim."""
    if len(resume.get("projects") or []) > 1:
        return {**resume, "projects": resume["projects"][:-1]}
    if len(resume.get("experience") or []) > 1:
        return {**resume, "experience": resume["experience"][:-1]}
    return None
