from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.portfolio_scraper import fetch_portfolio_text

# A real-looking public IP, used as the default DNS answer for "jane.dev" etc.
_PUBLIC_ADDRINFO = [(2, 1, 6, "", ("93.184.216.34", 0))]


def _response(html: str, status_code: int = 200, next_request=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    resp.next_request = next_request
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def mock_client():
    with patch("services.portfolio_scraper.httpx.AsyncClient") as patched, \
         patch("services.portfolio_scraper.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO):
        client = AsyncMock()
        patched.return_value.__aenter__.return_value = client
        yield client


@pytest.mark.anyio
async def test_returns_none_for_no_url(mock_client):
    text = await fetch_portfolio_text(None)

    assert text is None
    mock_client.send.assert_not_called()


@pytest.mark.anyio
async def test_extracts_text_from_html(mock_client):
    html = "<html><body><h1>Jane Doe</h1><p>Full-stack engineer.</p><script>ignore()</script></body></html>"
    mock_client.send.return_value = _response(html)

    text = await fetch_portfolio_text("https://jane.dev")

    assert "Jane Doe" in text
    assert "Full-stack engineer." in text


@pytest.mark.anyio
async def test_collapses_whitespace(mock_client):
    html = "<html><body><p>Line one</p>\n\n<p>   Line   two   </p></body></html>"
    mock_client.send.return_value = _response(html)

    text = await fetch_portfolio_text("https://jane.dev")

    assert "  " not in text


@pytest.mark.anyio
async def test_non_200_returns_none(mock_client):
    mock_client.send.return_value = _response("", status_code=404)

    text = await fetch_portfolio_text("https://jane.dev/missing")

    assert text is None


@pytest.mark.anyio
async def test_connection_error_returns_none(mock_client):
    mock_client.send.side_effect = httpx.ConnectError("boom")

    text = await fetch_portfolio_text("https://unreachable.example")

    assert text is None


@pytest.mark.anyio
async def test_empty_page_returns_none(mock_client):
    mock_client.send.return_value = _response("<html><body></body></html>")

    text = await fetch_portfolio_text("https://jane.dev")

    assert text is None


@pytest.mark.anyio
async def test_truncates_long_pages():
    from services import portfolio_scraper

    long_html = "<html><body><p>" + ("word " * 10000) + "</p></body></html>"
    with patch("services.portfolio_scraper.httpx.AsyncClient") as patched, \
         patch("services.portfolio_scraper.socket.getaddrinfo", return_value=_PUBLIC_ADDRINFO):
        client = AsyncMock()
        patched.return_value.__aenter__.return_value = client
        client.send.return_value = _response(long_html)

        text = await portfolio_scraper.fetch_portfolio_text("https://jane.dev")

    assert len(text) == portfolio_scraper._MAX_CHARS


@pytest.mark.anyio
async def test_rejects_metadata_ip(mock_client):
    with patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
    ):
        text = await fetch_portfolio_text("http://169.254.169.254/latest/meta-data/")

    assert text is None
    mock_client.send.assert_not_called()


@pytest.mark.anyio
async def test_rejects_loopback_ip_in_production(mock_client):
    with patch("services.portfolio_scraper.settings.environment", "production"), patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
    ):
        text = await fetch_portfolio_text("http://127.0.0.1/admin")

    assert text is None
    mock_client.send.assert_not_called()


@pytest.mark.anyio
async def test_rejects_private_ip_in_production(mock_client):
    with patch("services.portfolio_scraper.settings.environment", "production"), patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("10.0.0.5", 0))],
    ):
        text = await fetch_portfolio_text("http://10.0.0.5/internal")

    assert text is None
    mock_client.send.assert_not_called()


@pytest.mark.anyio
async def test_allows_loopback_ip_in_development(mock_client):
    with patch("services.portfolio_scraper.settings.environment", "development"), patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("127.0.0.1", 0))],
    ):
        mock_client.send.return_value = _response("<html><body><p>Local dev server</p></body></html>")

        text = await fetch_portfolio_text("http://127.0.0.1:5173/")

    assert text is not None
    assert "Local dev server" in text


@pytest.mark.anyio
async def test_allows_private_ip_in_development(mock_client):
    with patch("services.portfolio_scraper.settings.environment", "development"), patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("192.168.1.50", 0))],
    ):
        mock_client.send.return_value = _response("<html><body><p>LAN server</p></body></html>")

        text = await fetch_portfolio_text("http://192.168.1.50:8000/")

    assert text is not None
    assert "LAN server" in text


@pytest.mark.anyio
async def test_rejects_metadata_ip_even_in_development(mock_client):
    with patch("services.portfolio_scraper.settings.environment", "development"), patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("169.254.169.254", 0))],
    ):
        text = await fetch_portfolio_text("http://169.254.169.254/latest/meta-data/")

    assert text is None
    mock_client.send.assert_not_called()


@pytest.mark.anyio
async def test_rejects_non_http_scheme(mock_client):
    text = await fetch_portfolio_text("ftp://example.com/file")

    assert text is None
    mock_client.send.assert_not_called()


@pytest.mark.anyio
async def test_rejects_redirect_to_private_ip(mock_client):
    redirect_request = httpx.Request("GET", "http://internal.example/secret")

    with patch("services.portfolio_scraper.settings.environment", "production"), patch(
        "services.portfolio_scraper.socket.getaddrinfo",
        side_effect=[_PUBLIC_ADDRINFO, [(2, 1, 6, "", ("10.0.0.5", 0))]],
    ):
        mock_client.send.return_value = _response("", status_code=302, next_request=redirect_request)

        text = await fetch_portfolio_text("https://jane.dev")

    assert text is None
    mock_client.send.assert_called_once()
