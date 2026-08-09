from services.keyword_evidence import classify_keyword, classify_keywords


# ---------------------------------------------------------------------------
# Tier 1 — exact
# ---------------------------------------------------------------------------

def test_exact_match_on_flat_skill_field():
    profile = {"technical_skills": ["Python"]}

    result = classify_keyword("Python", profile)

    assert result.status == "supported"
    assert result.evidence_type == "exact"
    assert result.confidence == 1.0
    assert result.evidence == ["Python"]


def test_exact_match_is_case_insensitive():
    profile = {"technical_skills": ["python"]}

    result = classify_keyword("PYTHON", profile)

    assert result.status == "supported"
    assert result.evidence_type == "exact"


def test_exact_match_on_nested_project_technology():
    profile = {"projects": [{"technologies": ["Redis"]}]}

    result = classify_keyword("Redis", profile)

    assert result.status == "supported"
    assert result.evidence_type == "exact"
    assert result.evidence == ["Redis"]


# ---------------------------------------------------------------------------
# Tier 2 — alias
# ---------------------------------------------------------------------------

def test_alias_match_asp_net_core_vs_asp_net():
    profile = {"frameworks": ["ASP.NET"]}

    result = classify_keyword("ASP.NET Core", profile)

    assert result.status == "supported"
    assert result.evidence_type == "alias"
    assert result.evidence == ["ASP.NET"]


def test_alias_match_is_symmetric():
    profile = {"frameworks": ["ASP.NET Core"]}

    result = classify_keyword("ASP.NET", profile)

    assert result.status == "supported"
    assert result.evidence_type == "alias"


def test_alias_match_aws_full_name_vs_abbreviation():
    profile = {"cloud_platforms": ["AWS"]}

    result = classify_keyword("Amazon Web Services", profile)

    assert result.status == "supported"
    assert result.evidence_type == "alias"


def test_no_alias_match_without_profile_evidence():
    profile = {"technical_skills": ["Python"]}

    result = classify_keyword("Kubernetes", profile)

    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Tier 3 — semantic / category
# ---------------------------------------------------------------------------

def test_semantic_match_relational_databases():
    profile = {"databases": ["Azure SQL", "SQL Server", "MySQL"]}

    result = classify_keyword("relational databases", profile)

    assert result.status == "supported"
    assert result.evidence_type == "semantic"
    assert set(result.evidence) == {"Azure SQL", "SQL Server", "MySQL"}


def test_semantic_match_only_includes_members_actually_present():
    profile = {"databases": ["MySQL"]}

    result = classify_keyword("relational databases", profile)

    assert result.status == "supported"
    assert result.evidence_type == "semantic"
    assert result.evidence == ["MySQL"]


def test_semantic_match_bare_sql_against_a_named_sql_product():
    profile = {"databases": ["Azure SQL"]}

    result = classify_keyword("SQL", profile)

    assert result.status == "supported"
    assert result.evidence_type == "semantic"
    assert result.evidence == ["Azure SQL"]


def test_no_semantic_match_without_any_category_member():
    profile = {"technical_skills": ["Python"]}

    result = classify_keyword("relational databases", profile)

    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Tier 4 — experience (curated activity phrases)
# ---------------------------------------------------------------------------

def test_experience_match_api_development_from_curated_triggers():
    profile = {"work_experience": [{"bullets": ["Built REST APIs using FastAPI and ASP.NET."]}]}

    result = classify_keyword("API development", profile)

    assert result.status == "supported"
    assert result.evidence_type == "experience"
    assert "fastapi" in result.evidence


def test_experience_match_software_engineering_principles():
    profile = {"projects": [{"description": "Applied Clean Architecture and SOLID principles throughout."}]}

    result = classify_keyword("software engineering principles", profile)

    assert result.status == "supported"
    assert result.evidence_type == "experience"


def test_no_experience_match_for_curated_phrase_with_no_trigger_present():
    profile = {"work_experience": [{"bullets": ["Updated the company wiki."]}]}

    result = classify_keyword("API development", profile)

    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Tier 4 — experience (generic 3+ significant word overlap)
# ---------------------------------------------------------------------------

def test_experience_match_generic_three_word_phrase():
    profile = {
        "work_experience": [
            {"bullets": ["Managed the full project lifecycle from requirements gathering to deployment."]},
        ],
    }

    result = classify_keyword("full lifecycle development", profile)

    assert result.status == "supported"
    assert result.evidence_type == "experience"


