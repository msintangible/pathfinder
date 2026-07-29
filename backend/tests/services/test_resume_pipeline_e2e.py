"""
End-to-end regression gate for the resume pipeline: CandidateProfileAgent ->
dedup -> ResumeGenerationAgent -> structural validation -> real PDF render.

Only the two Gemini calls are mocked (no network access in tests) — every
deterministic step in between (dedup, ranking, synthetic layout, patch
engine, flattening, structural validation, page-fitting, and the actual
Jinja2/xhtml2pdf render) runs for real, so this catches regressions that
per-module unit tests can miss when the pieces are wired together wrong.

Covers the specific problems the resume pipeline used to have:
- duplicate work_experience/project entries from imperfect source merging
  (see profile_deduplicator.py)
- literal "&bull;" leaking into rendered text (see resume_renderer.py)
- an ATS keyword woven into wording with no real basis in the profile
  (see keyword_matcher.filter_backed_keywords)
- more than 2 rendered pages (see resume_page_fitter.py)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
import pytest

from schemas.profile import CandidateProfileInput
from services.candidate_profile_agent import CandidateProfileAgent
from services.resume_generation_agent import ResumeGenerationAgent
from services.resume_page_fitter import count_pdf_pages, render_within_page_limit
from services.resume_validator import validate_resume_structure

# The raw LLM extraction result, deliberately containing the exact kind of
# near-duplicate work_experience entry (same job, described slightly
# differently across resume vs. LinkedIn text) that used to slip through to
# the final PDF.
_RAW_EXTRACTED_PROFILE = {
    "name": "Jane Doe",
    "email": "jane@example.com",
    "phone": "+1 555 0100",
    "headline": "Backend Engineer",
    "summary": "Backend engineer who enjoys distributed systems.",
    "technical_skills": ["Python", "Docker"],
    "soft_skills": [],
    "programming_languages": ["Python"],
    "frameworks": ["FastAPI"],
    "libraries": [],
    "databases": [],
    "cloud_platforms": ["AWS"],
    "devops_tools": ["Docker"],
    "ai_ml_tools": [],
    "development_tools": [],
    "work_experience": [
        {
            "title": "Backend Engineer Intern", "company": "Acme Corp",
            "location": "Remote", "start_date": "2024", "end_date": "2024",
            # "Redis" appears only in prose here, never tagged in
            # technologies/skills_demonstrated — exercises the case where
            # match_keywords() calls it "missing" but filter_backed_keywords()
            # still finds real textual basis for it.
            "bullets": ["Built REST APIs with FastAPI and cached responses using Redis"],
            "technologies": ["Python", "FastAPI"],
            "skills_demonstrated": [],
        },
        {
            # Same real job, restated from the LinkedIn source with a
            # differently-formatted location — must collapse into one entry.
            "title": "Backend Engineer Intern", "company": "Acme Corp",
            "location": "Remote, USA", "start_date": "2024", "end_date": "2024",
            "bullets": ["Deployed services with Docker"], "technologies": ["Docker"],
            "skills_demonstrated": [],
        },
    ],
    "education": [],
    "projects": [
        {
            "name": "pathfinder", "description": "AI-powered job application assistant",
            "url": "https://github.com/jane/pathfinder", "technologies": ["Python", "FastAPI"],
            "skills_demonstrated": [], "notable_achievements": ["500 GitHub stars"],
        },
    ],
    "github_repositories": [],
    "open_source_contributions": [],
    "certifications": [],
    "awards": [],
    "achievements": [],
    "leadership_experience": [],
    "volunteer_work": [],
    "publications": [],
    "interests": [],
    "references": [],
    "links": {"linkedin": "https://linkedin.com/in/janedoe", "github": "https://github.com/jane"},
}

_JOB = {
    "skills": ["Python", "FastAPI", "Redis", "Kubernetes"],
}

# The optimization LLM's patches: genuinely weaves in "Kubernetes" wording
# with zero basis anywhere in the profile — the fabrication case Phase 4
# must catch and exclude from added_keywords.
_PATCHES_RESPONSE = {
    "patches": [
        {"block_id": "headline", "new_text": "Backend Engineer"},
        {
            "block_id": "summary",
            "new_text": "Backend engineer experienced with Python, FastAPI, and Kubernetes.",
        },
        {"block_id": "skills", "new_text": "Python, FastAPI, Docker, AWS"},
        {
            "block_id": "work_experience[0].bullets[0]",
            "new_text": "Built REST APIs with FastAPI and cached responses using Redis",
        },
        {"block_id": "work_experience[0].bullets[1]", "new_text": "Deployed services with Docker"},
        {"block_id": "projects[0].description", "new_text": "AI-powered job application assistant built with FastAPI"},
        {"block_id": "projects[0].achievements[0]", "new_text": "500 GitHub stars"},
        {
            "block_id": "changes_summary",
            "new_text": "Emphasized FastAPI since the job requires it.\n"
                         "Could not genuinely support Kubernetes from your real experience.",
        },
    ]
}


def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


def _page_text(pdf_bytes: bytes) -> str:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


@pytest.mark.anyio
async def test_full_pipeline_produces_a_clean_deduped_backed_two_page_resume():
    with patch("services.candidate_profile_agent.genai") as mock_profile_genai:
        mock_profile_genai.Client.return_value.aio.models.generate_content = AsyncMock(
            return_value=_make_response(_RAW_EXTRACTED_PROFILE)
        )
        profile = await CandidateProfileAgent().analyze(CandidateProfileInput(resume_text="...", linkedin_text="..."))

    # --- Phase 2: duplicate work_experience entries collapsed into one ---
    assert len(profile["work_experience"]) == 1
    merged_entry = profile["work_experience"][0]
    assert "Built REST APIs with FastAPI and cached responses using Redis" in merged_entry["bullets"]
    assert "Deployed services with Docker" in merged_entry["bullets"]

    with patch("services.resume_generation_agent.genai") as mock_gen_genai:
        mock_gen_genai.Client.return_value.aio.models.generate_content = AsyncMock(
            return_value=_make_response(_PATCHES_RESPONSE)
        )
        result = await ResumeGenerationAgent().generate(profile, _JOB)

    # --- Phase 4: genuinely-backed addition credited, fabrication excluded ---
    assert "Redis" in result["added_keywords"]
    assert "Kubernetes" not in result["added_keywords"]

    optimized_resume = result["optimized_resume"]

    # --- Phase 3: structural completeness, no duplicates, project cap ---
    assert validate_resume_structure(optimized_resume) == []

    # --- Phase 5: project achievement bullet was independently editable ---
    assert optimized_resume["projects"][0]["bullets"] == [
        "AI-powered job application assistant built with FastAPI",
        "500 GitHub stars",
    ]

    # --- Phase 1 + Phase 3: real render, fits the page budget ---
    pdf_bytes, rendered_resume = render_within_page_limit(optimized_resume)
    assert pdf_bytes[:4] == b"%PDF"
    assert count_pdf_pages(pdf_bytes) <= 2
    assert rendered_resume == optimized_resume  # short resume — nothing needed trimming

    text = _page_text(pdf_bytes)

    # --- Phase 1: no literal HTML entity leaking into rendered text ---
    assert "&bull;" not in text

    # --- Phase 2: only one "Acme Corp" entry actually rendered ---
    assert text.count("Acme Corp") == 1

    # --- Every rendered skill traces back to the real extracted profile ---
    real_skill_terms = {
        term.lower()
        for field in ("technical_skills", "programming_languages", "frameworks", "cloud_platforms", "devops_tools")
        for term in profile[field]
    }
    for skill in optimized_resume["skills"]:
        assert skill.lower() in real_skill_terms, f"{skill!r} has no basis in the extracted profile"
