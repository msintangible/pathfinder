from datetime import datetime

from sqlalchemy import Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, PrimaryKeyMixin


class User(Base, PrimaryKeyMixin):
    """
    An anonymous or registered account. Created anonymously on first extension
    use via POST /v1/auth/anonymous — no email/password required.

    email/hashed_password are nullable and unused until a real login flow is
    added: upgrading an anonymous account later just means setting these two
    columns on this same row (so its existing profiles/resumes carry over),
    not a schema migration on a populated table.
    """
    __tablename__ = "users"

    email: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    hashed_password: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
