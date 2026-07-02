import uuid
from datetime import datetime

from sqlalchemy import Text, DateTime, Numeric, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, PrimaryKeyMixin


class ResumeVersion(Base, PrimaryKeyMixin):
    """
    Phase 3 — Resume Optimiser output.

    Produced when the AI combines a UserProfile + Job analysis and generates
    an optimised resume. Immutable once created — each optimisation run
    produces a new row, so the full generation history is preserved.

    content holds the structured resume ready for PDF rendering:
        {
            "summary": str,
            "skills": [str],
            "experience": [{ "title", "company", "start", "end", "bullets": [str] }],
            "education": [{ "institution", "degree", "year" }],
            "projects": [{ "name", "description", "tech" }]
        }

    rendered_file_url/rendered_file_format are populated by the render worker
    after generation — format is "pdf" (generic template) or "docx" (the
    candidate's original file, edited in place).
    """
    __tablename__ = "resume_versions"

    user_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_profiles.id"), nullable=False, index=True
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jobs.id"), nullable=False, index=True
    )

    # Structured content produced by the CV Optimisation Agent
    content: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Keyword match report (job skills/technologies/keywords vs. profile), set by ResumeGenerationAgent
    matched_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [str]
    missing_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)  # [str]

    # ATS keyword match score (0–100), set by ATS Optimisation Agent
    ats_score: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)

    # Set by the render worker once the file is ready. format is "pdf" (built
    # from templates/resume.html) or "docx" (the candidate's original file,
    # edited in place — see docx_resume_renderer.py) so the download endpoint
    # knows which media type/extension to serve.
    rendered_file_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_file_format: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    profile: Mapped["UserProfile"] = relationship(  # type: ignore[name-defined]
        "UserProfile", back_populates="resume_versions"
    )
    job: Mapped["Job"] = relationship(  # type: ignore[name-defined]
        "Job", back_populates="resume_versions"
    )
