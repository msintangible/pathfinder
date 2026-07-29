"""
Tests for profile_deduplicator.dedupe_profile.

CandidateProfileAgent's prompt only asks the model to merge duplicate
entries, it doesn't enforce it — these tests cover the deterministic
code-level safety net that runs after every extraction.
"""

from services.profile_deduplicator import dedupe_profile, merge_overlapping_bullets


def _profile(**overrides) -> dict:
    base = {
        "technical_skills": [],
        "work_experience": [],
        "projects": [],
        "education": [],
        "github_repositories": [],
        "certifications": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# work_experience
# ---------------------------------------------------------------------------

def test_merges_exact_duplicate_work_experience():
    profile = _profile(work_experience=[
        {
            "title": "Full Stack Developer Intern", "company": "FluxPro",
            "location": "Letterkenny, Co.Donegal", "start_date": "May 2025", "end_date": "Sep 2025",
            "bullets": ["Built ASP.NET backend features"], "technologies": ["C#"],
        },
        {
            "title": "Full Stack Developer Intern", "company": "FluxPro",
            "location": "Letterkenny, County Donegal, Ireland", "start_date": "May 2025", "end_date": "Sep 2025",
            "bullets": ["Implemented JWT authentication"], "technologies": ["React"],
        },
    ])

    result = dedupe_profile(profile)

    assert len(result["work_experience"]) == 1
    merged = result["work_experience"][0]
    assert merged["title"] == "Full Stack Developer Intern"
    assert "Built ASP.NET backend features" in merged["bullets"]
    assert "Implemented JWT authentication" in merged["bullets"]
    assert set(merged["technologies"]) == {"C#", "React"}


def test_does_not_merge_different_companies_with_same_title():
    profile = _profile(work_experience=[
        {"title": "Software Engineer Intern", "company": "Acme Corp", "bullets": ["a"]},
        {"title": "Software Engineer Intern", "company": "Globex", "bullets": ["b"]},
    ])

    result = dedupe_profile(profile)

    assert len(result["work_experience"]) == 2


def test_does_not_merge_entries_with_no_comparable_key_fields():
    profile = _profile(work_experience=[
        {"title": None, "company": None, "bullets": ["a"]},
        {"title": None, "company": None, "bullets": ["b"]},
    ])

    result = dedupe_profile(profile)

    assert len(result["work_experience"]) == 2


def test_keeps_non_null_field_from_duplicate_when_base_is_missing_it():
    profile = _profile(work_experience=[
        {"title": "Intern", "company": "FluxPro", "location": None, "bullets": []},
        {"title": "Intern", "company": "FluxPro", "location": "Donegal, Ireland", "bullets": []},
    ])

    result = dedupe_profile(profile)

    assert len(result["work_experience"]) == 1
    assert result["work_experience"][0]["location"] == "Donegal, Ireland"


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

def test_merges_duplicate_projects_keeping_longer_description_and_union_of_tech():
    short_desc = "Stock valuation model."
    long_desc = "Developed a stock valuation model using financial ratios and market data."
    profile = _profile(projects=[
        {
            "name": "Stock Valuation & Prediction Model", "description": short_desc,
            "technologies": ["Python", "Pandas", "Matplotlib"],
        },
        {
            "name": "Stock Valuation & Prediction Model", "description": long_desc,
            "technologies": ["Python", "XGBoost", "Streamlit"],
        },
    ])

    result = dedupe_profile(profile)

    assert len(result["projects"]) == 1
    merged = result["projects"][0]
    assert merged["description"] == long_desc
    assert set(merged["technologies"]) == {"Python", "Pandas", "Matplotlib", "XGBoost", "Streamlit"}


def test_does_not_merge_projects_with_different_names():
    profile = _profile(projects=[
        {"name": "Kitchen Copilot", "description": "a"},
        {"name": "InvestIQ", "description": "b"},
    ])

    result = dedupe_profile(profile)

    assert len(result["projects"]) == 2


# ---------------------------------------------------------------------------
# string list fields
# ---------------------------------------------------------------------------

def test_dedupes_string_list_fields_case_insensitively_keeping_first_casing():
    profile = _profile(technical_skills=["Python", "python", "PYTHON", "SQL"])

    result = dedupe_profile(profile)

    assert result["technical_skills"] == ["Python", "SQL"]


def test_string_list_dedup_ignores_blank_entries():
    profile = _profile(technical_skills=["Python", "", None, "Python"])

    result = dedupe_profile(profile)

    assert result["technical_skills"] == ["Python"]


# ---------------------------------------------------------------------------
# education / github_repositories / certifications
# ---------------------------------------------------------------------------

def test_merges_duplicate_education_entries_unioning_achievements():
    profile = _profile(education=[
        {"institution": "Letterkenny Institute of Technology", "degree": "BSc Computer Science",
         "achievements": ["Member of the Programming Society"]},
        {"institution": "Letterkenny Institute of Technology", "degree": "BSc Computer Science",
         "achievements": ["1:1 honours"]},
    ])

    result = dedupe_profile(profile)

    assert len(result["education"]) == 1
    assert set(result["education"][0]["achievements"]) == {"Member of the Programming Society", "1:1 honours"}


def test_merges_duplicate_github_repositories_by_name():
    profile = _profile(github_repositories=[
        {"name": "pathfinder", "languages": ["Python"], "description": "short"},
        {"name": "pathfinder", "languages": ["JavaScript"], "description": "a much longer description here"},
    ])

    result = dedupe_profile(profile)

    assert len(result["github_repositories"]) == 1
    repo = result["github_repositories"][0]
    assert set(repo["languages"]) == {"Python", "JavaScript"}
    assert repo["description"] == "a much longer description here"


def test_merges_duplicate_certifications_by_name_and_issuer():
    profile = _profile(certifications=[
        {"name": "AWS Cloud Quest: Cloud Practitioner", "issuer": "Amazon Web Services (AWS)", "date": None},
        {"name": "AWS Cloud Quest: Cloud Practitioner", "issuer": "Amazon Web Services (AWS)", "date": "Aug 2025"},
    ])

    result = dedupe_profile(profile)

    assert len(result["certifications"]) == 1
    assert result["certifications"][0]["date"] == "Aug 2025"


def test_leaves_empty_profile_untouched():
    result = dedupe_profile(_profile())

    assert result["work_experience"] == []
    assert result["projects"] == []
    assert result["technical_skills"] == []


# ---------------------------------------------------------------------------
# within-entry redundancy (a project/job's own bullets restating each other)
# ---------------------------------------------------------------------------

def test_drops_a_project_achievement_that_just_restates_its_own_description():
    description = (
        "Built an AI-powered meeting intelligence platform that converts live meeting audio into structured "
        "software requirements, business logic, constraints, and ambiguity prompts for engineers. Designed a "
        "real-time architecture using FastAPI WebSockets and ElevenLabs Realtime STT to stream audio with "
        "sub-second transcription latency."
    )
    profile = _profile(projects=[{
        "name": "distill.",
        "description": description,
        "notable_achievements": [
            "Winner (Best Use of ElevenLabs) at HackBelfast 2026.",
            "Converts live meeting audio into structured software requirements, business logic, "
            "constraints, and ambiguity prompts",
            "Engineered a real-time architecture using FastAPI WebSockets and ElevenLabs Realtime STT "
            "for sub-second transcription latency.",
        ],
    }])

    result = dedupe_profile(profile)

    achievements = result["projects"][0]["notable_achievements"]
    assert achievements == ["Winner (Best Use of ElevenLabs) at HackBelfast 2026."]


def test_keeps_a_project_achievement_that_adds_genuinely_new_information():
    profile = _profile(projects=[{
        "name": "InvestIQ",
        "description": "A stock valuation tool using a Random Forest model.",
        "notable_achievements": ["Won first place at the university hackathon out of 40 teams."],
    }])

    result = dedupe_profile(profile)

    assert result["projects"][0]["notable_achievements"] == [
        "Won first place at the university hackathon out of 40 teams."
    ]


def test_drops_a_work_experience_bullet_that_restates_an_earlier_one():
    profile = _profile(work_experience=[{
        "title": "Web Developer", "company": "Freelance",
        "bullets": [
            "Managed the full project lifecycle from requirements gathering to deployment and maintenance, "
            "achieving a 95% client satisfaction rate.",
            "Managed the full project lifecycle from requirements gathering to deployment and maintenance "
            "for repeat business opportunities.",
        ],
    }])

    result = dedupe_profile(profile)

    assert len(result["work_experience"][0]["bullets"]) == 1


def test_merge_overlapping_bullets_drops_a_project_bullet_that_restates_another_post_rewording():
    optimized_resume = {
        "experience": [],
        "projects": [{
            "name": "Stock Valuation Chatbot",
            "bullets": [
                "Trained a Random Forest model to classify stocks as undervalued, fairly valued, or "
                "overvalued using fundamental and technical indicators.",
                "Trained a Random Forest model using fundamental and technical indicators to classify "
                "stocks as undervalued, fairly valued, or overvalued.",
                "Developed a Streamlit frontend for interactive dashboards and user interaction.",
            ],
        }],
    }

    result = merge_overlapping_bullets(optimized_resume)

    assert result["projects"][0]["bullets"] == [
        "Trained a Random Forest model to classify stocks as undervalued, fairly valued, or "
        "overvalued using fundamental and technical indicators.",
        "Developed a Streamlit frontend for interactive dashboards and user interaction.",
    ]


def test_merge_overlapping_bullets_keeps_distinct_experience_bullets():
    optimized_resume = {
        "experience": [{
            "title": "Full Stack Developer Intern",
            "bullets": [
                "Developed ASP.NET (C#) backend and React TypeScript frontend features using Redux.",
                "Integrated secure JWT-based authentication and connected external partner APIs.",
            ],
        }],
        "projects": [],
    }

    result = merge_overlapping_bullets(optimized_resume)

    assert result["experience"][0]["bullets"] == optimized_resume["experience"][0]["bullets"]
