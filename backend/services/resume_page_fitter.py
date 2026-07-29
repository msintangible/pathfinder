"""
Enforces the 2-page budget on the rendered resume PDF.

The generation prompt (resume_generation_agent.py) only controls wording,
never entry count, so a candidate with a long, relevant history can still
produce a resume over budget purely from how many experience/project
entries survive relevance_ranker.py's ranking. Rather than guess at a page
budget from word counts, this renders for real and trims the least-relevant
entry — always the last one, since both sections are already sorted
most-relevant-first — until the actual PDF fits, or there's nothing left
worth dropping.
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
    Renders optimized_resume, trimming its lowest-relevance project then
    lowest-relevance experience entry and re-rendering as needed. Returns
    (pdf_bytes, resume) using whichever resume was actually rendered, so
    callers persist/display exactly what the PDF shows — never the
    pre-trim version.
    """
    resume = optimized_resume
    pdf_bytes = render_pdf(resume)

    while count_pdf_pages(pdf_bytes) > max_pages:
        if len(resume.get("projects") or []) > 1:
            resume = {**resume, "projects": resume["projects"][:-1]}
        elif len(resume.get("experience") or []) > 1:
            resume = {**resume, "experience": resume["experience"][:-1]}
        else:
            logger.warning(
                "render_within_page_limit: still over %d page(s) with only one project and one "
                "experience entry left — returning as-is rather than dropping everything",
                max_pages,
            )
            break
        pdf_bytes = render_pdf(resume)

    return pdf_bytes, resume
