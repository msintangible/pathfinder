"""
Tests for ResumeGenerationAgent.

The agent is a controller, not a single LLM call:
- match_keywords and compute_ats run deterministically (no model call).
- Exactly one Gemini call optimizes the resume content — it returns
  ContentPatch[] keyed by block_id (see synthetic_profile_layout.py), never a
  restructured resume object directly. A deterministic post-step (Patch
  Engine + flattening) reconstructs the OptimizedResume-shaped dict.
- The returned dict matches the documented pipeline output shape.
"""
import io
import json
from unittest.mock import AsyncMock, MagicMock, patch

import docx
import pytest

from services.docx_layout_extractor import extract_docx_layout
from services.llm_output import LLMOutputError
from services.resume_generation_agent import _SYSTEM_PROMPT, ResumeGenerationAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


_PROFILE = {
    "headline": "Backend Engineer",
    "technical_skills": ["Python", "AWS"],
    "work_experience": [
        {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "start_date": "2020",
            "end_date": "Present",
            "bullets": ["Built APIs with Python and AWS"],
            "technologies": ["Python", "AWS"],
        }
    ],
    "projects": [],
}

_JOB = {"skills": ["Python", "AWS", "Terraform"]}

_PATCHES_RESPONSE = {
    "patches": [
        {"block_id": "headline", "new_text": "Senior Backend Engineer"},
        {"block_id": "summary", "new_text": "Backend engineer with Python and AWS experience."},
        {"block_id": "skills", "new_text": "Python, AWS"},
        {"block_id": "work_experience[0].bullets[0]", "new_text": "Built scalable APIs with Python and AWS"},
        {
            "block_id": "changes_summary",
            "new_text": "Emphasized your Python and AWS experience since the job requires both.\n"
                         "Could not address Terraform — no matching experience was found in your profile.",
        },
    ]
}

_EXPECTED_OPTIMIZED_RESUME = {
    "name": None,
    "email": None,
    "phone": None,
    "headline": "Senior Backend Engineer",
    "summary": "Backend engineer with Python and AWS experience.",
    "links": {},
    "skills": ["Python", "AWS"],
    "skill_groups": [{"label": "Technical", "items": ["Python", "AWS"]}],
    "experience": [
        {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "location": None,
            "start_date": "2020",
            "end_date": "Present",
            "bullets": ["Built scalable APIs with Python and AWS"],
        }
    ],
    "projects": [],
    "education": [],
    "certifications": [],
    "awards": [],
    "leadership": [],
    "volunteering": [],
    "publications": [],
    "interests": [],
    "references": [],
    "changes_summary": [
        "Emphasized your Python and AWS experience since the job requires both.",
        "Could not address Terraform — no matching experience was found in your profile.",
    ],
}


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
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert set(result.keys()) == {
        "ats_score", "matched_keywords", "missing_keywords", "added_keywords", "optimized_resume",
        "patches", "render_layout", "layout_preserved",
    }
    assert result["optimized_resume"] == _EXPECTED_OPTIMIZED_RESUME
    assert result["patches"] == _PATCHES_RESPONSE["patches"]
    assert result["render_layout"] is None  # no layout_document was given
    assert result["layout_preserved"] is False


