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
    No upsert key exists yet (no User FK until auth is introduced), so each
    ingestion currently inserts a new row.

    Extracted-data columns mirror schemas.profile.CandidateProfile exactly —
    the output of CandidateProfileAgent — the same way Job mirrors the Job
    Analysis Agent's output.

    All extracted data is stored as JSONB so the ingestion agent can write its
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

    # --- Extracted profile data (mirrors CandidateProfile output schema exactly) ---
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    technical_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)      # [str]
    soft_skills: Mapped[list | None] = mapped_column(JSONB, nullable=True)           # [str]
    programming_languages: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [str]
    frameworks: Mapped[list | None] = mapped_column(JSONB, nullable=True)            # [str]
    libraries: Mapped[list | None] = mapped_column(JSONB, nullable=True)             # [str]
    databases: Mapped[list | None] = mapped_column(JSONB, nullable=True)             # [str]
    cloud_platforms: Mapped[list | None] = mapped_column(JSONB, nullable=True)        # [str]
    devops_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)          # [str]
    ai_ml_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)           # [str]
    development_tools: Mapped[list | None] = mapped_column(JSONB, nullable=True)     # [str]

    work_experience: Mapped[list | None] = mapped_column(JSONB, nullable=True)       # [{ title, company, ... }]
    education: Mapped[list | None] = mapped_column(JSONB, nullable=True)             # [{ institution, degree, ... }]
    projects: Mapped[list | None] = mapped_column(JSONB, nullable=True)              # [{ name, description, ... }]
    github_repositories: Mapped[list | None] = mapped_column(JSONB, nullable=True)   # [{ name, languages, ... }]
    open_source_contributions: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [str]

    certifications: Mapped[list | None] = mapped_column(JSONB, nullable=True)        # [{ name, issuer, ... }]
    awards: Mapped[list | None] = mapped_column(JSONB, nullable=True)                # [str]
    achievements: Mapped[list | None] = mapped_column(JSONB, nullable=True)          # [str]

    leadership_experience: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [str]
    volunteer_work: Mapped[list | None] = mapped_column(JSONB, nullable=True)        # [str]
    publications: Mapped[list | None] = mapped_column(JSONB, nullable=True)          # [str]

    links: Mapped[dict | None] = mapped_column(JSONB, nullable=True)                 # { linkedin, github, ... }

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
