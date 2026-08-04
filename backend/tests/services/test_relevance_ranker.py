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

    assert ranked.profile["work_experience"][0]["title"] == "Relevant Role"


def test_ranks_projects_by_skills_demonstrated():
    profile = {
        "projects": [
            {"name": "Low relevance", "skills_demonstrated": []},
            {"name": "High relevance", "skills_demonstrated": ["AWS"]},
        ]
    }
    report = KeywordReport(matched=["AWS"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked.profile["projects"][0]["name"] == "High relevance"


def test_caps_github_repositories_to_max_four():
    profile = {"github_repositories": [{"name": f"repo-{i}"} for i in range(10)]}
    report = KeywordReport(matched=[], missing=[])

    ranked = rank_profile(profile, report)

    assert len(ranked.profile["github_repositories"]) == 4


def test_caps_projects_to_max_three():
    profile = {"projects": [{"name": f"project-{i}"} for i in range(10)]}
    report = KeywordReport(matched=[], missing=[])

    ranked = rank_profile(profile, report)

    assert len(ranked.profile["projects"]) == 3


def test_missing_sections_become_empty_lists():
    ranked = rank_profile({}, KeywordReport(matched=[], missing=[]))

    assert ranked.profile["work_experience"] == []
    assert ranked.profile["projects"] == []
    assert ranked.profile["github_repositories"] == []


def test_preserves_other_profile_fields_untouched():
    profile = {"name": "Jane Doe", "work_experience": []}

    ranked = rank_profile(profile, KeywordReport(matched=[], missing=[]))

    assert ranked.profile["name"] == "Jane Doe"


# ---------------------------------------------------------------------------
# source_indices
# ---------------------------------------------------------------------------

def test_source_indices_map_ranked_entries_back_to_original_positions():
    profile = {
        "work_experience": [
            {"title": "Unrelated Role", "technologies": ["COBOL"]},
            {"title": "Relevant Role", "technologies": ["Python", "Docker"]},
        ]
    }
    report = KeywordReport(matched=["Python", "Docker"], missing=[])

    ranked = rank_profile(profile, report)

    # "Relevant Role" (original index 1) now sits first after ranking.
    assert ranked.source_indices["work_experience"] == [1, 0]


def test_source_indices_reflect_truncation_by_cap():
    profile = {"github_repositories": [{"name": f"repo-{i}"} for i in range(10)]}
    report = KeywordReport(matched=[], missing=[])

    ranked = rank_profile(profile, report)

    assert len(ranked.source_indices["github_repositories"]) == 4
    assert ranked.source_indices["github_repositories"] == list(range(4))


def test_source_indices_empty_for_missing_sections():
    ranked = rank_profile({}, KeywordReport(matched=[], missing=[]))

    assert ranked.source_indices["work_experience"] == []
    assert ranked.source_indices["projects"] == []
    assert ranked.source_indices["github_repositories"] == []


# ---------------------------------------------------------------------------
# ranking_reasons
# ---------------------------------------------------------------------------

def test_ranking_reasons_lists_the_actual_matched_terms():
    profile = {
        "projects": [
            {"name": "Low relevance", "technologies": ["COBOL"]},
            {"name": "High relevance", "technologies": ["Azure", "Docker", "FastAPI"]},
        ]
    }
    report = KeywordReport(matched=["Azure", "Docker", "FastAPI", "Python"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked.ranking_reasons["projects"][0] == ["Azure", "Docker", "FastAPI"]


def test_ranking_reasons_empty_for_a_tie_broken_entry():
    profile = {"projects": [{"name": "No overlap", "technologies": ["COBOL"]}]}
    report = KeywordReport(matched=["Python"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked.ranking_reasons["projects"][0] == []


def test_ranking_reasons_deduplicates_terms_across_fields():
    profile = {
        "projects": [
            {"name": "A", "technologies": ["AWS"], "skills_demonstrated": ["aws", "Terraform"]},
        ]
    }
    report = KeywordReport(matched=["AWS", "Terraform"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked.ranking_reasons["projects"][0] == ["AWS", "Terraform"]


def test_ranking_reasons_empty_for_missing_sections():
    ranked = rank_profile({}, KeywordReport(matched=[], missing=[]))

    assert ranked.ranking_reasons["work_experience"] == []
    assert ranked.ranking_reasons["projects"] == []
    assert ranked.ranking_reasons["github_repositories"] == []


def test_source_indices_stay_aligned_with_ranked_profile_entries():
    profile = {
        "projects": [
            {"name": "Alpha", "skills_demonstrated": []},
            {"name": "Beta", "skills_demonstrated": ["AWS"]},
            {"name": "Gamma", "skills_demonstrated": ["AWS", "Docker"]},
        ]
    }
    report = KeywordReport(matched=["AWS", "Docker"], missing=[])

    ranked = rank_profile(profile, report)

    original_projects = profile["projects"]
    for position, original_index in enumerate(ranked.source_indices["projects"]):
        assert ranked.profile["projects"][position] == original_projects[original_index]