@pytest.mark.anyio
async def test_computes_ats_score_deterministically(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    # 2 of 3 job keywords (Python, AWS) are present in the profile.
    assert result["ats_score"] == pytest.approx(66.67)
    assert result["matched_keywords"] == ["Python", "AWS"]
    assert result["missing_keywords"] == ["Terraform"]


@pytest.mark.anyio
async def test_calls_model_exactly_once(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert mock_genai.aio.models.generate_content.call_count == 1


# ---------------------------------------------------------------------------
# Resilience — patches referencing unknown/missing block_ids
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_unknown_block_id_in_response_is_ignored_not_raised(mock_genai):
    response = {"patches": [*_PATCHES_RESPONSE["patches"], {"block_id": "not_a_real_block", "new_text": "ghost"}]}
    mock_genai.aio.models.generate_content.return_value = _make_response(response)

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert result["optimized_resume"] == _EXPECTED_OPTIMIZED_RESUME


@pytest.mark.anyio
async def test_missing_patch_for_a_block_keeps_its_original_placeholder_text(mock_genai):
    # The model never patches "headline" at all.
    patches = [p for p in _PATCHES_RESPONSE["patches"] if p["block_id"] != "headline"]
    mock_genai.aio.models.generate_content.return_value = _make_response({"patches": patches})

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert result["optimized_resume"]["headline"] == "Backend Engineer"  # original profile value, untouched


# ---------------------------------------------------------------------------
# Model input
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_sends_matched_and_missing_keywords_to_model(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    contents = json.loads(mock_genai.aio.models.generate_content.call_args.kwargs["contents"])
    assert contents["matched_keywords"] == ["Python", "AWS"]
    assert contents["missing_keywords"] == ["Terraform"]
    assert contents["job"] == _JOB


@pytest.mark.anyio
async def test_sends_editable_blocks_with_block_ids_and_placeholder_text(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    contents = json.loads(mock_genai.aio.models.generate_content.call_args.kwargs["contents"])
    editable_blocks = {block["block_id"]: block["text"] for block in contents["editable_blocks"]}
    assert editable_blocks["headline"] == "Backend Engineer"
    assert editable_blocks["work_experience[0].bullets[0]"] == "Built APIs with Python and AWS"
    assert editable_blocks["skills"] == ""  # blank canvas, synthesized fresh


@pytest.mark.anyio
async def test_sends_full_candidate_profile_as_context(mock_genai):
    """The model must still see the whole ranked profile (all skill
    categories, full entries) even though it can now only ever return
    wording changes through editable_blocks."""
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    contents = json.loads(mock_genai.aio.models.generate_content.call_args.kwargs["contents"])
    assert contents["candidate_profile"]["technical_skills"] == ["Python", "AWS"]


# ---------------------------------------------------------------------------
# layout_document — real in-place rendering via profile_layout_correlator.py
# ---------------------------------------------------------------------------

def _make_docx_bytes(paragraphs: list[str]) -> bytes:
    document = docx.Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_docx_bytes_with_styles(paragraphs: list[tuple[str, str | None]]) -> bytes:
    document = docx.Document()
    for text, style_name in paragraphs:
        document.add_paragraph(text, style=style_name)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.mark.anyio
async def test_confident_correlation_produces_a_patched_real_layout(mock_genai):
    # The real document's text closely matches the profile fields it was
    # extracted from, so correlation should confidently find every block.
    docx_bytes = _make_docx_bytes([
        "Backend Engineer",
        "Built APIs with Python and AWS",
    ])
    layout_document = extract_docx_layout(docx_bytes).model_dump()
    profile = {
        "headline": "Backend Engineer",
        "work_experience": [{"bullets": ["Built APIs with Python and AWS"]}],
    }
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "patches": [
            {"block_id": "headline", "new_text": "Senior Backend Engineer"},
            {"block_id": "summary", "new_text": ""},
            {"block_id": "skills", "new_text": ""},
            {"block_id": "work_experience[0].bullets[0]", "new_text": "Built scalable APIs with Python and AWS"},
            {"block_id": "changes_summary", "new_text": ""},
        ]
    })

    result = await ResumeGenerationAgent().generate(profile, _JOB, layout_document=layout_document)

    assert result["layout_preserved"] is True
    real_blocks = {
        block["block_id"]: block["text"]
        for section in result["render_layout"]["sections"]
        for block in section["blocks"]
    }
    assert real_blocks["paragraph[0]"] == "Senior Backend Engineer"
    assert real_blocks["paragraph[1]"] == "Built scalable APIs with Python and AWS"


@pytest.mark.anyio
async def test_skills_patch_is_distributed_across_overflow_blocks(mock_genai):
    # A multi-line skills section: instead of writing the whole list to the
    # first line and blanking the rest, each line gets its own roughly-even
    # share so no single line has to fit what used to span several.
    docx_bytes = _make_docx_bytes_with_styles([
        ("Backend Engineer", None),
        ("Skills", "Heading 1"),
        ("Python", None),
        ("PostgreSQL", None),
        ("Built APIs with Python and AWS", None),
    ])
    layout_document = extract_docx_layout(docx_bytes).model_dump()
    profile = {
        "headline": "Backend Engineer",
        "work_experience": [{"bullets": ["Built APIs with Python and AWS"]}],
    }
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "patches": [
            {"block_id": "headline", "new_text": "Senior Backend Engineer"},
            {"block_id": "skills", "new_text": "Python, PostgreSQL, Docker"},
            {"block_id": "work_experience[0].bullets[0]", "new_text": "Built scalable APIs with Python and AWS"},
        ]
    })

    result = await ResumeGenerationAgent().generate(profile, _JOB, layout_document=layout_document)

    real_blocks = {
        block["block_id"]: block["text"]
        for section in result["render_layout"]["sections"]
        for block in section["blocks"]
    }
    assert real_blocks["paragraph[2]"] == "Python, PostgreSQL"
    assert real_blocks["paragraph[3]"] == "Docker"


