from services.keyword_matcher import KeywordReport

# Caps keep the LLM optimization payload focused on what's relevant to the
# job, the same latency/token rationale as JobAnalysisAgent's text truncation.
_MAX_WORK_EXPERIENCE = 5
_MAX_PROJECTS = 6
_MAX_GITHUB_REPOS = 4


def _relevance(entry: dict, matched_lower: set[str], *fields: str) -> int:
    terms = {
        term.strip().lower()
        for field in fields
        for term in (entry.get(field) or [])
        if term
    }
    return len(terms & matched_lower)


def _sort_section(entries: list[dict] | None, matched_lower: set[str], cap: int, *fields: str) -> list[dict]:
    if not entries:
        return []
    ranked = sorted(entries, key=lambda entry: _relevance(entry, matched_lower, *fields), reverse=True)
    return ranked[:cap]


def rank_profile(profile: dict, keyword_report: KeywordReport) -> dict:
    """Reorder and trim profile sections so entries relevant to the job's matched keywords come first."""
    matched_lower = {term.lower() for term in keyword_report.matched}

    ranked = dict(profile)
    ranked["work_experience"] = _sort_section(
        profile.get("work_experience"), matched_lower, _MAX_WORK_EXPERIENCE,
        "technologies", "skills_demonstrated",
    )
    ranked["projects"] = _sort_section(
        profile.get("projects"), matched_lower, _MAX_PROJECTS,
        "technologies", "skills_demonstrated",
    )
    ranked["github_repositories"] = _sort_section(
        profile.get("github_repositories"), matched_lower, _MAX_GITHUB_REPOS,
        "technologies", "languages", "frameworks", "skills_demonstrated",
    )
    return ranked
