from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_anonymous_token
from database.session import get_db
from schemas.auth import TokenResponse
from services.repository.user_repository import UserRepository

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/anonymous", response_model=TokenResponse)
async def create_anonymous_session(session: AsyncSession = Depends(get_db)) -> TokenResponse:
    """
    Issue a long-lived anonymous identity — no email/password required.

    Every profile/resume created with the returned token is scoped to it, so
    this is the only thing standing between one install's data and another's.
    """
    user = await UserRepository(session).create_anonymous()
    token = create_anonymous_token(user.id)
    return TokenResponse(access_token=token)
