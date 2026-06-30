"""
Tests for CandidateProfileAgent.

Each test corresponds to a requirement from the agent spec:
- Extract name, headline, summary, skills, work experience, education,
  projects, GitHub repositories, certifications, and links.
- Return null for string fields that cannot be determined.
- Return empty arrays for list fields with no data.
- Include only sections that have data in the content sent to the model.
- Format GitHub repositories with name, languages, description, and readme.
- Use JSON response mode and temperature=0 for deterministic output.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.candidate_profile_agent import CandidateProfileAgent
from schemas.profile import CandidateProfileInput, RawGitHubRepo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


_FULL_PROFILE = {
    "name": "Jane Doe",
    "headline": "Senior Software Engineer",
    "summary": "Experienced backend engineer specialising in Python and distributed systems.",
    "technical_skills": ["Python", "FastAPI", "PostgreSQL", "Redis"],
    "soft_skills": ["communication", "leadership", "mentoring"],
    "programming_languages": ["Python", "JavaScript", "TypeScript"],
    "frameworks": ["FastAPI", "Django", "React"],
    "libraries": ["Pydantic", "SQLAlchemy"],
    "databases": ["PostgreSQL", "Redis"],
    "cloud_platforms": ["AWS", "GCP"],
    "devops_tools": ["Docker", "Kubernetes", "GitHub Actions"],
    "ai_ml_tools": [],
    "development_tools": ["VSCode", "Git"],
    "work_experience": [
        {
            "title": "Senior Software Engineer",
            "company": "Acme Corp",
            "location": "London, UK",
            "start_date": "2021-01",
            "end_date": None,
            "current": True,
            "bullets": [
                "Led migration of monolith to microservices",
                "Reduced API latency by 40%",
            ],
            "technologies": ["Python", "FastAPI", "Docker"],
            "skills_demonstrated": ["system design", "performance optimisation"],
        }
    ],
    "education": [
        {
            "institution": "University of Manchester",
            "degree": "BSc",
            "field": "Computer Science",
            "start_date": "2015-09",
            "end_date": "2018-06",
            "grade": "First Class Honours",
            "achievements": ["Graduated top of class"],
        }
    ],
    "projects": [
        {
            "name": "pathfinder",
            "description": "AI-powered job application assistant",
            "url": "https://github.com/jane/pathfinder",
            "technologies": ["Python", "FastAPI", "React"],
            "skills_demonstrated": ["full-stack development", "AI integration"],
            "notable_achievements": ["500 GitHub stars"],
        }
    ],
    "github_repositories": [
        {
            "name": "pathfinder",
            "description": "AI-powered job application assistant",
            "url": "https://github.com/jane/pathfinder",
            "languages": ["Python", "JavaScript"],
            "frameworks": ["FastAPI", "React"],
            "technologies": ["PostgreSQL", "Docker"],
            "purpose": "Job application automation tool",
            "complexity": "high",
            "skills_demonstrated": ["backend development", "AI integration"],
        }
    ],
    "open_source_contributions": ["django/django", "tiangolo/fastapi"],
    "certifications": [
        {"name": "AWS Solutions Architect", "issuer": "Amazon", "date": "2022-03", "url": None}
    ],
    "awards": ["Employee of the Year 2023"],
    "achievements": ["Promoted to Senior Engineer in 18 months"],
    "leadership_experience": ["Led a team of 4 engineers for 2 years"],
    "volunteer_work": ["Mentored junior developers at a local coding bootcamp"],
    "publications": [],
    "links": {
        "linkedin": "https://linkedin.com/in/jane",
        "github": "https://github.com/jane",
    },
}

_SPARSE_PROFILE = {
    "name": None,
    "headline": None,
    "summary": None,
    "technical_skills": [],
    "soft_skills": [],
    "programming_languages": [],
    "frameworks": [],
    "libraries": [],
    "databases": [],
    "cloud_platforms": [],
    "devops_tools": [],
    "ai_ml_tools": [],
    "development_tools": [],
    "work_experience": [],
    "education": [],
    "projects": [],
    "github_repositories": [],
    "open_source_contributions": [],
    "certifications": [],
    "awards": [],
    "achievements": [],
    "leadership_experience": [],
    "volunteer_work": [],
    "publications": [],
    "links": {},
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_genai():
    """Patches genai in the agent module and yields the mock client."""
    with patch("services.candidate_profile_agent.genai") as patched:
        mock_client = MagicMock()
        patched.Client.return_value = mock_client
        yield mock_client


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def test_extracts_name_and_headline(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="Jane Doe..."))

    assert result["name"] == "Jane Doe"
    assert result["headline"] == "Senior Software Engineer"


def test_extracts_summary(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert "Python" in result["summary"]


def test_extracts_programming_languages(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert "Python" in result["programming_languages"]
    assert "TypeScript" in result["programming_languages"]


def test_extracts_work_experience(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert len(result["work_experience"]) == 1
    job = result["work_experience"][0]
    assert job["title"] == "Senior Software Engineer"
    assert job["company"] == "Acme Corp"
    assert job["current"] is True
    assert "Led migration of monolith to microservices" in job["bullets"]


def test_extracts_education(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert len(result["education"]) == 1
    edu = result["education"][0]
    assert edu["institution"] == "University of Manchester"
    assert edu["degree"] == "BSc"
    assert edu["grade"] == "First Class Honours"


def test_extracts_github_repositories(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert len(result["github_repositories"]) == 1
    repo = result["github_repositories"][0]
    assert repo["name"] == "pathfinder"
    assert "Python" in repo["languages"]
    assert repo["complexity"] == "high"


def test_extracts_certifications(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert len(result["certifications"]) == 1
    assert result["certifications"][0]["name"] == "AWS Solutions Architect"
    assert result["certifications"][0]["issuer"] == "Amazon"


def test_extracts_links(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert result["links"]["linkedin"] == "https://linkedin.com/in/jane"
    assert result["links"]["github"] == "https://github.com/jane"


# ---------------------------------------------------------------------------
# Null / empty-array handling
# ---------------------------------------------------------------------------

def test_returns_null_for_undetermined_string_fields(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_SPARSE_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert result["name"] is None
    assert result["headline"] is None
    assert result["summary"] is None


def test_returns_empty_arrays_for_undetermined_list_fields(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_SPARSE_PROFILE)

    result = CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    assert result["programming_languages"] == []
    assert result["work_experience"] == []
    assert result["education"] == []
    assert result["github_repositories"] == []
    assert result["certifications"] == []


# ---------------------------------------------------------------------------
# Content construction
# ---------------------------------------------------------------------------

def test_resume_section_present_in_content(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="Jane Doe, Python Engineer"))

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert "=== RESUME ===" in contents
    assert "Jane Doe, Python Engineer" in contents


def test_linkedin_section_present_in_content(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    CandidateProfileAgent().analyze(
        CandidateProfileInput(linkedin_text="Jane Doe · Senior Engineer at Acme")
    )

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert "=== LINKEDIN PROFILE ===" in contents
    assert "Senior Engineer at Acme" in contents


def test_missing_sources_omitted_from_content(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    # Only resume provided — other sections must not appear.
    CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="Jane Doe..."))

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert "=== LINKEDIN PROFILE ===" not in contents
    assert "=== PORTFOLIO / PERSONAL SITE ===" not in contents
    assert "=== GITHUB REPOSITORIES ===" not in contents


def test_github_repos_formatted_with_name_and_languages(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    CandidateProfileAgent().analyze(
        CandidateProfileInput(
            github_repositories=[
                RawGitHubRepo(
                    name="my-api",
                    languages=["Python", "Go"],
                    description="A REST API",
                    url="https://github.com/jane/my-api",
                )
            ]
        )
    )

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert "=== GITHUB REPOSITORIES ===" in contents
    assert "my-api" in contents
    assert "Python, Go" in contents
    assert "A REST API" in contents


def test_multiple_repos_all_appear_in_content(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    CandidateProfileAgent().analyze(
        CandidateProfileInput(
            github_repositories=[
                RawGitHubRepo(name="repo-one", languages=["Python"]),
                RawGitHubRepo(name="repo-two", languages=["TypeScript"]),
            ]
        )
    )

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert "repo-one" in contents
    assert "repo-two" in contents


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

def test_uses_json_response_mode(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    config = mock_genai.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"


def test_uses_zero_temperature_for_determinism(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_PROFILE)

    CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="..."))

    config = mock_genai.models.generate_content.call_args.kwargs["config"]
    assert config.temperature == 0
