import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.session import get_db
from models.user import User
from services.repository.user_repository import UserRepository

_bearer_scheme = HTTPBearer(auto_error=False)


def create_anonymous_token(user_id: uuid.UUID) -> str:
    """Long-lived token for a self-issued anonymous identity — no login/refresh flow exists yet."""
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_anonymous_token_expire_days)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


async def _user_from_token(token: str, session: AsyncSession) -> User:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return await _user_from_token(credentials.credentials, session)


async def get_current_user_allow_query_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Same as get_current_user, but also accepts ?token=... as a fallback.

    Only used on the resume download route: a plain browser-tab navigation
    (opening a PDF link) can't attach a custom Authorization header, so
    there's no other way to authenticate it. Kept off every other route so
    tokens don't end up in URLs/logs/history more than this one case requires.
    """
    token = credentials.credentials if credentials else request.query_params.get("token")
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    return await _user_from_token(token, session)
