from services.resume_validator import validate_resume_structure


def _resume(**overrides) -> dict:
    base = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+1 555 0100",
        "summary": "Backend engineer specialising in distributed systems.",
        "links": {"linkedin": "https://linkedin.com/in/jane"},
        "experience": [{"title": "Engineer", "company": "Acme"}],
        "projects": [{"name": "pathfinder"}],
    }
    base.update(overrides)
    return base


def test_complete_resume_has_no_issues():
    assert validate_resume_structure(_resume()) == []


def test_flags_missing_name():
    issues = validate_resume_structure(_resume(name=None))
    assert any("name" in issue for issue in issues)


def test_flags_missing_summary():
    issues = validate_resume_structure(_resume(summary=""))
    assert any("summary" in issue for issue in issues)


def test_flags_missing_email_and_phone():
    issues = validate_resume_structure(_resume(email=None, phone=None))
    assert any("email and phone" in issue for issue in issues)


def test_does_not_flag_contact_when_only_phone_present():
    issues = validate_resume_structure(_resume(email=None, phone="+1 555 0100"))
    assert not any("email and phone" in issue for issue in issues)


def test_flags_missing_links():
    issues = validate_resume_structure(_resume(links={}))
    assert any("professional links" in issue for issue in issues)


def test_flags_no_experience_or_projects():
    issues = validate_resume_structure(_resume(experience=[], projects=[]))
    assert any("no experience or projects" in issue for issue in issues)


def test_flags_more_than_three_projects():
    projects = [{"name": f"Project {i}"} for i in range(4)]
    issues = validate_resume_structure(_resume(projects=projects))
    assert any("exceeds the 3-project maximum" in issue for issue in issues)


def test_does_not_flag_exactly_three_projects():
    projects = [{"name": f"Project {i}"} for i in range(3)]
    issues = validate_resume_structure(_resume(projects=projects))
    assert not any("exceeds" in issue for issue in issues)


def test_flags_duplicate_experience_entries():
    experience = [
        {"title": "Intern", "company": "FluxPro"},
        {"title": "Intern", "company": "FluxPro"},
    ]
    issues = validate_resume_structure(_resume(experience=experience))
    assert any("duplicate experience entry" in issue for issue in issues)


def test_flags_duplicate_project_entries():
    projects = [{"name": "Stock Valuation Model"}, {"name": "Stock Valuation Model"}]
    issues = validate_resume_structure(_resume(projects=projects))
    assert any("duplicate project entry" in issue for issue in issues)


def test_does_not_flag_distinct_experience_entries():
    experience = [
        {"title": "Intern", "company": "FluxPro"},
        {"title": "Web Developer", "company": "Freelance"},
    ]
    issues = validate_resume_structure(_resume(experience=experience))
    assert not any("duplicate" in issue for issue in issues)
