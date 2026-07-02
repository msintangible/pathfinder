"""
Coverage for the anonymous-identity auth flow: POST /v1/auth/anonymous issues
a token, and get_current_user must accept it back (and reject anything else).
Written because this wiring had zero test coverage despite already being
live in router.py.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.v1.auth import router
from core.config import settings
from core.security import create_anonymous_token, get_current_user
from database.session import get_db
from models.user import User


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router, prefix="/v1")

    @app.get("/v1/whoami")
    async def whoami(user: User = Depends(get_current_user)) -> dict:
        return {"user_id": str(user.id)}

    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app)


def test_anonymous_creates_user_and_returns_token(client):
    user_id = uuid.uuid4()
    with patch("api.v1.auth.UserRepository") as mock_repo_cls:
        mock_repo_cls.return_value.create_anonymous = AsyncMock(return_value=User(id=user_id))

        resp = client.post("/v1/auth/anonymous")

        assert resp.status_code == 200
        body = resp.json()
        assert body["token_type"] == "bearer"

        payload = jwt.decode(body["access_token"], settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == str(user_id)


def test_valid_token_resolves_current_user(client):
    user_id = uuid.uuid4()
    token = create_anonymous_token(user_id)

    with patch("core.security.UserRepository") as mock_repo_cls:
        mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=User(id=user_id))

        resp = client.get("/v1/whoami", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json()["user_id"] == str(user_id)


def test_missing_token_returns_401(client):
    resp = client.get("/v1/whoami")

    assert resp.status_code == 401


def test_malformed_token_returns_401(client):
    resp = client.get("/v1/whoami", headers={"Authorization": "Bearer not-a-real-token"})

    assert resp.status_code == 401


def test_expired_token_returns_401(client):
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(days=1)},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    resp = client.get("/v1/whoami", headers={"Authorization": f"Bearer {expired}"})

    assert resp.status_code == 401


def test_valid_token_for_unknown_user_returns_401(client):
    token = create_anonymous_token(uuid.uuid4())

    with patch("core.security.UserRepository") as mock_repo_cls:
        mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)

        resp = client.get("/v1/whoami", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 401
