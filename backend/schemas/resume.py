import uuid

from pydantic import BaseModel


class GenerateResumeRequest(BaseModel):
    user_profile_id: uuid.UUID
    job_id: uuid.UUID


class ResumeExperienceEntry(BaseModel):
    title: str | None = None
    company: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    bullets: list[str] = []


class ResumeProjectEntry(BaseModel):
    name: str | None = None
    description: str | None = None
    technologies: list[str] = []


class OptimizedResume(BaseModel):
    headline: str | None = None
    summary: str | None = None
    skills: list[str] = []
    experience: list[ResumeExperienceEntry] = []
    projects: list[ResumeProjectEntry] = []


class ResumeGenerationResponse(BaseModel):
    ats_score: float
    matched_keywords: list[str]
    missing_keywords: list[str]
    optimized_resume: OptimizedResume
    download_url: str
