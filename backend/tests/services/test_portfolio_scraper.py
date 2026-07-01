from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.portfolio_scraper import fetch_portfolio_text


def _response(html: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def mock_client():
    with patch("services.portfolio_scraper.httpx.AsyncClient") as patched:
        client = AsyncMock()
        patched.return_value.__aenter__.return_value = client
        yield client


@pytest.mark.anyio
async def test_returns_none_for_no_url(mock_client):
    text = await fetch_portfolio_text(None)

    assert text is None
    mock_client.get.assert_not_called()


@pytest.mark.anyio
async def test_extracts_text_from_html(mock_client):
    html = "<html><body><h1>Jane Doe</h1><p>Full-stack engineer.</p><script>ignore()</script></body></html>"
    mock_client.get.return_value = _response(html)

    text = await fetch_portfolio_text("https://jane.dev")

    assert "Jane Doe" in text
    assert "Full-stack engineer." in text


@pytest.mark.anyio
async def test_collapses_whitespace(mock_client):
    html = "<html><body><p>Line one</p>\n\n<p>   Line   two   </p></body></html>"
    mock_client.get.return_value = _response(html)

    text = await fetch_portfolio_text("https://jane.dev")

    assert "  " not in text


@pytest.mark.anyio
async def test_non_200_returns_none(mock_client):
    mock_client.get.return_value = _response("", status_code=404)

    text = await fetch_portfolio_text("https://jane.dev/missing")

    assert text is None


@pytest.mark.anyio
async def test_connection_error_returns_none(mock_client):
    mock_client.get.side_effect = httpx.ConnectError("boom")

    text = await fetch_portfolio_text("https://unreachable.example")

    assert text is None


@pytest.mark.anyio
async def test_empty_page_returns_none(mock_client):
    mock_client.get.return_value = _response("<html><body></body></html>")

    text = await fetch_portfolio_text("https://jane.dev")

    assert text is None


@pytest.mark.anyio
async def test_truncates_long_pages():
    from services import portfolio_scraper

    long_html = "<html><body><p>" + ("word " * 10000) + "</p></body></html>"
    with patch("services.portfolio_scraper.httpx.AsyncClient") as patched:
        client = AsyncMock()
        patched.return_value.__aenter__.return_value = client
        client.get.return_value = _response(long_html)

        text = await portfolio_scraper.fetch_portfolio_text("https://jane.dev")

    assert len(text) == portfolio_scraper._MAX_CHARS
