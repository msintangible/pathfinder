import io
import logging
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup, escape
from xhtml2pdf import pisa

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), autoescape=True)

# The one fixed section order every resume is rendered with, now that this
# template is the sole renderer (in-place docx/pdf editing was removed —
# see the 2026-08 dead-code cleanup). Previously this deferred to each
# candidate's own document structure via a per-document inference step,
# which doesn't apply anymore now that every resume shares this same
# layout regardless of how it was originally formatted.
CANONICAL_SECTION_ORDER = [
    "summary",
    "education",
    "experience",
    "projects",
    "skills",
    "certifications",
    "awards",
    "leadership",
    "volunteering",
    "publications",
    "interests",
    "references",
]


def _markdown_emphasis(value: str | None) -> Markup:
    if not value:
        return Markup("")

    parts = re.split(r"(\*\*[^*]+\*\*)", str(value))
    rendered: list[str] = []
    for part in parts:
        if part.startswith("**") and part.endswith("**"):
            rendered.append(f"<strong>{escape(part[2:-2])}</strong>")
        else:
            rendered.append(str(escape(part)))
    return Markup("".join(rendered))


_env.filters["emphasis"] = _markdown_emphasis


class PDFRenderError(Exception):
    pass


def render_pdf(optimized_resume: dict, section_order: list[str] | None = None) -> bytes:
    """
    Render an OptimizedResume dict to PDF bytes via the resume.html template,
    using CANONICAL_SECTION_ORDER unless a caller overrides it (tests only —
    production always renders with the one fixed layout).
    """
    order = section_order or CANONICAL_SECTION_ORDER
    logger.debug("render_pdf: using section_order=%s", order)
    html = _env.get_template("resume.html").render(section_order=order, **optimized_resume)

    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise PDFRenderError(f"xhtml2pdf failed with {result.err} error(s)")

    return buffer.getvalue()
