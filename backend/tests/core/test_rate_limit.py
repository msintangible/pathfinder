"""
Coverage for the in-memory per-IP rate limiter (core/rate_limit.py) and its
wiring onto the three cost-abuse-prone endpoints DEPLOYMENT_PLAN.md flags:
POST /v1/auth/anonymous, /v1/profile/import, /v1/resumes/generate.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from api.v1.auth import router as auth_router
from core.rate_limit import _FixedWindowLimiter, default_rate_limit
from database.session import get_db
from models.user import User


def test_allows_requests_up_to_the_limit():
    limiter = _FixedWindowLimiter(limit=2)
    request = Request(scope={"type": "http", "client": ("1.2.3.4", 0)})

    limiter(request)
    limiter(request)  # still within limit, must not raise


def test_blocks_the_request_that_exceeds_the_limit():
    limiter = _FixedWindowLimiter(limit=1)
    request = Request(scope={"type": "http", "client": ("1.2.3.4", 0)})

    limiter(request)
    with pytest.raises(HTTPException) as exc_info:
        limiter(request)

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_tracks_each_client_ip_independently():
    limiter = _FixedWindowLimiter(limit=1)
    request_a = Request(scope={"type": "http", "client": ("1.2.3.4", 0)})
    request_b = Request(scope={"type": "http", "client": ("5.6.7.8", 0)})

    limiter(request_a)
    limiter(request_b)  # different IP, must not raise despite limit=1


@pytest.fixture
def auth_client():
    app = FastAPI()
    app.include_router(auth_router, prefix="/v1")
    app.dependency_overrides[get_db] = lambda: None
    return app, TestClient(app)


def test_anonymous_endpoint_429s_once_the_limit_trips(auth_client):
    app, client = auth_client
    app.dependency_overrides[default_rate_limit] = _FixedWindowLimiter(limit=1)

    with patch("api.v1.auth.UserRepository") as mock_repo_cls:
        mock_repo_cls.return_value.create_anonymous = AsyncMock(return_value=User(id=uuid.uuid4()))

        first = client.post("/v1/auth/anonymous")
        second = client.post("/v1/auth/anonymous")

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Retry-After" in second.headers
