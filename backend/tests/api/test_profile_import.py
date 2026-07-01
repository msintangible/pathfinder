"""
Regression coverage for POST /v1/profile/import's empty-content guard.

Found via live verification: calling CandidateProfileAgent with a blank
prompt (no CV, no LinkedIn text, a GitHub/portfolio fetch that both came back
empty) made Gemini fabricate an entire fictional profile instead of returning
nulls, despite the agent's "never invent" system instruction. The endpoint
must refuse before ever reaching the agent in that case.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.profile import router
from database.session import get_db
from models.profile import UserProfile


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_rejects_when_no_content_could_be_extracted(client):
    """A github_url that resolves to nothing, with no other source, must 422 — not fabricate a profile."""
    with patch("api.v1.profile.fetch_github_profile", new=AsyncMock(return_value=(None, []))), \
         patch("api.v1.profile.fetch_portfolio_text", new=AsyncMock(return_value=None)), \
         patch("api.v1.profile.CandidateProfileAgent") as mock_agent_cls:
        mock_agent_cls.return_value.analyze = AsyncMock()

        resp = client.post(
            "/v1/profile/import",
            data={"github_url": "https://github.com/this-user-should-not-exist-xyz123"},
        )

        assert resp.status_code == 422
        mock_agent_cls.return_value.analyze.assert_not_called()


def test_proceeds_when_linkedin_text_present(client):
    """Real scraped content (even with no other source) must reach the agent."""
    with patch("api.v1.profile.fetch_github_profile", new=AsyncMock(return_value=(None, []))), \
         patch("api.v1.profile.fetch_portfolio_text", new=AsyncMock(return_value=None)), \
         patch("api.v1.profile.CandidateProfileAgent") as mock_agent_cls, \
         patch("api.v1.profile.ProfileRepository") as mock_repo_cls:
        mock_agent_cls.return_value.analyze = AsyncMock(return_value={"name": "Jane Doe"})
        test_id = uuid.uuid4()
        mock_repo_cls.return_value.create_from_analysis = AsyncMock(
            return_value=UserProfile(id=test_id, name="Jane Doe")
        )

        resp = client.post(
            "/v1/profile/import",
            data={"linkedin_url": "https://linkedin.com/in/jane", "linkedin_text": "Jane Doe, Engineer"},
        )

        assert resp.status_code == 200
        mock_agent_cls.return_value.analyze.assert_called_once()

        body = resp.json()
        assert body["id"] == str(test_id)
        assert body["sources"]["linkedin_text"] == "Jane Doe, Engineer"
        assert body["sources"]["resume_text"] is None
        assert body["sources"]["github_repositories"] == []
