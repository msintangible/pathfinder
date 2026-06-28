from datetime import datetime

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PrimaryKeyMixin


class Job(Base, PrimaryKeyMixin):
    """
    Phase 1 — Job Analysis.

    Stores the raw job posting and the structured analysis produced by the
    Job Analysis Agent. The hash column deduplicates cross-posted listings
    so the same posting is never analysed twice.

    Analysis output shape:
        {
            "title": str,
            "company": str,
            "skills": [str],
            "technologies": [str],
            "experience": str,
            "responsibilities": [str],
            "qualifications": [str],
            "keywords": [str]
        }
    """
    __tablename__ = "jobs"

    # --- Input ---
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    # SHA-256 of normalised posting text — unique index prevents re-analysis
    posting_text_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    # --- Analysis output (mirrors Phase 1 output schema exactly) ---
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)            # [str]
    technologies: Mapped[list | None] = mapped_column(JSONB, nullable=True)      # [str]
    experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsibilities: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [str]
    qualifications: Mapped[list | None] = mapped_column(JSONB, nullable=True)    # [str]
    keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)          # [str]

    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Populated in Phase 3
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(  # type: ignore[name-defined]
        "ResumeVersion", back_populates="job"
    )
