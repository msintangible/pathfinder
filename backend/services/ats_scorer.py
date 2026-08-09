from services.keyword_matcher import KeywordReport


def compute_ats(keyword_report: KeywordReport) -> float:
    """
    ATS keyword-match score (0-100): each matched keyword contributes its
    real evidence confidence (see schemas/resume.py::KeywordEvidence) rather
    than flat full credit — a keyword only "supported"/matched via a loose
    semantic/experience tier (confidence 0.6-0.85) pulls the score less than
    an exact/alias match (0.9-1.0), so a resume leaning entirely on loose
    evidence doesn't score identically to one with strong direct matches.
    Missing keywords still contribute nothing, same as before.

    A matched keyword with no corresponding "supported" entry in
    keyword_report.evidence falls back to full credit (1.0). This keeps two
    real call shapes correct with zero extra code: (1) a plain
    KeywordReport(matched=[...], missing=[...]) built without evidence at
    all (existing tests, and any future caller not yet wired to evidence)
    scores exactly as it always did — every matched keyword at full credit;
    (2) resume_generation_agent's "after" score, built by adding
    already-verified added_keywords into `matched` while carrying the
    original `evidence` list forward — those keywords' only evidence entry
    says "unsupported" (that's what they were *before* optimization), which
    is deliberately excluded from the confidence lookup below so they don't
    get penalized for a stale pre-optimization classification; they fall
    back to full credit, matching the fact that find_added_keywords +
    filter_backed_keywords already confirmed they're now genuinely present
    and truthfully backed.
    """
    total = len(keyword_report.matched) + len(keyword_report.missing)
    if total == 0:
        return 0.0

    confidence_by_keyword = {
        item.keyword.strip().lower(): item.confidence
        for item in keyword_report.evidence
        if item.status == "supported"
    }
    matched_weight = sum(
        confidence_by_keyword.get(keyword.strip().lower(), 1.0)
        for keyword in keyword_report.matched
    )
    return round(matched_weight / total * 100, 2)
