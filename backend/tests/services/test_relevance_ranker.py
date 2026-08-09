from services.keyword_evidence import classify_keyword
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


# ---------------------------------------------------------------------------
# Multi-criteria project ranking (Phase C of the Projects redesign):
# keyword-evidence coverage, technical depth, impact, and category diversity.
# ---------------------------------------------------------------------------

def test_ranks_project_higher_via_semantic_keyword_evidence():
    """A project's real technologies satisfying a semantic-tier job keyword
    (e.g. "relational databases" via "Azure SQL") must credit the project
    even without the literal job phrase anywhere in its own tags — the
    whole point of routing project ranking through the keyword_evidence
    engine instead of literal tag overlap alone."""
    profile = {
        "databases": ["Azure SQL", "SQL Server"],
        "projects": [
            {"name": "No DB experience", "technologies": ["React"]},
            {"name": "Has DB experience", "technologies": ["Azure SQL", "SQL Server"]},
        ],
    }
    evidence = [classify_keyword("relational databases", profile)]
    report = KeywordReport(matched=["relational databases"], missing=[], evidence=evidence)

    ranked = rank_profile(profile, report)

    assert ranked.profile["projects"][0]["name"] == "Has DB experience"
    assert "relational databases" in ranked.ranking_reasons["projects"][0]


def test_ranks_project_higher_for_technical_depth_when_keyword_coverage_ties():
    profile = {
        "projects": [
            {"name": "Shallow", "technologies": ["Python"]},
            {
                "name": "Deep", "technologies": ["Python"],
                "architecture": ["FastAPI WebSocket backend"],
                "responsibilities": ["Backend architecture"],
                "technical_achievements": ["Sub-second latency"],
            },
        ],
    }
    report = KeywordReport(matched=["Python"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked.profile["projects"][0]["name"] == "Deep"


def test_ranks_project_higher_for_measurable_impact_when_otherwise_tied():
    profile = {
        "projects": [
            {"name": "No impact", "technologies": ["Python"]},
            {"name": "Has impact", "technologies": ["Python"], "impact": ["Won 1st place at HackBelfast 2026"]},
        ],
    }
    report = KeywordReport(matched=["Python"], missing=[])

    ranked = rank_profile(profile, report)

    assert ranked.profile["projects"][0]["name"] == "Has impact"


def test_diversifies_project_categories_when_scores_are_close():
    profile = {
        "projects": [
            {"name": "Backend A", "technologies": ["FastAPI", "PostgreSQL"]},
            {"name": "Backend B", "technologies": ["FastAPI"]},
            {"name": "Backend C", "technologies": ["FastAPI"]},
            {"name": "Data project", "technologies": ["XGBoost"]},
        ],
    }
    report = KeywordReport(matched=["FastAPI", "PostgreSQL", "XGBoost"], missing=[])

    ranked = rank_profile(profile, report)

    names = [p["name"] for p in ranked.profile["projects"]]
    assert len(names) == 3
    assert "Backend A" in names  # clearly strongest — always kept
    assert "Data project" in names  # diversified in ahead of a tied same-category project
    assert "Backend C" not in names


def test_diversity_does_not_sacrifice_a_much_stronger_same_category_project():
    """A different-category project with a near-zero score must not bump a
    genuinely stronger same-category project — diversity is a tie-breaker
    preference, not a quota that overrides quality."""
    profile = {
        "projects": [
            {"name": "Strong Backend", "technologies": ["FastAPI", "PostgreSQL", "Docker"]},
            {"name": "Solid Backend", "technologies": ["FastAPI", "PostgreSQL"]},
            {"name": "Weak Backend", "technologies": ["FastAPI"]},
            {"name": "Tiny Data project", "technologies": []},
        ],
    }
    report = KeywordReport(matched=["FastAPI", "PostgreSQL", "Docker"], missing=[])

    ranked = rank_profile(profile, report)

    names = [p["name"] for p in ranked.profile["projects"]]
    assert names == ["Strong Backend", "Solid Backend", "Weak Backend"]


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
