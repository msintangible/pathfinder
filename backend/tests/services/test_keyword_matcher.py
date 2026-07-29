from services.keyword_matcher import (
    filter_backed_keywords,
    find_added_keywords,
    match_keywords,
    unused_candidate_skills,
)


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


def test_unused_candidate_skills_excludes_skills_the_job_cares_about():
    profile = {"technical_skills": ["Python", "Docker"], "devops_tools": ["Terraform", "Azure DevOps"]}
    job = {"skills": ["Python"]}

    result = unused_candidate_skills(profile, job)

    assert result == ["Docker", "Terraform", "Azure DevOps"]


def test_unused_candidate_skills_is_empty_when_job_covers_everything():
    profile = {"technical_skills": ["Python"]}
    job = {"skills": ["Python"]}

    assert unused_candidate_skills(profile, job) == []


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


# ---------------------------------------------------------------------------
# Paraphrase-aware matching (3+ word keywords) — see _keyword_appears_in
# ---------------------------------------------------------------------------

def test_backs_a_multiword_keyword_when_most_of_its_words_appear_reworded():
    profile = {
        "work_experience": [
            {"bullets": [
                "Managed the full project lifecycle from requirements gathering to deployment and maintenance.",
            ]},
        ],
    }

    backed = filter_backed_keywords(profile, ["Full Lifecycle Development"])

    assert backed == ["Full Lifecycle Development"]


def test_does_not_back_a_multiword_keyword_sharing_only_one_word():
    profile = {"work_experience": [{"bullets": ["Delivered custom websites for 10+ clients."]}]}

    backed = filter_backed_keywords(profile, ["Full Lifecycle Development"])

    assert backed == []


def test_two_word_keyword_requires_an_exact_match_not_a_shared_word():
    """A 2-word category label sharing one common word ("data") isn't real
    evidence — too weak a signal on its own to credit as genuinely backed."""
    profile = {"work_experience": [{"bullets": ["Used Azure SQL for data persistence."]}]}

    backed = filter_backed_keywords(profile, ["Data Science"])

    assert backed == []


def test_find_added_keywords_credits_a_reworded_multiword_keyword():
    optimized_resume = {
        "experience": [{"bullets": ["Owned the full lifecycle of each release, from requirements through deployment."]}],
    }

    added = find_added_keywords(["Full Lifecycle Development"], optimized_resume)

    assert added == ["Full Lifecycle Development"]
