import asyncio
import os
import re

import httpx

from schemas.profile import RawGitHubRepo
from services.text_utils import truncate_text

_GITHUB_API = "https://api.github.com"
# Was 10 — raised after a real user's own repos got truncated below their
# actual count. Still bounded (not "all repos") to keep the analysis prompt's
# size predictable; _MAX_README_CHARS caps each repo's own contribution.
_MAX_REPOS = 20
# Keeps the extraction prompt bounded even with up to _MAX_REPOS READMEs
# attached — most READMEs' problem/architecture/impact framing lives in the
# intro and feature list, well within this budget.
_MAX_README_CHARS = 2000
_USERNAME_RE = re.compile(r"github\.com/([A-Za-z0-9-]+)")


def extract_username(github_url: str) -> str | None:
    """Pull the username out of a github.com/<user> URL. None if unparseable."""
    match = _USERNAME_RE.search(github_url or "")
    return match.group(1) if match else None


def _profile_text(user: dict) -> str | None:
    parts = [p for p in (user.get("name"), user.get("bio"), user.get("company"), user.get("location")) if p]
    return " · ".join(parts) if parts else None


def _to_repo(raw: dict, readme: str | None) -> RawGitHubRepo | None:
    if not raw.get("name"):
        return None
    return RawGitHubRepo(
        name=raw["name"],
        description=raw.get("description"),
        languages=[raw["language"]] if raw.get("language") else [],
        topics=raw.get("topics") or [],
        readme=readme,
        url=raw.get("html_url"),
        stars=raw.get("stargazers_count"),
    )


async def _fetch_readme(client: httpx.AsyncClient, raw: dict) -> str | None:
    """
    Fetch a repo's README as truncated raw text — mined by
    CandidateProfileAgent for richer project evidence (architecture,
    technical_achievements, impact, deployment — see schemas/profile.py's
    Project) beyond the bare name/description/topics already fetched. None
    if the repo has no full_name, has no README, or the request fails for
    any reason — never raises, same contract as fetch_github_profile itself.
    The vnd.github.raw+json media type returns the file's raw text directly
    instead of a JSON envelope with base64-encoded content.
    """
    full_name = raw.get("full_name")
    if not full_name:
        return None
    try:
        resp = await client.get(
            f"{_GITHUB_API}/repos/{full_name}/readme",
            headers={"Accept": "application/vnd.github.raw+json"},
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return truncate_text(resp.text, _MAX_README_CHARS, "\n[... README truncated]") or None


async def fetch_github_profile(github_url: str | None) -> tuple[str | None, list[RawGitHubRepo]]:
    """
    Fetch a public GitHub profile (bio) + top repos by star count, including
    each repo's README (fetched concurrently to keep latency close to a
    single round-trip despite up to _MAX_REPOS extra calls).

    Never raises — a bad URL, a private/nonexistent user, a rate limit, or a
    network error all degrade to (None, []) so a flaky GitHub API never blocks
    CV import. A single repo's README failing is handled separately inside
    _fetch_readme, so one broken README never drops the whole repo.
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

            profile_text = _profile_text(user_resp.json())

            repos_json = repos_resp.json()
            if not isinstance(repos_json, list):
                return profile_text, []

            # Forks carry none of the candidate's own work by default — a
            # starred fork would otherwise take a real project's slot under
            # the cap below.
            owned = [r for r in repos_json if not r.get("fork")]
            top = sorted(owned, key=lambda r: r.get("stargazers_count") or 0, reverse=True)[:_MAX_REPOS]
            readmes = await asyncio.gather(*[_fetch_readme(client, raw) for raw in top])
    except (httpx.HTTPError, ValueError):
        return None, []

    repos = [repo for raw, readme in zip(top, readmes) if (repo := _to_repo(raw, readme)) is not None]
    return profile_text, repos
