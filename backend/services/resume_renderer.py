import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from xhtml2pdf import pisa

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATES_DIR), autoescape=True)


class PDFRenderError(Exception):
    pass


def render_pdf(optimized_resume: dict) -> bytes:
    """Render an OptimizedResume dict to PDF bytes via the resume.html template."""
    html = _env.get_template("resume.html").render(**optimized_resume)

    buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buffer)
    if result.err:
        raise PDFRenderError(f"xhtml2pdf failed with {result.err} error(s)")

    return buffer.getvalue()
