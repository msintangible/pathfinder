import asyncio
import ipaddress
import socket

import httpx
from lxml import html as lxml_html
from lxml.html.clean import Cleaner

from core.config import settings

# Generous but bounded, same rationale as job_analysis_agent._MAX_CHARS.
_MAX_CHARS = 20000
_MAX_REDIRECTS = 5

# Strips <script>/<style>/comments before text extraction — without this,
# JS-heavy sites leak inline CSS/JSON into the "readable" text.
_cleaner = Cleaner(scripts=True, style=True, comments=True, javascript=True, page_structure=False)


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """
    Reject private/loopback/multicast/reserved/unspecified ranges. Link-local
    (169.254.0.0/16) specifically covers 169.254.169.254, the AWS/GCP/Azure
    instance-metadata address — the classic SSRF target for exfiltrating
    cloud credentials — so it stays blocked even in development.

    Private/loopback are allowed through in development only, so a developer
    can point portfolio_url at a server running on their own machine; remove
    this allowance before production (settings.environment defaults to
    "development", so it must be explicitly set to something else to deploy).
    """
    if ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if ip.is_private or ip.is_loopback:
        return settings.environment == "development"
    return True


async def _is_public_url(url: httpx.URL) -> bool:
    """
    True only if url is http(s) and its hostname resolves exclusively to
    public IPs. Checked before the first request AND before following each
    redirect hop, since a public host could otherwise redirect to an
    internal address and bypass a check that only ran once, up front.

    Accepted residual risk: DNS-rebinding TOCTOU between this resolve and the
    connection httpx opens a moment later — closing that fully needs a
    custom transport pinning the resolved IP, out of scope for the current
    threat model (requires an attacker to control DNS and win a race).
    """
    if url.scheme not in ("http", "https") or not url.host:
        return False
    try:
        # socket.getaddrinfo is blocking; keep it off the event loop.
        infos = await asyncio.to_thread(socket.getaddrinfo, url.host, None)
    except socket.gaierror:
        return False
    return all(_is_public_ip(ipaddress.ip_address(info[4][0])) for info in infos)


async def fetch_portfolio_text(portfolio_url: str | None) -> str | None:
    """Fetch and extract readable text from a candidate's portfolio site. Never raises."""
    if not portfolio_url:
        return None

    try:
        request = httpx.Request("GET", portfolio_url, headers={"User-Agent": "Pathfinder/1.0"})
        # follow_redirects=False (httpx's own default) so each hop can be
        # re-validated below before it's dialed — see _is_public_url.
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                if not await _is_public_url(request.url):
                    return None
                resp = await client.send(request)
                if resp.next_request is None:
                    break
                request = resp.next_request
            else:
                return None  # exhausted redirect budget
            resp.raise_for_status()
        tree = _cleaner.clean_html(lxml_html.fromstring(resp.text))
        text = tree.text_content()
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return None

    text = " ".join(text.split())
    return text[:_MAX_CHARS] or None
