import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def create_anonymous(self) -> User:
        user = User()
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user
