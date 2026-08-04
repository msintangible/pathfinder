from services.optimization_validator import validate_optimization_integrity


def _base_resume(**overrides) -> dict:
    resume = {
        "email": "jane@example.com",
        "phone": "+1 555 0100",
        "links": {"linkedin": "https://linkedin.com/in/jane"},
        "experience": [{"title": "Engineer"}],
        "projects": [{"name": "pathfinder"}],
        "skills": ["Python", "AWS"],
    }
    resume.update(overrides)
    return resume


def _base_profile(**overrides) -> dict:
    profile = {
        "email": "jane@example.com",
        "phone": "+1 555 0100",
        "links": {"linkedin": "https://linkedin.com/in/jane"},
        "technical_skills": ["Python", "AWS"],
    }
    profile.update(overrides)
    return profile


def _ranked(**overrides) -> dict:
    ranked = {"work_experience": [{"title": "Engineer"}], "projects": [{"name": "pathfinder"}]}
    ranked.update(overrides)
    return ranked


# ---------------------------------------------------------------------------
# Identity preservation
# ---------------------------------------------------------------------------

def test_no_issues_when_everything_matches():
    issues = validate_optimization_integrity(
        _base_profile(), _ranked(), _base_resume(), ats_score_before=50.0, ats_score_after=50.0,
    )
    assert issues == []


def test_flags_email_changed():
    resume = _base_resume(email="different@example.com")
    issues = validate_optimization_integrity(
        _base_profile(), _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("email changed" in issue for issue in issues)


def test_flags_phone_dropped():
    resume = _base_resume(phone="")
    issues = validate_optimization_integrity(
        _base_profile(), _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("phone changed" in issue for issue in issues)


def test_flags_link_missing_from_resume():
    resume = _base_resume(links={})
    issues = validate_optimization_integrity(
        _base_profile(), _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("link 'linkedin'" in issue for issue in issues)


def test_does_not_flag_a_link_the_candidate_never_had():
    profile = _base_profile(links={})
    resume = _base_resume(links={})
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert issues == []


# ---------------------------------------------------------------------------
# Entry-count integrity
# ---------------------------------------------------------------------------

def test_flags_resume_with_more_entries_than_ranked_profile():
    ranked = _ranked(projects=[{"name": "pathfinder"}])
    resume = _base_resume(projects=[{"name": "pathfinder"}, {"name": "extra"}])
    issues = validate_optimization_integrity(
        _base_profile(), ranked, resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("MORE entries" in issue and "projects" in issue for issue in issues)


def test_reports_trimmed_entries_as_informational():
    ranked = _ranked(projects=[{"name": "A"}, {"name": "B"}])
    resume = _base_resume(projects=[{"name": "A"}])
    issues = validate_optimization_integrity(
        _base_profile(), ranked, resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("trimmed from 2 to 1" in issue for issue in issues)


# ---------------------------------------------------------------------------
# ATS regression
# ---------------------------------------------------------------------------

def test_flags_ats_score_regression():
    issues = validate_optimization_integrity(
        _base_profile(), _ranked(), _base_resume(), ats_score_before=60.0, ats_score_after=45.0,
    )
    assert any("ATS score regressed" in issue for issue in issues)


def test_does_not_flag_ats_score_improvement():
    issues = validate_optimization_integrity(
        _base_profile(), _ranked(), _base_resume(), ats_score_before=45.0, ats_score_after=60.0,
    )
    assert not any("ATS score regressed" in issue for issue in issues)


# ---------------------------------------------------------------------------
# Skills retention
# ---------------------------------------------------------------------------

def test_flags_majority_of_skills_dropped():
    profile = _base_profile(technical_skills=["Python", "AWS", "Docker", "Redis"])
    resume = _base_resume(skills=["Python"])
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("candidate skills dropped" in issue for issue in issues)


def test_does_not_flag_minor_skill_trim():
    profile = _base_profile(technical_skills=["Python", "AWS", "Docker", "Redis"])
    resume = _base_resume(skills=["Python", "AWS", "Docker"])
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert not any("candidate skills dropped" in issue for issue in issues)


# ---------------------------------------------------------------------------
# Thin projects with an unmined matching repo
# ---------------------------------------------------------------------------

def test_flags_thin_project_with_a_similarly_named_repo():
    profile = _base_profile(github_repositories=[{"name": "QuantaScan"}])
    resume = _base_resume(projects=[{"name": "QuantaScan", "bullets": ["one", "two"]}])
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert any("QuantaScan" in issue and "similarly-named github repository" in issue for issue in issues)


def test_does_not_flag_a_project_with_enough_bullets():
    profile = _base_profile(github_repositories=[{"name": "QuantaScan"}])
    resume = _base_resume(projects=[{"name": "QuantaScan", "bullets": ["one", "two", "three"]}])
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert not any("similarly-named github repository" in issue for issue in issues)


def test_does_not_flag_a_thin_project_with_no_matching_repo():
    profile = _base_profile(github_repositories=[{"name": "unrelated-repo"}])
    resume = _base_resume(projects=[{"name": "QuantaScan", "bullets": ["one", "two"]}])
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert not any("similarly-named github repository" in issue for issue in issues)


def test_does_not_flag_when_profile_has_no_github_repositories():
    profile = _base_profile()
    resume = _base_resume(projects=[{"name": "QuantaScan", "bullets": ["one", "two"]}])
    issues = validate_optimization_integrity(
        profile, _ranked(), resume, ats_score_before=50.0, ats_score_after=50.0,
    )
    assert not any("similarly-named github repository" in issue for issue in issues)
