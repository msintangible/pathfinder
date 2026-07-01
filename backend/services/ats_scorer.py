from services.keyword_matcher import KeywordReport


def compute_ats(keyword_report: KeywordReport) -> float:
    """ATS keyword-match score (0-100): percentage of the job's required keywords found in the candidate's profile."""
    total = len(keyword_report.matched) + len(keyword_report.missing)
    if total == 0:
        return 0.0
    return round(len(keyword_report.matched) / total * 100, 2)
