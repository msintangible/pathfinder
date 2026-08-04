from services.inferable_keywords import infer_available_keywords


def test_infers_testing_from_bullet_evidence():
    profile = {
        "work_experience": [
            {"bullets": ["Wrote unit tests to catch regressions before deployment"]},
        ],
    }

    result = infer_available_keywords(profile)

    assert "Testing & Debugging" in result


def test_infers_agile_from_bullet_evidence():
    profile = {"work_experience": [{"bullets": ["Worked in an agile team running two-week sprints"]}]}

    result = infer_available_keywords(profile)

    assert "Agile Software Development" in result


def test_does_not_infer_a_keyword_with_no_evidence():
    profile = {"work_experience": [{"bullets": ["Built a to-do list app"]}]}

    result = infer_available_keywords(profile)

    assert "CI/CD" not in result
    assert "Agile Software Development" not in result


def test_infers_from_project_description_and_achievements():
    profile = {"projects": [{"description": "Documented the API in a public wiki", "notable_achievements": []}]}

    result = infer_available_keywords(profile)

    assert "Technical Documentation" in result
    assert "API Development" in result


def test_infers_from_github_repo_description():
    profile = {"github_repositories": [{"description": "A REST API with full test coverage", "purpose": None}]}

    result = infer_available_keywords(profile)

    assert "API Development" in result
    assert "Testing & Debugging" in result


def test_problem_solving_inferred_whenever_any_real_entry_exists():
    profile = {"projects": [{"description": "A simple calculator app"}]}

    result = infer_available_keywords(profile)

    assert "Problem Solving" in result


def test_problem_solving_not_inferred_from_an_empty_profile():
    result = infer_available_keywords({})

    assert "Problem Solving" not in result


def test_empty_profile_infers_nothing():
    assert infer_available_keywords({}) == []
