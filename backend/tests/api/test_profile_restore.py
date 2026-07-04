"""
Coverage for POST /v1/profile/restore.

Exists so a stale/deleted user_profiles row (e.g. after a database reset)
doesn't force the user to re-upload their CV and re-run LLM analysis just to
generate a resume again — the client caches its last CandidateProfile and can
hand it straight back for re-persistence.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.profile import router
from core.security import get_current_user
from database.session import get_db
from models.profile import UserProfile
from models.user import User

_TEST_USER_ID = uuid.uuid4()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: User(id=_TEST_USER_ID)
    return TestClient(app)


def test_restore_persists_the_cached_profile_without_calling_the_agent(client):
    with patch("api.v1.profile.CandidateProfileAgent") as mock_agent_cls, \
         patch("api.v1.profile.ProfileRepository") as mock_repo_cls:
        test_id = uuid.uuid4()
        mock_repo_cls.return_value.create_from_analysis = AsyncMock(
            return_value=UserProfile(id=test_id, name="Jane Doe", technical_skills=["Python"])
        )

        resp = client.post(
            "/v1/profile/restore",
            json={"profile": {"name": "Jane Doe", "technical_skills": ["Python"]}},
        )

        assert resp.status_code == 200
        mock_agent_cls.return_value.analyze.assert_not_called()
        mock_repo_cls.return_value.create_from_analysis.assert_called_once()

        call_kwargs = mock_repo_cls.return_value.create_from_analysis.call_args.kwargs
        assert call_kwargs["user_id"] == _TEST_USER_ID
        analysis = mock_repo_cls.return_value.create_from_analysis.call_args.args[0]
        assert analysis["name"] == "Jane Doe"
        assert analysis["technical_skills"] == ["Python"]

        body = resp.json()
        assert body["id"] == str(test_id)
        assert body["profile"]["name"] == "Jane Doe"


def test_restore_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    unauthenticated_client = TestClient(app)

    resp = unauthenticated_client.post("/v1/profile/restore", json={"profile": {"name": "Jane Doe"}})

    assert resp.status_code == 401
