from services.keyword_matcher import KeywordReport
from services.relevance_ranker import rank_profile


def test_ranks_work_experience_by_matched_technology_overlap():
    profile = {
        "work_experience": [
            {"title": "Unrelated Role", "technologies": ["COBOL"]},
            {"title": "Relevant Role", "technologies": ["Python", "Docker"]},
        ]
    }
    report = KeywordReport(matched=["Python", "Docker"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked["work_experience"][0]["title"] == "Relevant Role"


def test_ranks_projects_by_skills_demonstrated():
    profile = {
        "projects": [
            {"name": "Low relevance", "skills_demonstrated": []},
            {"name": "High relevance", "skills_demonstrated": ["AWS"]},
        ]
    }
    report = KeywordReport(matched=["AWS"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked["projects"][0]["name"] == "High relevance"


def test_caps_github_repositories_to_max_four():
    profile = {"github_repositories": [{"name": f"repo-{i}"} for i in range(10)]}
    report = KeywordReport(matched=[], missing=[])

    ranked = rank_profile(profile, report)

    assert len(ranked["github_repositories"]) == 4


def test_missing_sections_become_empty_lists():
    ranked = rank_profile({}, KeywordReport(matched=[], missing=[]))

    assert ranked["work_experience"] == []
    assert ranked["projects"] == []
    assert ranked["github_repositories"] == []


def test_preserves_other_profile_fields_untouched():
    profile = {"name": "Jane Doe", "work_experience": []}

    ranked = rank_profile(profile, KeywordReport(matched=[], missing=[]))

    assert ranked["name"] == "Jane Doe"