@pytest.mark.anyio
async def test_skills_patch_distributed_across_three_blocks_loses_no_items(mock_genai):
    # Mirrors a real "Technical Skills" section: heading + 3 category lines.
    # Every item from the LLM's compiled list must land in exactly one
    # block, with no item dropped or duplicated across the split.
    docx_bytes = _make_docx_bytes_with_styles([
        ("Backend Engineer", None),
        ("Skills", "Heading 1"),
        ("Python", None),
        ("PostgreSQL", None),
        ("Docker", None),
        ("Built APIs with Python and AWS", None),
    ])
    layout_document = extract_docx_layout(docx_bytes).model_dump()
    profile = {
        "headline": "Backend Engineer",
        "work_experience": [{"bullets": ["Built APIs with Python and AWS"]}],
    }
    skills_items = ["Python", "Java", "SQL", "HTML5", "CSS", "JavaScript", "TypeScript"]
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "patches": [
            {"block_id": "headline", "new_text": "Senior Backend Engineer"},
            {"block_id": "skills", "new_text": ", ".join(skills_items)},
            {"block_id": "work_experience[0].bullets[0]", "new_text": "Built scalable APIs with Python and AWS"},
        ]
    })

    result = await ResumeGenerationAgent().generate(profile, _JOB, layout_document=layout_document)

    real_blocks = {
        block["block_id"]: block["text"]
        for section in result["render_layout"]["sections"]
        for block in section["blocks"]
    }
    skills_block_ids = ["paragraph[2]", "paragraph[3]", "paragraph[4]"]
    chunks = [real_blocks[block_id] for block_id in skills_block_ids]
    assert all(chunk for chunk in chunks)  # every block got a non-empty share
    recombined = [item.strip() for chunk in chunks for item in chunk.split(",")]
    assert recombined == skills_items


@pytest.mark.anyio
async def test_single_block_skills_section_gets_the_full_list_unsplit(mock_genai):
    docx_bytes = _make_docx_bytes_with_styles([
        ("Backend Engineer", None),
        ("Skills", "Heading 1"),
        ("Python", None),
        ("Built APIs with Python and AWS", None),
    ])
    layout_document = extract_docx_layout(docx_bytes).model_dump()
    profile = {
        "headline": "Backend Engineer",
        "work_experience": [{"bullets": ["Built APIs with Python and AWS"]}],
    }
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "patches": [
            {"block_id": "headline", "new_text": "Senior Backend Engineer"},
            {"block_id": "skills", "new_text": "Python, PostgreSQL, Docker"},
            {"block_id": "work_experience[0].bullets[0]", "new_text": "Built scalable APIs with Python and AWS"},
        ]
    })

    result = await ResumeGenerationAgent().generate(profile, _JOB, layout_document=layout_document)

    real_blocks = {
        block["block_id"]: block["text"]
        for section in result["render_layout"]["sections"]
        for block in section["blocks"]
    }
    assert real_blocks["paragraph[2]"] == "Python, PostgreSQL, Docker"


