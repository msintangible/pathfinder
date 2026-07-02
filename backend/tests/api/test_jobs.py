"""
Coverage for POST /v1/jobs/analyze's auth requirement.

Jobs are deduped/shared across all users (posting_text_hash), so unlike
profile/resume there's no ownership check here — just that the caller must
be authenticated.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.jobs import router
from core.security import get_current_user
from database.session import get_db
from models.job import Job
from models.user import User


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: User(id=uuid.uuid4())
    return TestClient(app)


def test_requires_authentication():
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    unauthenticated_client = TestClient(app)

    resp = unauthenticated_client.post("/v1/jobs/analyze", json={"raw_text": "We are hiring a backend engineer."})

    assert resp.status_code == 401


def test_analyze_succeeds_when_authenticated(client):
    job_id = uuid.uuid4()
    with patch("api.v1.jobs.JobAnalysisAgent") as mock_agent_cls, \
         patch("api.v1.jobs.JobRepository") as mock_repo_cls:
        mock_agent_cls.return_value.analyze = AsyncMock(return_value={"title": "Backend Engineer"})
        mock_repo_cls.return_value.create_from_analysis = AsyncMock(
            return_value=Job(
                id=job_id,
                raw_text="We are hiring a backend engineer.",
                posting_text_hash="x" * 64,
                title="Backend Engineer",
                analyzed_at=datetime.now(timezone.utc),
            )
        )

        resp = client.post("/v1/jobs/analyze", json={"raw_text": "We are hiring a backend engineer."})

        assert resp.status_code == 200
        assert resp.json()["id"] == str(job_id)
        mock_agent_cls.return_value.analyze.assert_called_once()
