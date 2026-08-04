"""
Tests for resume_renderer.render_pdf — the sole resume renderer now that
in-place docx/pdf editing is no longer wired in (see api/v1/resume.py).
"""

import fitz

from services.resume_renderer import CANONICAL_SECTION_ORDER, render_pdf

# Mirrors every key OptimizedResume.model_dump() always emits (see
# schemas/resume.py) — the template accesses some of these via attribute
# (e.g. links.linkedin), which raises if the key is missing entirely rather
# than just empty, unlike a dict that's merely missing a sub-key.
_BASE_RESUME: dict = {
    "name": None, "email": None, "phone": None, "headline": None, "summary": None,
    "links": {}, "skills": [], "skill_groups": [], "experience": [], "projects": [],
    "education": [], "certifications": [], "awards": [], "leadership": [],
    "volunteering": [], "publications": [], "interests": [], "references": [],
    "changes_summary": [],
}


def _resume(**overrides) -> dict:
    return {**_BASE_RESUME, **overrides}


def _page_text(pdf_bytes: bytes) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


def test_renders_valid_pdf_bytes():
    pdf_bytes = render_pdf(_resume(name="Jane Doe", summary="Backend engineer."))

    assert pdf_bytes[:4] == b"%PDF"


def test_skill_list_renders_a_real_bullet_not_the_html_entity():
    """Regression test: the join separator used to be the literal string
    " &bull; ", which Jinja2 autoescaping turned into visible "&bull;" text
    instead of a bullet glyph (see templates/resume.html)."""
    pdf_bytes = render_pdf(_resume(name="Jane Doe", skills=["Python", "SQL"]))

    text = _page_text(pdf_bytes)

    assert "&bull;" not in text
    assert "•" in text


def test_tech_stack_list_renders_a_real_bullet_not_the_html_entity():
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        projects=[{"name": "Widget", "technologies": ["Python", "FastAPI"], "description": "A widget."}],
    ))

    text = _page_text(pdf_bytes)

    assert "&bull;" not in text
    assert "•" in text


def test_omits_sections_with_no_data():
    pdf_bytes = render_pdf(_resume(name="Jane Doe", summary="Backend engineer."))

    text = _page_text(pdf_bytes)

    assert "Experience" not in text
    assert "Projects" not in text
    assert "Technical Skills" not in text


def test_includes_sections_that_have_data():
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        summary="Backend engineer.",
        experience=[{"title": "Engineer", "company": "Acme", "bullets": ["Built things."]}],
        projects=[{"name": "Widget", "description": "A widget."}],
        skills=["Python"],
    ))

    text = _page_text(pdf_bytes)

    assert "Experience" in text
    assert "Projects" in text
    assert "Technical Skills" in text


def test_uses_canonical_section_order_by_default():
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        summary="Backend engineer.",
        skills=["Python"],
        experience=[{"title": "Engineer", "company": "Acme"}],
    ))

    text = _page_text(pdf_bytes)

    # Canonical order puts Experience before Technical Skills even though
    # "skills" comes before "experience" in the dict passed in.
    assert text.index("Experience") < text.index("Technical Skills")
    assert CANONICAL_SECTION_ORDER.index("experience") < CANONICAL_SECTION_ORDER.index("skills")


def test_does_not_render_a_headline_subtitle_under_the_name():
    pdf_bytes = render_pdf(_resume(name="Jane Doe", headline="Senior Backend Engineer", summary="Backend engineer."))

    text = _page_text(pdf_bytes)

    assert "Senior Backend Engineer" not in text


def test_email_renders_as_a_real_mailto_link():
    pdf_bytes = render_pdf(_resume(name="Jane Doe", email="jane@example.com"))

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        links = [link["uri"] for link in doc[0].get_links() if "uri" in link]

    assert "mailto:jane@example.com" in links


def test_phone_renders_as_a_real_tel_link():
    pdf_bytes = render_pdf(_resume(name="Jane Doe", phone="+1 555 0100"))

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        links = [link["uri"] for link in doc[0].get_links() if "uri" in link]

    assert "tel:+1 555 0100" in links


def test_linkedin_github_portfolio_render_as_real_links():
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        links={
            "linkedin": "https://linkedin.com/in/janedoe",
            "github": "https://github.com/janedoe",
            "portfolio": "https://janedoe.dev",
        },
    ))

    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        links = [link["uri"] for link in doc[0].get_links() if "uri" in link]

    assert "https://linkedin.com/in/janedoe" in links
    assert "https://github.com/janedoe" in links
    assert "https://janedoe.dev" in links


def test_skill_groups_render_labels_and_items_in_a_table():
    """skill_groups renders as a multi-column table (see resume.html) rather
    than one full-width row per category — this only checks the text
    content survives the table layout, not the visual column count, which
    PyMuPDF text extraction can't directly assert."""
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        skill_groups=[
            {"label": "Languages", "items": ["Python", "Java"]},
            {"label": "Cloud", "items": ["Azure", "Docker"]},
        ],
    ))

    text = _page_text(pdf_bytes)

    assert "Languages" in text
    assert "Python" in text and "Java" in text
    assert "Cloud" in text
    assert "Azure" in text and "Docker" in text


def test_skill_groups_with_more_than_three_categories_all_render():
    """batch(3) wraps into additional table rows — every category must
    still appear, not just the first three."""
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        skill_groups=[
            {"label": "Languages", "items": ["Python"]},
            {"label": "Cloud", "items": ["Azure"]},
            {"label": "Databases", "items": ["Postgres"]},
            {"label": "DevOps", "items": ["Docker"]},
            {"label": "Tools", "items": ["Git"]},
        ],
    ))

    text = _page_text(pdf_bytes)

    for label in ("Languages", "Cloud", "Databases", "DevOps", "Tools"):
        assert label in text


def test_skill_groups_with_empty_items_are_skipped():
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        skill_groups=[
            {"label": "Languages", "items": ["Python"]},
            {"label": "Empty Category", "items": []},
        ],
    ))

    text = _page_text(pdf_bytes)

    assert "Languages" in text
    assert "Empty Category" not in text


def test_emphasis_filter_does_not_leak_markdown_asterisks():
    pdf_bytes = render_pdf(_resume(
        name="Jane Doe",
        summary="Backend engineer.",
        experience=[{"title": "Engineer", "company": "Acme", "bullets": ["Reduced **latency** by 40%."]}],
    ))

    text = _page_text(pdf_bytes)

    assert "**" not in text
    assert "latency" in text
