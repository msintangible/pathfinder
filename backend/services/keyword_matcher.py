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

# Nested sections whose entries carry their own tag fields — a keyword can be
# genuinely true of the candidate (e.g. tagged on one specific job) without
# ever being rolled up into the flat _PROFILE_SKILL_FIELDS lists above.
# Mirrors the exact fields relevance_ranker.py already treats as authoritative
# skill/tech tags per entry, so matching and ranking agree on what counts.
_NESTED_SKILL_SECTIONS = {
    "work_experience": ("technologies", "skills_demonstrated"),
    "projects": ("technologies", "skills_demonstrated"),
    "github_repositories": ("technologies", "languages", "frameworks", "skills_demonstrated"),
}


@dataclass
class KeywordReport:
    matched: list[str]
    missing: list[str]


def _nested_terms(profile: dict) -> set[str]:
    return {
        term.strip().lower()
        for section, fields in _NESTED_SKILL_SECTIONS.items()
        for entry in (profile.get(section) or [])
        for field in fields
        for term in (entry.get(field) or [])
        if term
    }


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
    } | _nested_terms(profile)

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


def find_added_keywords(missing_keywords: list[str], optimized_resume: dict) -> list[str]:
    """
    Which of missing_keywords now appear in the optimized resume's actual
    wording — i.e. the optimization LLM found genuine, truthful support for
    them somewhere in the candidate's real experience and wove them in.

    Substring matching against the flattened rendered text, not the
    structured-field matching match_keywords() does above: a woven-in
    keyword shows up as natural wording inside a bullet/summary, not as a
    new profile skill tag (the LLM can only edit wording, never add one).
    """
    haystack = _flatten_optimized_resume(optimized_resume).lower()
    return [keyword for keyword in missing_keywords if keyword.strip().lower() in haystack]


def _flatten_optimized_resume(optimized_resume: dict) -> str:
    parts = [
        optimized_resume.get("headline") or "",
        optimized_resume.get("summary") or "",
        ", ".join(optimized_resume.get("skills") or []),
    ]
    for entry in optimized_resume.get("experience") or []:
        parts.extend(entry.get("bullets") or [])
    for project in optimized_resume.get("projects") or []:
        parts.append(project.get("description") or "")
        parts.extend(project.get("technologies") or [])
    return " ".join(parts)


def filter_backed_keywords(candidate_profile: dict, keywords: list[str]) -> list[str]:
    """
    Of `keywords` (already confirmed to appear in the optimized resume's
    wording — see find_added_keywords), keep only the ones with a real
    textual basis somewhere in the candidate's own profile data: a project,
    a job bullet, a GitHub repo, a skill list entry — anything the candidate
    actually said about themselves.

    This is a code-level safety net, not a replacement for
    ResumeGenerationAgent's "never invent" prompt rule — a keyword with zero
    textual basis anywhere in the full profile is a clear-cut fabrication
    signal; a keyword this substring check misses (a genuine but very
    differently-worded rephrase) is not something either this or the prompt
    can fully guarantee, but that's a smaller, harder-to-avoid gap than
    trusting the LLM's compliance with no check at all.
    """
    profile_text = _flatten_candidate_profile_text(candidate_profile).lower()
    return [keyword for keyword in keywords if keyword.strip().lower() in profile_text]


def _flatten_candidate_profile_text(profile: dict) -> str:
    parts: list[str] = [profile.get("headline") or "", profile.get("summary") or ""]

    for field in _PROFILE_SKILL_FIELDS:
        parts.extend(profile.get(field) or [])
    parts.extend(profile.get("soft_skills") or [])

    for entry in profile.get("work_experience") or []:
        parts.extend(entry.get("bullets") or [])
        parts.extend(entry.get("technologies") or [])
        parts.extend(entry.get("skills_demonstrated") or [])

    for project in profile.get("projects") or []:
        parts.append(project.get("description") or "")
        parts.extend(project.get("technologies") or [])
        parts.extend(project.get("skills_demonstrated") or [])
        parts.extend(project.get("notable_achievements") or [])

    for repo in profile.get("github_repositories") or []:
        parts.append(repo.get("description") or "")
        parts.append(repo.get("purpose") or "")
        parts.extend(repo.get("languages") or [])
        parts.extend(repo.get("frameworks") or [])
        parts.extend(repo.get("technologies") or [])
        parts.extend(repo.get("skills_demonstrated") or [])

    for education in profile.get("education") or []:
        parts.extend(education.get("achievements") or [])

    for cert in profile.get("certifications") or []:
        parts.append(cert.get("name") or "")

    parts.extend(profile.get("open_source_contributions") or [])
    parts.extend(profile.get("awards") or [])
    parts.extend(profile.get("achievements") or [])
    parts.extend(profile.get("leadership_experience") or [])
    parts.extend(profile.get("volunteer_work") or [])
    parts.extend(profile.get("publications") or [])
    parts.extend(profile.get("interests") or [])

    return " ".join(parts)
