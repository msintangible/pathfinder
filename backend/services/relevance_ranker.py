from dataclasses import dataclass

from services.keyword_matcher import KeywordReport

# Caps keep the LLM optimization payload focused on what's relevant to the
# job, the same latency/token rationale as JobAnalysisAgent's text truncation.
_MAX_WORK_EXPERIENCE = 5
_MAX_PROJECTS = 6
_MAX_GITHUB_REPOS = 4


@dataclass
class RankedProfile:
    # Byte-identical in shape to the plain dict this returned before —
    # still safe to json.dumps straight into the LLM prompt.
    profile: dict
    # Each ranked section's entries' positions in the *original* (unranked)
    # profile list, in the same new order — e.g. source_indices["projects"][0]
    # is the original index of profile["projects"] that now sits at
    # profile["projects"][0] after ranking/truncation. Lets callers map an
    # optimized entry back to the document block it came from.
    source_indices: dict[str, list[int]]


def _relevance(entry: dict, matched_lower: set[str], *fields: str) -> int:
    terms = {
        term.strip().lower()
        for field in fields
        for term in (entry.get(field) or [])
        if term
    }
    return len(terms & matched_lower)


def _sort_section(
    entries: list[dict] | None, matched_lower: set[str], cap: int, *fields: str
) -> tuple[list[dict], list[int]]:
    if not entries:
        return [], []
    indexed = sorted(
        enumerate(entries),
        key=lambda item: _relevance(item[1], matched_lower, *fields),
        reverse=True,
    )[:cap]
    return [entry for _, entry in indexed], [index for index, _ in indexed]


def rank_profile(profile: dict, keyword_report: KeywordReport) -> RankedProfile:
    """Reorder and trim profile sections so entries relevant to the job's matched keywords come first."""
    matched_lower = {term.lower() for term in keyword_report.matched}

    work_experience, work_experience_indices = _sort_section(
        profile.get("work_experience"), matched_lower, _MAX_WORK_EXPERIENCE,
        "technologies", "skills_demonstrated",
    )
    projects, project_indices = _sort_section(
        profile.get("projects"), matched_lower, _MAX_PROJECTS,
        "technologies", "skills_demonstrated",
    )
    github_repositories, github_repository_indices = _sort_section(
        profile.get("github_repositories"), matched_lower, _MAX_GITHUB_REPOS,
        "technologies", "languages", "frameworks", "skills_demonstrated",
    )

    ranked = dict(profile)
    ranked["work_experience"] = work_experience
    ranked["projects"] = projects
    ranked["github_repositories"] = github_repositories

    return RankedProfile(
        profile=ranked,
        source_indices={
            "work_experience": work_experience_indices,
            "projects": project_indices,
            "github_repositories": github_repository_indices,
        },
    )
