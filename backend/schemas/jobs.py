import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl, field_validator


class AnalyzeJobRequest(BaseModel):
    raw_text: str = Field(min_length=1)
    url: HttpUrl | None = None


class JobAnalysis(BaseModel):
    """Mirrors JobAnalysisAgent's output schema exactly — see its _SYSTEM_PROMPT."""

    title: str | None = None
    company: str | None = None
    experience: str | None = None
    skills: list[str] = []
    technologies: list[str] = []
    responsibilities: list[str] = []
    qualifications: list[str] = []
    keywords: list[str] = []

    # Despite the prompt instructing "unknown arrays: []", Gemini sometimes
    # emits null — same defensive coercion as CandidateProfile.
    @field_validator(
        "skills", "technologies", "responsibilities", "qualifications", "keywords",
        mode="before",
    )
    @classmethod
    def _null_to_empty_list(cls, value: list | None) -> list:
        return value if value is not None else []


class JobResponse(BaseModel):
    id: uuid.UUID
    url: str | None
    title: str | None
    company: str | None
    experience: str | None
    skills: list | None
    technologies: list | None
    responsibilities: list | None
    qualifications: list | None
    keywords: list | None
    analyzed_at: datetime

    model_config = {"from_attributes": True}
