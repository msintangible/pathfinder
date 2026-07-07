import io
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

from services.resume_section_order import DEFAULT_SECTION_ORDER

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), autoescape=True)


class PDFRenderError(Exception):
    pass


def render_pdf(optimized_resume: dict, section_order: list[str] | None = None) -> bytes:
    """
    Render an OptimizedResume dict to PDF bytes via the resume.html template.

    section_order controls which order the Skills/Experience/Projects
    sections appear in (see services/resume_section_order.py) — this can't
    reproduce the candidate's original fonts/spacing (that's the in-place
    renderers' job), but at least keeps the fallback's section order
    consistent with their real document's, instead of always using a fixed
    order regardless of source.
    """
    order = section_order or DEFAULT_SECTION_ORDER
    logger.debug("render_pdf: using section_order=%s", order)
    html = _env.get_template("resume.html").render(section_order=order, **optimized_resume)

    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise PDFRenderError(f"xhtml2pdf failed with {result.err} error(s)")

    return buffer.getvalue()