def test_two_word_phrase_never_uses_the_generic_overlap_path():
    # "data science" is exactly 2 significant words — deliberately excluded
    # from the generic loose-overlap check (see keyword_matcher's own
    # reasoning); only "data" appearing alone must not be enough.
    profile = {"work_experience": [{"bullets": ["Managed customer data entry."]}]}

    result = classify_keyword("data science", profile)

    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Unsupported
# ---------------------------------------------------------------------------

def test_unsupported_with_no_evidence_anywhere():
    profile = {"technical_skills": ["Python"], "work_experience": [], "projects": []}

    result = classify_keyword("Terraform", profile)

    assert result.status == "unsupported"
    assert result.evidence_type == "none"
    assert result.confidence == 0.0
    assert result.evidence == []


def test_empty_keyword_is_unsupported():
    result = classify_keyword("   ", {"technical_skills": ["Python"]})

    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Part 3 false-positive protection — explicit named regression guards.
# Each of these must NEVER become "alias"/"semantic"/"experience" no matter
# how broad the profile's related technologies are, since the relationship
# is correlational, not definitional (see module docstring).
# ---------------------------------------------------------------------------

def test_aws_does_not_satisfy_terraform():
    result = classify_keyword("Terraform", {"cloud_platforms": ["AWS"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


def test_aws_does_not_satisfy_kubernetes():
    result = classify_keyword("Kubernetes", {"cloud_platforms": ["AWS"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


def test_docker_does_not_satisfy_kubernetes():
    # Containerization and orchestration are different skills — see module docstring.
    result = classify_keyword("Kubernetes", {"devops_tools": ["Docker"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


def test_azure_does_not_satisfy_terraform():
    result = classify_keyword("Terraform", {"cloud_platforms": ["Azure"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


def test_python_does_not_satisfy_pandas():
    result = classify_keyword("Pandas", {"technical_skills": ["Python"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


def test_docker_and_azure_do_not_satisfy_aws_marketplace():
    result = classify_keyword("AWS Marketplace", {"cloud_platforms": ["Azure"], "devops_tools": ["Docker"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


def test_machine_learning_tag_does_not_satisfy_a_specific_framework():
    result = classify_keyword("XGBoost", {"technical_skills": ["Machine Learning"]})
    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Synonym-key coverage — job postings phrase the same curated category/
# activity many ways; these must classify the same as their canonical key
# (see _CATEGORY_GROUPS/_ACTIVITY_GROUPS in keyword_evidence.py).
# ---------------------------------------------------------------------------

def test_semantic_match_relational_database_systems_phrasing():
    profile = {"databases": ["Azure SQL", "SQL Server", "MySQL"]}

    result = classify_keyword("Relational Database Systems", profile)

    assert result.status == "supported"
    assert result.evidence_type == "semantic"
    assert set(result.evidence) == {"Azure SQL", "SQL Server", "MySQL"}


def test_semantic_match_rdbms_expanded_phrasing():
    # "relational database management systems" is literally what RDBMS
    # stands for — must classify identically to the "rdbms" key.
    profile = {"databases": ["Azure SQL"]}

    result = classify_keyword("relational database management systems", profile)

    assert result.status == "supported"
    assert result.evidence_type == "semantic"


def test_experience_match_building_apis_phrasing():
    profile = {"work_experience": [{"bullets": ["Built FastAPI REST endpoints for the mobile app."]}]}

    result = classify_keyword("building APIs", profile)

    assert result.status == "supported"
    assert result.evidence_type == "experience"
    assert "fastapi" in result.evidence


def test_experience_match_api_design_phrasing():
    profile = {"work_experience": [{"bullets": ["Developed ASP.NET backend services."]}]}

    result = classify_keyword("API design", profile)

    assert result.status == "supported"
    assert result.evidence_type == "experience"


def test_synonym_phrasing_still_requires_real_evidence():
    # Widening recognized phrasing must not widen what counts as evidence —
    # an unrelated profile still classifies as unsupported.
    profile = {"technical_skills": ["Python"]}

    result = classify_keyword("Relational Database Systems", profile)

    assert result.status == "unsupported"
    assert result.evidence_type == "none"


# ---------------------------------------------------------------------------
# Batch wrapper
# ---------------------------------------------------------------------------

def test_classify_keywords_preserves_order_and_original_casing():
    profile = {"technical_skills": ["Python"], "databases": ["MySQL"]}

    results = classify_keywords(["Python", "relational databases", "Terraform"], profile)

    assert [r.keyword for r in results] == ["Python", "relational databases", "Terraform"]
    assert [r.status for r in results] == ["supported", "supported", "unsupported"]
    assert [r.evidence_type for r in results] == ["exact", "semantic", "none"]
