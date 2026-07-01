from dataclasses import dataclass

# Every profile field that can hold a skill/technology term the candidate has.
_PROFILE_SKILL_FIELDS = (
    "technical_skills",
    "programming_languages",
    "frameworks",
    "libraries",
    "databases",
    "cloud_platforms",
    "devops_tools",
    "ai_ml_tools",
    "development_tools",
)

# Every job field that can hold a required/preferred term.
_JOB_KEYWORD_FIELDS = ("skills", "technologies", "keywords")


@dataclass
class KeywordReport:
    matched: list[str]
    missing: list[str]


def match_keywords(profile: dict, job: dict) -> KeywordReport:
    """Compare the job's skills/technologies/keywords against everything the candidate's profile lists.

    Matching is case-insensitive; the original casing from the job posting is
    preserved in the output since that's what downstream consumers display.
    """
    profile_terms = {
        term.strip().lower()
        for field in _PROFILE_SKILL_FIELDS
        for term in (profile.get(field) or [])
        if term
    }

    # Dedup across job fields (e.g. "Python" in both skills and keywords) while
    # keeping the first-seen casing.
    job_terms: dict[str, str] = {}
    for field in _JOB_KEYWORD_FIELDS:
        for term in (job.get(field) or []):
            if not term:
                continue
            key = term.strip().lower()
            job_terms.setdefault(key, term.strip())

    matched = [original for key, original in job_terms.items() if key in profile_terms]
    missing = [original for key, original in job_terms.items() if key not in profile_terms]
    return KeywordReport(matched=matched, missing=missing)
