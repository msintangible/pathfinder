"""
Coverage for ProfileRepository.create_from_analysis.

No DB session is actually opened — the AsyncSession is mocked, since this
repository's only real logic is *which* analysis fields end up on the
UserProfile row; add/commit/refresh are SQLAlchemy plumbing already exercised
end-to-end by the API-level import/restore tests.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.repository.profile_repository import ProfileRepository

_USER_ID = uuid.uuid4()


def _mock_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.anyio
async def test_create_from_analysis_persists_phone():
    """Regression test: phone was extracted by CandidateProfileAgent (see
    candidate_profile_agent.py's prompt) but silently dropped here — the
    UserProfile constructor call never read analysis.get("phone")."""
    repo = ProfileRepository(_mock_session())

    profile = await repo.create_from_analysis(
        {"name": "Jane Doe", "phone": "+1 555 0100"}, user_id=_USER_ID,
    )

    assert profile.phone == "+1 555 0100"


@pytest.mark.anyio
async def test_create_from_analysis_handles_missing_phone():
    repo = ProfileRepository(_mock_session())

    profile = await repo.create_from_analysis({"name": "Jane Doe"}, user_id=_USER_ID)

    assert profile.phone is None


@pytest.mark.anyio
async def test_create_from_analysis_persists_explicit_source_urls():
    repo = ProfileRepository(_mock_session())

    profile = await repo.create_from_analysis(
        {"name": "Jane Doe"},
        user_id=_USER_ID,
        linkedin_url="https://linkedin.com/in/jane",
        github_url="https://github.com/jane",
        portfolio_url="https://jane.dev",
    )

    assert profile.linkedin_url == "https://linkedin.com/in/jane"
    assert profile.github_url == "https://github.com/jane"
    assert profile.portfolio_url == "https://jane.dev"


@pytest.mark.anyio
async def test_create_from_analysis_still_maps_email_correctly():
    """Not a regression (email was already mapped correctly) — kept as a
    guard so a future refactor of this function can't silently break it
    alongside the phone fix."""
    repo = ProfileRepository(_mock_session())

    profile = await repo.create_from_analysis(
        {"name": "Jane Doe", "email": "jane@example.com"}, user_id=_USER_ID,
    )

    assert profile.email == "jane@example.com"
