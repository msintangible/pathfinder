from datetime import date as date_

from sqlalchemy import Date, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class GeminiUsageDaily(Base):
    """
    One row per UTC calendar day, tracking how many Gemini API calls the
    backend has made that day — the in-app half of the Gemini cost-safety
    net (see services/repository/gemini_usage_repository.py for the atomic
    increment-and-check; the Google Cloud Console quota cap is the other,
    external half).
    """
    __tablename__ = "gemini_usage_daily"

    date: Mapped[date_] = mapped_column(Date, primary_key=True)
    call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
