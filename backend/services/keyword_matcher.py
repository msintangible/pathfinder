from dataclasses import dataclass

# Every profile field that can hold a skill/technology term the candidate has.
PROFILE_SKILL_FIELDS = (
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
# ever being rolled up into the flat PROFILE_SKILL_FIELDS lists above.
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


def _job_terms(job: dict) -> dict[str, str]:
    # Dedup across job fields (e.g. "Python" in both skills and keywords) while
    # keeping the first-seen casing.
    job_terms: dict[str, str] = {}
    for field in _JOB_KEYWORD_FIELDS:
        for term in (job.get(field) or []):
            if not term:
                continue
            key = term.strip().lower()
            job_terms.setdefault(key, term.strip())
    return job_terms


def match_keywords(profile: dict, job: dict) -> KeywordReport:
    """Compare the job's skills/technologies/keywords against everything the candidate's profile lists.

    Matching is case-insensitive; the original casing from the job posting is
    preserved in the output since that's what downstream consumers display.
    """
    profile_terms = {
        term.strip().lower()
        for field in PROFILE_SKILL_FIELDS
        for term in (profile.get(field) or [])
        if term
    } | _nested_terms(profile)

    job_terms = _job_terms(job)
    matched = [original for key, original in job_terms.items() if key in profile_terms]
    missing = [original for key, original in job_terms.items() if key not in profile_terms]
    return KeywordReport(matched=matched, missing=missing)


def unused_candidate_skills(profile: dict, job: dict) -> list[str]:
    """
    Flat-field candidate skills with no counterpart anywhere in this job's
    keyword set — real skills the candidate has that this specific posting
    has no use for. Surfaced in OptimizationReport so a candidate can see
    those skills weren't overlooked by mistake, just not relevant here.

    Deliberately only the flat PROFILE_SKILL_FIELDS lists, not
    _NESTED_SKILL_SECTIONS — this mirrors what actually renders in the
    resume's Skills section (see synthetic_profile_layout.py), not every
    per-project tag in the full profile.
    """
    job_term_keys = set(_job_terms(job))
    seen: set[str] = set()
    result: list[str] = []
    for field in PROFILE_SKILL_FIELDS:
        for term in profile.get(field) or []:
            if not term:
                continue
            key = term.strip().lower()
            if key in job_term_keys or key in seen:
                continue
            seen.add(key)
            result.append(term.strip())
    return result


def find_added_keywords(missing_keywords: list[str], optimized_resume: dict) -> list[str]:
    """
    Which of missing_keywords now appear in the optimized resume's actual
    wording — i.e. the optimization LLM found genuine, truthful support for
    them somewhere in the candidate's real experience and wove them in.

    Matching against the flattened rendered text, not the structured-field
    matching match_keywords() does above: a woven-in keyword shows up as
    natural wording inside a bullet/summary, not as a new profile skill tag
    (the LLM can only edit wording, never add one). See _keyword_appears_in
    for why this isn't a plain substring check — the prompt tells the model
    to phrase concepts naturally rather than paste the keyword verbatim, so
    a process/soft-skill keyword ("full lifecycle development") is expected
    to show up reworded, not word-for-word.
    """
    haystack = _flatten_optimized_resume(optimized_resume).lower()
    return [keyword for keyword in missing_keywords if _keyword_appears_in(keyword, haystack)]


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
    signal; a keyword this check misses (a genuine but very differently
    -worded rephrase) is not something either this or the prompt can fully
    guarantee, but that's a smaller, harder-to-avoid gap than trusting the
    LLM's compliance with no check at all.
    """
    profile_text = _flatten_candidate_profile_text(candidate_profile).lower()
    return [keyword for keyword in keywords if _keyword_appears_in(keyword, profile_text)]


_STOPWORDS = {"a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with"}


def _keyword_appears_in(keyword: str, haystack_lower: str) -> bool:
    """
    True if `keyword` has real textual basis in `haystack_lower` — an exact
    substring match, or, for a 3+ significant-word keyword, most of those
    words appearing anywhere in the text (not necessarily together or in
    order). This is what lets a process/soft-skill keyword like "full
    lifecycle development" credit against a truthfully-related but
    differently-worded bullet ("managed the full project lifecycle from
    requirements gathering to deployment and maintenance") — 2 of its 3
    words appear, so it counts.

    Deliberately NOT applied to 1-2 word keywords: a category label like
    "data science" sharing just one common word ("data") with an unrelated
    bullet isn't real evidence — with only 2 words to work with, "most of
    them" would mean "any one of them", which is too weak a signal to credit
    without the exact phrase actually appearing.
    """
    normalized = keyword.strip().lower()
    if not normalized:
        return False
    if normalized in haystack_lower:
        return True

    words = [word for word in normalized.split() if word not in _STOPWORDS]
    if len(words) < 3:
        return False

    haystack_tokens = haystack_lower.split()
    present = sum(1 for word in words if _word_present(word, haystack_tokens))
    return present >= len(words) - 1


def _word_present(word: str, haystack_tokens: list[str]) -> bool:
    # A short common-prefix match (5 chars) catches simple inflections
    # ("solving"/"solve"/"solver", "developer"/"development") without full
    # stemming, while still requiring most of a word to line up.
    prefix = word[:5] if len(word) > 5 else word
    return any(token.startswith(prefix) for token in haystack_tokens)


def _flatten_candidate_profile_text(profile: dict) -> str:
    parts: list[str] = [profile.get("headline") or "", profile.get("summary") or ""]

    for field in PROFILE_SKILL_FIELDS:
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
