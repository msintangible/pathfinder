"""
Tests for JobAnalysisAgent.

Each test corresponds to a requirement from the agent spec:
- Extract title, company, experience, skills, technologies,
  responsibilities, qualifications, and ATS keywords.
- Return null for fields that cannot be determined.
- Return empty arrays for list fields with no data.
- Prepend the source URL to content when provided.
- Use JSON response mode and temperature=0 for deterministic output.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from services.job_analysis_agent import JobAnalysisAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


_FULL_ANALYSIS = {
    "title": "Senior Software Engineer",
    "company": "Acme Corp",
    "experience": "5+ years of backend experience",
    "skills": ["Python", "Django", "PostgreSQL", "Redis"],
    "technologies": ["Python", "Django", "PostgreSQL", "Redis", "Docker", "Kubernetes"],
    "responsibilities": [
        "Design and implement scalable microservices",
        "Review code and mentor junior engineers",
        "Collaborate with product on technical requirements",
    ],
    "qualifications": [
        "Bachelor's degree in Computer Science or equivalent experience",
        "Strong written and verbal communication skills",
    ],
    "keywords": [
        "Python", "Django", "PostgreSQL", "Redis", "microservices",
        "backend", "API", "scalable",
    ],
}

_SPARSE_ANALYSIS = {
    "title": None,
    "company": None,
    "experience": None,
    "skills": [],
    "technologies": [],
    "responsibilities": [],
    "qualifications": [],
    "keywords": [],
}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_genai():
    """Patches genai in the agent module and yields the mock client."""
    with patch("services.job_analysis_agent.genai") as patched:
        mock_client = MagicMock()
        patched.Client.return_value = mock_client
        yield mock_client


# ---------------------------------------------------------------------------
# Field extraction tests
# ---------------------------------------------------------------------------

def test_extracts_title_and_company(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("Senior Software Engineer at Acme Corp...")

    assert result["title"] == "Senior Software Engineer"
    assert result["company"] == "Acme Corp"


def test_extracts_experience_level(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("...requires 5+ years...")

    assert result["experience"] == "5+ years of backend experience"


def test_extracts_skills(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("...Python, Django required...")

    assert "Python" in result["skills"]
    assert "Django" in result["skills"]


def test_extracts_technologies(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("...Docker, Kubernetes...")

    assert "Docker" in result["technologies"]
    assert "Kubernetes" in result["technologies"]


def test_extracts_responsibilities(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("...Design and implement scalable microservices...")

    assert len(result["responsibilities"]) == 3
    assert "Design and implement scalable microservices" in result["responsibilities"]


def test_extracts_qualifications(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("...Bachelor's degree required...")

    assert any("Bachelor" in q for q in result["qualifications"])


def test_extracts_ats_keywords(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = JobAnalysisAgent().analyze("...backend API microservices...")

    assert "microservices" in result["keywords"]
    assert "backend" in result["keywords"]


# ---------------------------------------------------------------------------
# Null / empty-array handling
# ---------------------------------------------------------------------------

def test_returns_null_for_undetermined_string_fields(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_SPARSE_ANALYSIS)

    result = JobAnalysisAgent().analyze("We are hiring! Apply now.")

    assert result["title"] is None
    assert result["company"] is None
    assert result["experience"] is None


def test_returns_empty_arrays_for_undetermined_list_fields(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_SPARSE_ANALYSIS)

    result = JobAnalysisAgent().analyze("We are hiring! Apply now.")

    assert result["skills"] == []
    assert result["technologies"] == []
    assert result["responsibilities"] == []
    assert result["qualifications"] == []
    assert result["keywords"] == []


# ---------------------------------------------------------------------------
# Input construction
# ---------------------------------------------------------------------------

def test_prepends_url_when_provided(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)
    url = "https://jobs.example.com/12345"

    JobAnalysisAgent().analyze(raw_text="Job posting text", url=url)

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert contents.startswith(f"Source URL: {url}")
    assert "Job posting text" in contents


def test_omits_url_prefix_when_not_provided(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    JobAnalysisAgent().analyze(raw_text="Job posting text")

    contents = mock_genai.models.generate_content.call_args.kwargs["contents"]
    assert contents == "Job posting text"


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

def test_uses_json_response_mode(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    JobAnalysisAgent().analyze("Any text")

    config = mock_genai.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"


def test_uses_zero_temperature_for_determinism(mock_genai):
    mock_genai.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    JobAnalysisAgent().analyze("Any text")

    config = mock_genai.models.generate_content.call_args.kwargs["config"]
    assert config.temperature == 0
