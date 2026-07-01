import httpx
from lxml import html as lxml_html
from lxml.html.clean import Cleaner

# Generous but bounded, same rationale as job_analysis_agent._MAX_CHARS.
_MAX_CHARS = 20000

# Strips <script>/<style>/comments before text extraction — without this,
# JS-heavy sites leak inline CSS/JSON into the "readable" text.
_cleaner = Cleaner(scripts=True, style=True, comments=True, javascript=True, page_structure=False)


async def fetch_portfolio_text(portfolio_url: str | None) -> str | None:
    """Fetch and extract readable text from a candidate's portfolio site. Never raises."""
    if not portfolio_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(portfolio_url, headers={"User-Agent": "Pathfinder/1.0"})
            resp.raise_for_status()
        tree = _cleaner.clean_html(lxml_html.fromstring(resp.text))
        text = tree.text_content()
    except (httpx.HTTPError, ValueError):
        return None

    text = " ".join(text.split())
    return text[:_MAX_CHARS] or None
