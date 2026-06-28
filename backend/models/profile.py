from datetime import datetime

from sqlalchemy import Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PrimaryKeyMixin


class UserProfile(Base, PrimaryKeyMixin):
    """
    Phase 2 — User Profile Ingestion.

    Single record representing everything we know about the candidate, built by
    ingesting their resume PDF, LinkedIn, GitHub, and optional portfolio URL.

    Unified profile shape:
        {
            "name": str,
            "skills": [str],
            "projects": [{ "name", "description", "url", "tech" }],
            "experience": [{ "title", "company", "start", "end", "bullets" }],
            "education": [{ "institution", "degree", "year" }],
            "links": { "linkedin", "github", "portfolio", ... }
        }

    All source data is stored as JSONB so the ingestion agents can write their
    output directly without a rigid relational schema at this stage. Individual
    tables (WorkExperience, Skill, etc.) are introduced only when Phase 4+
    requires querying across profiles.
    """
    __tablename__ = "user_profiles"

    # --- Identity (no User FK until auth is introduced) ---
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Ingestion sources ---
    resume_pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)   # S3 URL of uploaded PDF
    linkedin_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Extracted / unified profile data (mirrors Phase 2 output schema) ---
    skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)       # [str]
    experience: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [{ title, company, ... }]
    education: Mapped[list | None] = mapped_column(JSONB, nullable=True)    # [{ institution, degree, ... }]
    projects: Mapped[list | None] = mapped_column(JSONB, nullable=True)     # [{ name, description, ... }]
    links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)        # { linkedin, github, ... }

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Populated in Phase 3
    resume_versions: Mapped[list["ResumeVersion"]] = relationship(  # type: ignore[name-defined]
        "ResumeVersion", back_populates="profile"
    )
