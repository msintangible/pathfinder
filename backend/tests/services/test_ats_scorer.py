from services.ats_scorer import compute_ats
from services.keyword_evidence import classify_keyword
from services.keyword_matcher import KeywordReport
from schemas.resume import KeywordEvidence


def test_full_match_scores_100():
    report = KeywordReport(matched=["Python", "Docker"], missing=[])

    assert compute_ats(report) == 100.0


def test_no_match_scores_0():
    report = KeywordReport(matched=[], missing=["Python", "Docker"])

    assert compute_ats(report) == 0.0


def test_partial_match_is_rounded_percentage():
    report = KeywordReport(matched=["Python"], missing=["Docker", "Terraform"])

    assert compute_ats(report) == 33.33


def test_no_keywords_at_all_scores_0():
    report = KeywordReport(matched=[], missing=[])

    assert compute_ats(report) == 0.0


# ---------------------------------------------------------------------------
# Evidence-tier weighting — a matched keyword now contributes its real
# classify_keyword confidence, not flat full credit (see compute_ats'
# docstring). A plain KeywordReport with no evidence (all four tests above)
# must keep scoring exactly as before — that's the fallback path.
# ---------------------------------------------------------------------------

def test_semantic_match_contributes_its_tier_confidence_not_full_credit():
    # "relational databases" only classifies as semantic (confidence 0.85)
    # against this profile — the score must reflect that, not treat it as
    # equal to an exact match.
    profile = {"databases": ["Azure SQL"]}
    evidence = [classify_keyword("relational databases", profile)]
    report = KeywordReport(matched=["relational databases"], missing=[], evidence=evidence)

    assert compute_ats(report) == 85.0


def test_exact_and_semantic_matches_produce_a_weighted_average():
    profile = {"technical_skills": ["Python"], "databases": ["Azure SQL"]}
    evidence = [
        classify_keyword("Python", profile),  # exact, confidence 1.0
        classify_keyword("relational databases", profile),  # semantic, confidence 0.85
    ]
    report = KeywordReport(matched=["Python", "relational databases"], missing=[], evidence=evidence)

    # (1.0 + 0.85) / 2 * 100
    assert compute_ats(report) == 92.5


def test_unsupported_keyword_in_evidence_still_contributes_nothing():
    profile = {"technical_skills": ["Python"]}
    evidence = [
        classify_keyword("Python", profile),
        classify_keyword("Terraform", profile),
    ]
    report = KeywordReport(matched=["Python"], missing=["Terraform"], evidence=evidence)

    # (1.0 + 0) / 2 * 100 — identical to the old flat matched/total behavior
    # here since Python is a full-credit exact match.
    assert compute_ats(report) == 50.0


def test_matched_keyword_missing_from_evidence_falls_back_to_full_credit():
    # Simulates any caller that hasn't (or can't) attach real evidence for a
    # specific matched keyword — e.g. resume_generation_agent's "after"
    # report for a newly woven-in keyword, whose only evidence entry still
    # says "unsupported" from its pre-optimization classification.
    report = KeywordReport(
        matched=["Kubernetes"],
        missing=[],
        evidence=[KeywordEvidence(keyword="Kubernetes", status="unsupported", evidence_type="none", confidence=0.0)],
    )

    assert compute_ats(report) == 100.0
