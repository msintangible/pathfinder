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


def test_matches_a_keyword_only_tagged_on_one_work_experience_entry():
    """A skill tagged on a specific job, but never rolled up into technical_skills, must still count."""
    profile = {
        "technical_skills": ["Python"],
        "work_experience": [{"title": "Engineer", "technologies": ["Kubernetes"]}],
    }
    job = {"skills": ["Python", "Kubernetes"]}

    report = match_keywords(profile, job)

    assert set(report.matched) == {"Python", "Kubernetes"}
    assert report.missing == []


def test_matches_a_keyword_only_in_project_skills_demonstrated():
    profile = {"projects": [{"name": "Side project", "skills_demonstrated": ["Terraform"]}]}
    job = {"technologies": ["Terraform"]}

    report = match_keywords(profile, job)

    assert report.matched == ["Terraform"]
    assert report.missing == []


def test_matches_a_keyword_only_in_github_repository_languages():
    profile = {"github_repositories": [{"name": "repo", "languages": ["Go"]}]}
    job = {"keywords": ["Go"]}

    report = match_keywords(profile, job)

    assert report.matched == ["Go"]
    assert report.missing == []


def test_nested_sections_missing_or_empty_are_handled_gracefully():
    profile = {"work_experience": [{"title": "Engineer"}], "projects": None}
    job = {"skills": ["Rust"]}

    report = match_keywords(profile, job)

    assert report.matched == []
    assert report.missing == ["Rust"]
