from unittest.mock import patch

from services.resume_page_fitter import count_pdf_pages, render_within_page_limit
from services.resume_renderer import render_pdf

# Mirrors every key OptimizedResume.model_dump() always emits (see
# schemas/resume.py and test_resume_renderer.py) — the template accesses
# some of these via attribute (e.g. links.linkedin), which raises if the key
# is missing entirely rather than just empty.
_BASE_RESUME: dict = {
    "name": None, "email": None, "phone": None, "headline": None, "summary": None,
    "links": {}, "skills": [], "skill_groups": [], "experience": [], "projects": [],
    "education": [], "certifications": [], "awards": [], "leadership": [],
    "volunteering": [], "publications": [], "interests": [], "references": [],
    "changes_summary": [],
}


def _resume(**overrides) -> dict:
    return {**_BASE_RESUME, **overrides}


def test_count_pdf_pages_counts_a_real_rendered_pdf():
    pdf_bytes = render_pdf(_resume(name="Jane Doe", summary="Backend engineer."))

    assert count_pdf_pages(pdf_bytes) == 1


def test_short_resume_fits_without_any_trimming():
    resume = _resume(
        name="Jane Doe",
        summary="Backend engineer.",
        experience=[{"title": "Engineer", "company": "Acme", "bullets": ["Built things."]}],
        projects=[{"name": "Widget", "description": "A widget."}],
        skills=["Python"],
    )

    pdf_bytes, rendered_resume = render_within_page_limit(resume)

    assert pdf_bytes[:4] == b"%PDF"
    assert count_pdf_pages(pdf_bytes) <= 2
    assert rendered_resume == resume


def test_removes_the_shortest_bullet_from_the_least_relevant_entry_first():
    """Graduated trim, step 1: an entry with a spare bullet loses only its
    shortest bullet — not the whole entry — before anything else is
    touched. Both projects still survive, unlike the old whole-entry-drop
    behavior."""
    resume = {
        "name": "Jane Doe",
        "experience": [],
        "projects": [
            {"name": "Project 0", "bullets": ["A reasonably long and detailed bullet point here."]},
            {"name": "Project 1", "bullets": ["Short one.", "A much longer bullet point with more detail in it."]},
        ],
    }

    with patch("services.resume_page_fitter.render_pdf", return_value=b"final-pdf") as mock_render_pdf, \
         patch("services.resume_page_fitter.count_pdf_pages", side_effect=[3, 2]) as mock_count_pages:
        pdf_bytes, rendered_resume = render_within_page_limit(resume)

    assert pdf_bytes == b"final-pdf"
    # Project 1 (least relevant — last in the list) loses its shortest
    # bullet ("Short one."); Project 0 and Project 1's longer bullet survive.
    assert len(rendered_resume["projects"]) == 2
    assert rendered_resume["projects"][1]["bullets"] == ["A much longer bullet point with more detail in it."]
    assert mock_render_pdf.call_count == 2
    assert mock_count_pages.call_count == 2


def test_drops_a_whole_entry_only_once_no_entry_has_a_spare_bullet():
    """Entries with no bullets field at all (or only one bullet each) have
    nothing left for step 1 to trim — falls back to the old whole-entry
    drop, projects before experience, same section priority as before."""
    resume = {
        "name": "Jane Doe",
        "experience": [{"title": f"Job {i}"} for i in range(3)],
        "projects": [{"name": f"Project {i}"} for i in range(3)],
    }

    with patch("services.resume_page_fitter.render_pdf", return_value=b"final-pdf") as mock_render_pdf, \
         patch("services.resume_page_fitter.count_pdf_pages", side_effect=[3, 3, 3, 2]) as mock_count_pages:
        pdf_bytes, rendered_resume = render_within_page_limit(resume)

    assert pdf_bytes == b"final-pdf"
    assert len(rendered_resume["projects"]) == 1
    assert len(rendered_resume["experience"]) == 2
    assert mock_render_pdf.call_count == 4
    assert mock_count_pages.call_count == 4


def test_stops_without_looping_forever_when_still_over_limit_at_minimal_content(caplog):
    resume = {
        "name": "Jane Doe",
        "experience": [{"title": "Only Job"}],
        "projects": [{"name": "Only Project"}],
    }

    with patch("services.resume_page_fitter.render_pdf", return_value=b"still-too-big") as mock_render_pdf, \
         patch("services.resume_page_fitter.count_pdf_pages", return_value=3):
        pdf_bytes, rendered_resume = render_within_page_limit(resume)

    assert pdf_bytes == b"still-too-big"
    assert rendered_resume == resume
    assert mock_render_pdf.call_count == 1
    assert "still over" in caplog.text
