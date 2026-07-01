from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from services.github_profile_fetcher import extract_username, fetch_github_profile


# ---------------------------------------------------------------------------
# extract_username — pure function, no mocking
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/octocat", "octocat"),
        ("https://github.com/octocat/", "octocat"),
        ("github.com/octocat", "octocat"),
        ("https://www.github.com/octocat", "octocat"),
        ("https://example.com/octocat", None),
        ("", None),
        (None, None),
    ],
)
def test_extract_username(url, expected):
    assert extract_username(url) == expected


# ---------------------------------------------------------------------------
# fetch_github_profile — mocked httpx
# ---------------------------------------------------------------------------

def _response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture
def mock_client():
    with patch("services.github_profile_fetcher.httpx.AsyncClient") as patched:
        client = AsyncMock()
        patched.return_value.__aenter__.return_value = client
        yield client


@pytest.mark.anyio
async def test_returns_none_and_empty_for_no_url(mock_client):
    profile_text, repos = await fetch_github_profile(None)

    assert profile_text is None
    assert repos == []
    mock_client.get.assert_not_called()


@pytest.mark.anyio
async def test_returns_none_and_empty_for_unparseable_url(mock_client):
    profile_text, repos = await fetch_github_profile("https://example.com")

    assert profile_text is None
    assert repos == []
    mock_client.get.assert_not_called()


@pytest.mark.anyio
async def test_successful_fetch_builds_profile_text_and_repos(mock_client):
    user = {"name": "The Octocat", "bio": "GitHub mascot", "company": "GitHub", "location": "SF"}
    repos = [
        {"name": "spoon-knife", "description": "A repo", "language": "Ruby",
         "topics": [], "html_url": "https://github.com/octocat/spoon-knife", "stargazers_count": 5},
    ]
    mock_client.get.side_effect = [_response(user), _response(repos)]

    profile_text, result_repos = await fetch_github_profile("https://github.com/octocat")

    assert profile_text == "The Octocat · GitHub mascot · GitHub · SF"
    assert len(result_repos) == 1
    assert result_repos[0].name == "spoon-knife"
    assert result_repos[0].languages == ["Ruby"]
    assert result_repos[0].stars == 5


@pytest.mark.anyio
async def test_caps_repos_at_ten_sorted_by_stars(mock_client):
    user = {"name": "Someone"}
    repos = [
        {"name": f"repo-{i}", "stargazers_count": i, "html_url": None, "topics": []}
        for i in range(15)
    ]
    mock_client.get.side_effect = [_response(user), _response(repos)]

    _, result_repos = await fetch_github_profile("https://github.com/someone")

    assert len(result_repos) == 10
    assert result_repos[0].name == "repo-14"  # highest stars first
    assert result_repos[-1].name == "repo-5"


@pytest.mark.anyio
async def test_user_not_found_returns_none_and_empty(mock_client):
    mock_client.get.side_effect = [_response({}, status_code=404)]

    profile_text, repos = await fetch_github_profile("https://github.com/doesnotexist")

    assert profile_text is None
    assert repos == []


@pytest.mark.anyio
async def test_network_error_returns_none_and_empty(mock_client):
    mock_client.get.side_effect = httpx.ConnectError("boom")

    profile_text, repos = await fetch_github_profile("https://github.com/octocat")

    assert profile_text is None
    assert repos == []


@pytest.mark.anyio
async def test_malformed_repos_response_returns_profile_only(mock_client):
    user = {"name": "Someone"}
    mock_client.get.side_effect = [_response(user), _response({"not": "a list"})]

    profile_text, repos = await fetch_github_profile("https://github.com/someone")

    assert profile_text == "Someone"
    assert repos == []
