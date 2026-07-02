"""
Tests for JobAnalysisAgent.

Each test corresponds to a requirement from the agent spec:
- Extract title, company, experience, skills, technologies,
  responsibilities, qualifications, and ATS keywords.
- Return null for fields that cannot be determined.
- Return empty arrays for list fields with no data.
- Accept an optional source URL without sending it to the model.
- Use JSON response mode and temperature=0 for deterministic output.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.job_analysis_agent import JobAnalysisAgent
from services.llm_output import LLMOutputError


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
    """Patches genai in the agent module and yields the mock client.

    aio.models.generate_content is pre-configured as an AsyncMock because
    JobAnalysisAgent.analyze() now awaits it.
    """
    with patch("services.job_analysis_agent.genai") as patched:
        mock_client = MagicMock()
        patched.Client.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock()
        yield mock_client


# ---------------------------------------------------------------------------
# Field extraction tests
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_extracts_title_and_company(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("Senior Software Engineer at Acme Corp...")

    assert result["title"] == "Senior Software Engineer"
    assert result["company"] == "Acme Corp"


@pytest.mark.anyio
async def test_extracts_experience_level(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("...requires 5+ years...")

    assert result["experience"] == "5+ years of backend experience"


@pytest.mark.anyio
async def test_extracts_skills(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("...Python, Django required...")

    assert "Python" in result["skills"]
    assert "Django" in result["skills"]


@pytest.mark.anyio
async def test_extracts_technologies(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("...Docker, Kubernetes...")

    assert "Docker" in result["technologies"]
    assert "Kubernetes" in result["technologies"]


@pytest.mark.anyio
async def test_extracts_responsibilities(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("...Design and implement scalable microservices...")

    assert len(result["responsibilities"]) == 3
    assert "Design and implement scalable microservices" in result["responsibilities"]


@pytest.mark.anyio
async def test_extracts_qualifications(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("...Bachelor's degree required...")

    assert any("Bachelor" in q for q in result["qualifications"])


@pytest.mark.anyio
async def test_extracts_ats_keywords(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    result = await JobAnalysisAgent().analyze("...backend API microservices...")

    assert "microservices" in result["keywords"]
    assert "backend" in result["keywords"]


# ---------------------------------------------------------------------------
# Null / empty-array handling
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_returns_null_for_undetermined_string_fields(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_SPARSE_ANALYSIS)

    result = await JobAnalysisAgent().analyze("We are hiring! Apply now.")

    assert result["title"] is None
    assert result["company"] is None
    assert result["experience"] is None


@pytest.mark.anyio
async def test_returns_empty_arrays_for_undetermined_list_fields(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_SPARSE_ANALYSIS)

    result = await JobAnalysisAgent().analyze("We are hiring! Apply now.")

    assert result["skills"] == []
    assert result["technologies"] == []
    assert result["responsibilities"] == []
    assert result["qualifications"] == []
    assert result["keywords"] == []


# ---------------------------------------------------------------------------
# Input construction
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_url_is_not_sent_to_model(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)
    url = "https://jobs.example.com/12345"

    await JobAnalysisAgent().analyze(raw_text="Job posting text", url=url)

    contents = mock_genai.aio.models.generate_content.call_args.kwargs["contents"]
    assert contents == "Job posting text"


@pytest.mark.anyio
async def test_omits_url_prefix_when_not_provided(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    await JobAnalysisAgent().analyze(raw_text="Job posting text")

    contents = mock_genai.aio.models.generate_content.call_args.kwargs["contents"]
    assert contents == "Job posting text"


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_uses_json_response_mode(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    await JobAnalysisAgent().analyze("Any text")

    config = mock_genai.aio.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"


@pytest.mark.anyio
async def test_uses_zero_temperature_for_determinism(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_FULL_ANALYSIS)

    await JobAnalysisAgent().analyze("Any text")

    config = mock_genai.aio.models.generate_content.call_args.kwargs["config"]
    assert config.temperature == 0


# ---------------------------------------------------------------------------
# Invalid LLM output
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_raises_llm_output_error_on_invalid_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = MagicMock(text="not json")

    with pytest.raises(LLMOutputError):
        await JobAnalysisAgent().analyze("Any text")


@pytest.mark.anyio
async def test_raises_llm_output_error_on_wrong_shaped_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response({"skills": "not-a-list"})

    with pytest.raises(LLMOutputError):
        await JobAnalysisAgent().analyze("Any text")
