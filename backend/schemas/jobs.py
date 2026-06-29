import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AnalyzeJobRequest(BaseModel):
    raw_text: str = Field(min_length=1)
    url: str | None = None


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
