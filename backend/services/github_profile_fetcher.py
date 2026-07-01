import os
import re

import httpx

from schemas.profile import RawGitHubRepo

_GITHUB_API = "https://api.github.com"
_MAX_REPOS = 10
_USERNAME_RE = re.compile(r"github\.com/([A-Za-z0-9-]+)")


def extract_username(github_url: str) -> str | None:
    """Pull the username out of a github.com/<user> URL. None if unparseable."""
    match = _USERNAME_RE.search(github_url or "")
    return match.group(1) if match else None


def _profile_text(user: dict) -> str | None:
    parts = [p for p in (user.get("name"), user.get("bio"), user.get("company"), user.get("location")) if p]
    return " · ".join(parts) if parts else None


def _to_repo(raw: dict) -> RawGitHubRepo | None:
    if not raw.get("name"):
        return None
    return RawGitHubRepo(
        name=raw["name"],
        description=raw.get("description"),
        languages=[raw["language"]] if raw.get("language") else [],
        topics=raw.get("topics") or [],
        readme=None,  # skipped in v1 to bound API calls against the unauthenticated rate limit
        url=raw.get("html_url"),
        stars=raw.get("stargazers_count"),
    )


async def fetch_github_profile(github_url: str | None) -> tuple[str | None, list[RawGitHubRepo]]:
    """
    Fetch a public GitHub profile (bio) + top repos by star count.

    Never raises — a bad URL, a private/nonexistent user, a rate limit, or a
    network error all degrade to (None, []) so a flaky GitHub API never blocks
    CV import.
    """
    username = extract_username(github_url) if github_url else None
    if not username:
        return None, []

    headers = {"Accept": "application/vnd.github+json"}
    token = os.getenv("GITHUB_TOKEN")  # optional — raises 60/hr limit to 5000/hr
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
            user_resp = await client.get(f"{_GITHUB_API}/users/{username}")
            user_resp.raise_for_status()
            repos_resp = await client.get(
                f"{_GITHUB_API}/users/{username}/repos",
                params={"sort": "updated", "per_page": 100, "type": "owner"},
            )
            repos_resp.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None, []

    profile_text = _profile_text(user_resp.json())

    repos_json = repos_resp.json()
    if not isinstance(repos_json, list):
        return profile_text, []

    top = sorted(repos_json, key=lambda r: r.get("stargazers_count") or 0, reverse=True)[:_MAX_REPOS]
    repos = [repo for raw in top if (repo := _to_repo(raw)) is not None]
    return profile_text, repos
