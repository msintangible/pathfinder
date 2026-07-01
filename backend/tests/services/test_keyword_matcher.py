from services.keyword_matcher import match_keywords


def test_matches_case_insensitively():
    profile = {"technical_skills": ["python", "Docker"]}
    job = {"skills": ["Python", "DOCKER"]}

    report = match_keywords(profile, job)

    assert report.matched == ["Python", "DOCKER"]
    assert report.missing == []


def test_reports_missing_keywords():
    profile = {"technical_skills": ["Python"]}
    job = {"skills": ["Python", "Terraform"]}

    report = match_keywords(profile, job)

    assert report.matched == ["Python"]
    assert report.missing == ["Terraform"]


def test_searches_across_all_profile_skill_fields():
    profile = {
        "programming_languages": ["Python"],
        "cloud_platforms": ["AWS"],
        "devops_tools": ["Docker"],
    }
    job = {"technologies": ["Python", "AWS", "Docker"]}

    report = match_keywords(profile, job)

    assert set(report.matched) == {"Python", "AWS", "Docker"}
    assert report.missing == []


def test_dedups_job_terms_across_fields_keeping_first_seen_casing():
    profile = {"technical_skills": ["python"]}
    job = {"skills": ["Python"], "keywords": ["python"]}

    report = match_keywords(profile, job)

    assert report.matched == ["Python"]


def test_handles_missing_fields_gracefully():
    report = match_keywords({}, {})

    assert report.matched == []
    assert report.missing == []
