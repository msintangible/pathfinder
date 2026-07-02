"""
Regression coverage for POST /v1/profile/import's empty-content guard.

Found via live verification: calling CandidateProfileAgent with a blank
prompt (no CV, no LinkedIn text, a GitHub/portfolio fetch that both came back
empty) made Gemini fabricate an entire fictional profile instead of returning
nulls, despite the agent's "never invent" system instruction. The endpoint
must refuse before ever reaching the agent in that case.
"""
import io
import uuid
from unittest.mock import AsyncMock, patch

import docx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.profile import router
from core.security import get_current_user
from database.session import get_db
from models.profile import UserProfile
from models.user import User

_TEST_USER_ID = uuid.uuid4()


def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: User(id=_TEST_USER_ID)
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
        mock_repo_cls.return_value.create_from_analysis.assert_called_once()
        assert mock_repo_cls.return_value.create_from_analysis.call_args.kwargs["user_id"] == _TEST_USER_ID

        body = resp.json()
        assert body["id"] == str(test_id)
        assert body["sources"]["linkedin_text"] == "Jane Doe, Engineer"
        assert body["sources"]["resume_text"] is None
        assert body["sources"]["github_repositories"] == []


def test_docx_upload_stores_the_source_document(client, tmp_path):
    """A .docx CV must be stored so resume generation can later edit it in place, not just have its text extracted."""
    docx_bytes = _make_docx_bytes(["Jane Doe", "Senior Backend Engineer"])

    with patch("api.v1.profile.fetch_github_profile", new=AsyncMock(return_value=(None, []))), \
         patch("api.v1.profile.fetch_portfolio_text", new=AsyncMock(return_value=None)), \
         patch("api.v1.profile.CandidateProfileAgent") as mock_agent_cls, \
         patch("api.v1.profile.ProfileRepository") as mock_repo_cls, \
         patch("api.v1.profile.LocalResumeStorage") as mock_storage_cls:
        mock_agent_cls.return_value.analyze = AsyncMock(return_value={"name": "Jane Doe"})
        mock_repo_cls.return_value.create_from_analysis = AsyncMock(
            return_value=UserProfile(id=uuid.uuid4(), name="Jane Doe")
        )
        stored_path = str(tmp_path / "source-abc123.docx")
        mock_storage_cls.return_value.save.return_value = stored_path

        resp = client.post(
            "/v1/profile/import",
            files={"file": ("resume.docx", docx_bytes,
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert resp.status_code == 200
        mock_storage_cls.return_value.save.assert_called_once()
        saved_bytes = mock_storage_cls.return_value.save.call_args.args[0]
        assert saved_bytes == docx_bytes

        call_kwargs = mock_repo_cls.return_value.create_from_analysis.call_args.kwargs
        assert call_kwargs["source_document_path"] == stored_path
        assert call_kwargs["source_document_format"] == "docx"


def test_rejects_unsupported_file_type(client):
    with patch("api.v1.profile.CandidateProfileAgent") as mock_agent_cls:
        mock_agent_cls.return_value.analyze = AsyncMock()

        resp = client.post(
            "/v1/profile/import",
            files={"file": ("resume.txt", b"plain text resume", "text/plain")},
        )

        assert resp.status_code == 400
        mock_agent_cls.return_value.analyze.assert_not_called()


def test_requires_authentication():
    """Without a valid bearer token, the endpoint must 401 before touching any source."""
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    unauthenticated_client = TestClient(app)

    resp = unauthenticated_client.post(
        "/v1/profile/import",
        data={"linkedin_url": "https://linkedin.com/in/jane", "linkedin_text": "Jane Doe, Engineer"},
    )

    assert resp.status_code == 401


def test_rejects_malformed_portfolio_url(client):
    """A malformed portfolio_url must 422 before any fetch or agent call."""
    with patch("api.v1.profile.fetch_github_profile", new=AsyncMock(return_value=(None, []))), \
         patch("api.v1.profile.fetch_portfolio_text", new=AsyncMock()) as mock_fetch_portfolio, \
         patch("api.v1.profile.CandidateProfileAgent") as mock_agent_cls:
        mock_agent_cls.return_value.analyze = AsyncMock()

        resp = client.post(
            "/v1/profile/import",
            data={"portfolio_url": "not-a-url"},
        )

        assert resp.status_code == 422
        mock_fetch_portfolio.assert_not_called()
        mock_agent_cls.return_value.analyze.assert_not_called()
