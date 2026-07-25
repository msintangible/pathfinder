from services.keyword_matcher import filter_backed_keywords, find_added_keywords, match_keywords


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


# ---------------------------------------------------------------------------
# find_added_keywords
# ---------------------------------------------------------------------------

def test_finds_a_missing_keyword_woven_into_a_bullet():
    optimized_resume = {
        "experience": [{"bullets": ["Researched AWS Lambda and API Gateway for scalability decisions."]}],
    }

    added = find_added_keywords(["Lambda", "Terraform"], optimized_resume)

    assert added == ["Lambda"]


def test_finds_a_missing_keyword_in_summary_or_skills():
    optimized_resume = {"summary": "Experienced with Kubernetes clusters.", "skills": ["Python", "Docker"]}

    added = find_added_keywords(["Kubernetes", "Docker", "Rust"], optimized_resume)

    assert set(added) == {"Kubernetes", "Docker"}


def test_finds_a_missing_keyword_in_a_project_description_or_technologies():
    optimized_resume = {"projects": [{"description": "Built with Terraform.", "technologies": ["AWS"]}]}

    added = find_added_keywords(["Terraform", "AWS", "GCP"], optimized_resume)

    assert set(added) == {"Terraform", "AWS"}


def test_matching_is_case_insensitive():
    optimized_resume = {"summary": "Experience with kubernetes."}

    added = find_added_keywords(["Kubernetes"], optimized_resume)

    assert added == ["Kubernetes"]


def test_keyword_not_present_anywhere_is_not_added():
    optimized_resume = {"summary": "Backend engineer.", "skills": ["Python"]}

    added = find_added_keywords(["Terraform"], optimized_resume)

    assert added == []


def test_empty_optimized_resume_adds_nothing():
    assert find_added_keywords(["Terraform"], {}) == []


# ---------------------------------------------------------------------------
# filter_backed_keywords
# ---------------------------------------------------------------------------

def test_keeps_a_keyword_backed_by_a_work_experience_bullet():
    profile = {"work_experience": [{"bullets": ["Researched AWS Lambda for scalability decisions."]}]}

    backed = filter_backed_keywords(profile, ["Lambda"])

    assert backed == ["Lambda"]


def test_keeps_a_keyword_backed_by_a_project_technology():
    profile = {"projects": [{"technologies": ["Terraform"]}]}

    backed = filter_backed_keywords(profile, ["Terraform"])

    assert backed == ["Terraform"]


def test_keeps_a_keyword_backed_by_a_github_repo():
    profile = {"github_repositories": [{"description": "A tool built with Kubernetes."}]}

    backed = filter_backed_keywords(profile, ["Kubernetes"])

    assert backed == ["Kubernetes"]


def test_drops_a_keyword_with_no_basis_anywhere_in_the_profile():
    profile = {
        "technical_skills": ["Python"],
        "work_experience": [{"bullets": ["Built REST APIs."]}],
    }

    backed = filter_backed_keywords(profile, ["Rust"])

    assert backed == []


def test_mixed_backed_and_unbacked_keywords():
    profile = {"technical_skills": ["Python"], "projects": [{"description": "Used Docker for deployment."}]}

    backed = filter_backed_keywords(profile, ["Python", "Docker", "Rust"])

    assert set(backed) == {"Python", "Docker"}


def test_matching_is_case_insensitive_for_backing():
    profile = {"technical_skills": ["python"]}

    backed = filter_backed_keywords(profile, ["PYTHON"])

    assert backed == ["PYTHON"]


def test_empty_profile_backs_nothing():
    assert filter_backed_keywords({}, ["Python"]) == []
