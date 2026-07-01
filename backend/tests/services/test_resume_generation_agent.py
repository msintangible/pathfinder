"""
Tests for ResumeGenerationAgent.

The agent is a controller, not a single LLM call:
- match_keywords and compute_ats run deterministically (no model call).
- Exactly one Gemini call optimizes the resume content.
- The returned dict matches the documented pipeline output shape.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.resume_generation_agent import _SYSTEM_PROMPT, ResumeGenerationAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


_OPTIMIZED_RESUME = {
    "headline": "Senior Backend Engineer",
    "summary": "Backend engineer with Python and AWS experience.",
    "skills": ["Python", "AWS"],
    "experience": [
        {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "start_date": "2020",
            "end_date": "Present",
            "bullets": ["Built scalable APIs with Python and AWS"],
        }
    ],
    "projects": [],
    "changes_summary": [
        "Emphasized your Python and AWS experience since the job requires both.",
        "Could not address Terraform — no matching experience was found in your profile.",
    ],
}

_PROFILE = {
    "technical_skills": ["Python", "AWS"],
    "work_experience": [
        {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "technologies": ["Python", "AWS"],
        }
    ],
}

_JOB = {"skills": ["Python", "AWS", "Terraform"]}


@pytest.fixture
def mock_genai():
    """Patches genai in the agent module and yields the mock client."""
    with patch("services.resume_generation_agent.genai") as patched:
        mock_client = MagicMock()
        patched.Client.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock()
        yield mock_client


# ---------------------------------------------------------------------------
# Pipeline shape
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_returns_full_pipeline_output_shape(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_OPTIMIZED_RESUME)

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert set(result.keys()) == {"ats_score", "matched_keywords", "missing_keywords", "optimized_resume"}
    assert result["optimized_resume"] == _OPTIMIZED_RESUME


@pytest.mark.anyio
async def test_computes_ats_score_deterministically(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_OPTIMIZED_RESUME)

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    # 2 of 3 job keywords (Python, AWS) are present in the profile.
    assert result["ats_score"] == pytest.approx(66.67)
    assert result["matched_keywords"] == ["Python", "AWS"]
    assert result["missing_keywords"] == ["Terraform"]


@pytest.mark.anyio
async def test_calls_model_exactly_once(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_OPTIMIZED_RESUME)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert mock_genai.aio.models.generate_content.call_count == 1


# ---------------------------------------------------------------------------
# Model input
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_sends_matched_and_missing_keywords_to_model(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_OPTIMIZED_RESUME)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    contents = json.loads(mock_genai.aio.models.generate_content.call_args.kwargs["contents"])
    assert contents["matched_keywords"] == ["Python", "AWS"]
    assert contents["missing_keywords"] == ["Terraform"]
    assert contents["job"] == _JOB


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_uses_flash_lite_model(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_OPTIMIZED_RESUME)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert mock_genai.aio.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-flash-lite"


@pytest.mark.anyio
async def test_uses_json_response_mode_and_zero_temperature(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_OPTIMIZED_RESUME)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    config = mock_genai.aio.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0


def test_prompt_asks_for_changes_summary():
    """Regression guard: a future prompt edit must not silently drop the field the schema expects."""
    assert "changes_summary" in _SYSTEM_PROMPT
