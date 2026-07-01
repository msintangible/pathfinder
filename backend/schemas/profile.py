"""
Schemas for the Candidate Profile Agent.

CandidateProfileInput  — what the service layer passes to the agent.
CandidateProfile       — the validated output the agent must return.

All downstream agents (resume optimisation, cover letter, job matching,
interview preparation) consume CandidateProfile as their primary knowledge
source, so the output schema is intentionally comprehensive.
"""

import uuid

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

class RawGitHubRepo(BaseModel):
    """Raw repository data collected by the service layer before the agent runs."""
    name: str
    description: str | None = None
    languages: list[str] = []
    topics: list[str] = []
    readme: str | None = None
    url: str | None = None
    stars: int | None = None


class CandidateProfileInput(BaseModel):
    """
    Everything the agent receives. All scraping and parsing is already done.
    The agent only transforms this into a structured CandidateProfile.
    Every field is optional — the agent handles missing sources gracefully.
    """
    resume_text: str | None = None
    linkedin_text: str | None = None
    github_profile: str | None = None
    github_repositories: list[RawGitHubRepo] = []
    portfolio_text: str | None = None


# ---------------------------------------------------------------------------
# Output — nested models
# ---------------------------------------------------------------------------

class WorkExperience(BaseModel):
    title: str | None = None
    company: str | None = None
    location: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    current: bool = False
    bullets: list[str] = []
    technologies: list[str] = []
    skills_demonstrated: list[str] = []


class Education(BaseModel):
    institution: str | None = None
    degree: str | None = None
    field: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    grade: str | None = None
    achievements: list[str] = []


class Project(BaseModel):
    name: str | None = None
    description: str | None = None
    url: str | None = None
    technologies: list[str] = []
    skills_demonstrated: list[str] = []
    notable_achievements: list[str] = []


class AnalyzedRepo(BaseModel):
    """A GitHub repository after the agent has extracted meaning from it."""
    name: str | None = None
    description: str | None = None
    url: str | None = None
    languages: list[str] = []
    frameworks: list[str] = []
    technologies: list[str] = []
    purpose: str | None = None
    complexity: str | None = None
    skills_demonstrated: list[str] = []


class Certification(BaseModel):
    name: str | None = None
    issuer: str | None = None
    date: str | None = None
    url: str | None = None


# ---------------------------------------------------------------------------
# Output — top-level profile
# ---------------------------------------------------------------------------

class CandidateProfile(BaseModel):
    """
    The structured candidate profile returned by CandidateProfileAgent.

    Designed to be the single source of truth for all downstream agents.
    Fields that cannot be determined from the input must be null or [].
    The agent must never invent information.
    """

    # Identity
    name: str | None = None
    headline: str | None = None
    summary: str | None = None

    # Skills — broken out so downstream agents can do precise keyword matching
    technical_skills: list[str] = []
    soft_skills: list[str] = []
    programming_languages: list[str] = []
    frameworks: list[str] = []
    libraries: list[str] = []
    databases: list[str] = []
    cloud_platforms: list[str] = []
    devops_tools: list[str] = []
    ai_ml_tools: list[str] = []
    development_tools: list[str] = []

    # Experience
    work_experience: list[WorkExperience] = []
    education: list[Education] = []
    projects: list[Project] = []
    github_repositories: list[AnalyzedRepo] = []
    open_source_contributions: list[str] = []

    # Credentials
    certifications: list[Certification] = []
    awards: list[str] = []
    achievements: list[str] = []

    # Soft profile
    leadership_experience: list[str] = []
    volunteer_work: list[str] = []
    publications: list[str] = []

    # Links — e.g. {"linkedin": "...", "github": "...", "portfolio": "..."}
    links: dict[str, str] = {}

    # UserProfile stores "no data" as SQL NULL for these fields (see ProfileRepository),
    # so validating straight from the ORM row via from_attributes=True must accept None.
    @field_validator(
        "technical_skills", "soft_skills", "programming_languages", "frameworks",
        "libraries", "databases", "cloud_platforms", "devops_tools", "ai_ml_tools",
        "development_tools", "work_experience", "education", "projects",
        "github_repositories", "open_source_contributions", "certifications",
        "awards", "achievements", "leadership_experience", "volunteer_work",
        "publications",
        mode="before",
    )
    @classmethod
    def _null_to_empty_list(cls, value: list | None) -> list:
        return value if value is not None else []

    @field_validator("links", mode="before")
    @classmethod
    def _null_to_empty_dict(cls, value: dict | None) -> dict:
        return value if value is not None else {}


class ProfileImportResponse(BaseModel):
    # The persisted UserProfile row's id — the client needs this to reference
    # "this profile" in later calls (e.g. resume generation).
    id: uuid.UUID
    profile: CandidateProfile
    # The raw per-source content actually fed to the agent, so the client can
    # show the user what was found in each source (CV, LinkedIn, GitHub, portfolio).
    sources: CandidateProfileInput
