from services.ats_scorer import compute_ats
from services.keyword_matcher import KeywordReport


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