@pytest.mark.anyio
async def test_skills_overflow_blocks_are_untouched_without_a_skills_patch(mock_genai):
    # Same multi-line skills section, but the model never emits a "skills"
    # patch — the overflow blocks must be left exactly as-is, not blanked.
    docx_bytes = _make_docx_bytes_with_styles([
        ("Backend Engineer", None),
        ("Skills", "Heading 1"),
        ("Python", None),
        ("PostgreSQL", None),
        ("Built APIs with Python and AWS", None),
    ])
    layout_document = extract_docx_layout(docx_bytes).model_dump()
    profile = {
        "headline": "Backend Engineer",
        "work_experience": [{"bullets": ["Built APIs with Python and AWS"]}],
    }
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "patches": [
            {"block_id": "headline", "new_text": "Senior Backend Engineer"},
            {"block_id": "work_experience[0].bullets[0]", "new_text": "Built scalable APIs with Python and AWS"},
        ]
    })

    result = await ResumeGenerationAgent().generate(profile, _JOB, layout_document=layout_document)

    real_blocks = {
        block["block_id"]: block["text"]
        for section in result["render_layout"]["sections"]
        for block in section["blocks"]
    }
    assert real_blocks["paragraph[2]"] == "Python"
    assert real_blocks["paragraph[3]"] == "PostgreSQL"


@pytest.mark.anyio
async def test_low_confidence_correlation_falls_back_without_a_render_layout(mock_genai):
    # Nothing in this document resembles the profile's fields at all.
    docx_bytes = _make_docx_bytes(["Completely unrelated filler text."])
    layout_document = extract_docx_layout(docx_bytes).model_dump()
    profile = {
        "headline": "Backend Engineer",
        "work_experience": [{"bullets": ["Built APIs with Python and AWS"]}],
    }
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    result = await ResumeGenerationAgent().generate(profile, _JOB, layout_document=layout_document)

    assert result["layout_preserved"] is False
    assert result["render_layout"] is None


@pytest.mark.anyio
async def test_no_layout_document_means_no_render_layout(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    result = await ResumeGenerationAgent().generate(_PROFILE, _JOB, layout_document=None)

    assert result["layout_preserved"] is False
    assert result["render_layout"] is None


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_uses_flash_lite_model(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    assert mock_genai.aio.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-flash-lite"


@pytest.mark.anyio
async def test_uses_json_response_mode_and_zero_temperature(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_PATCHES_RESPONSE)

    await ResumeGenerationAgent().generate(_PROFILE, _JOB)

    config = mock_genai.aio.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0


def test_prompt_asks_for_changes_summary():
    """Regression guard: a future prompt edit must not silently drop the field the schema expects."""
    assert "changes_summary" in _SYSTEM_PROMPT


def test_prompt_gives_length_guidance_for_every_block_type():
    """Regression guard: summary/skills/bullets each render into a fixed-size
    area of the original document, so a future prompt edit must not silently
    drop their length guidance — that's what keeps rendered text from being
    truncated."""
    normalized_prompt = " ".join(_SYSTEM_PROMPT.split())
    assert "roughly the same length" in normalized_prompt  # summary
    assert "compactly" in normalized_prompt  # skills
    assert "15%" in normalized_prompt  # experience bullets


def test_prompt_explains_the_patch_contract():
    """Regression guard: a future prompt edit must not silently drop the
    block_id/patches contract the parser expects. Structural safety (entry
    count/order, title/company/dates) is now enforced by code — see
    test_synthetic_profile_layout.py — rather than by prompt wording, since
    the LLM has no channel to touch those fields at all."""
    assert "block_id" in _SYSTEM_PROMPT
    assert "editable_blocks" in _SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Invalid LLM output
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_raises_llm_output_error_on_invalid_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = MagicMock(text="not json")

    with pytest.raises(LLMOutputError):
        await ResumeGenerationAgent().generate(_PROFILE, _JOB)


@pytest.mark.anyio
async def test_raises_llm_output_error_on_wrong_shaped_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response({"skills": "not-a-list"})

    with pytest.raises(LLMOutputError):
        await ResumeGenerationAgent().generate(_PROFILE, _JOB)
