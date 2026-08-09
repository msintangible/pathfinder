"""
A curated, evidence-gated taxonomy of process/methodology/soft-skill ATS
keywords legitimately inferable from HOW a candidate describes their real
work, even when never mentioned literally — e.g. a project whose bullets
describe testing implies "Testing & Debugging" even if that exact phrase
never appears as a skill tag anywhere in the profile.

Evidence-gated by design, mirroring keyword_matcher.filter_backed_keywords'
"real textual basis" rule: a keyword is only ever offered here if the
candidate's OWN text (work_experience/project/github bullets and
descriptions) contains at least one of its trigger phrases. This is what
keeps inference truthful — resume_generation_agent only ever receives these
as additional missing_keyword candidates, still subject to its normal
per-block truthful-support test before weaving one in (see _SYSTEM_PROMPT's
ATS keyword test) — nothing here fabricates or auto-credits anything.
"""

# keyword -> trigger phrases; ANY one match anywhere in the candidate's own
# flattened text is sufficient evidence to OFFER the keyword (not to credit
# it — that still goes through the LLM's truthful-support test, and
# separately through keyword_matcher.filter_backed_keywords once it
# actually appears in the rendered wording).
INFERABLE_KEYWORDS: dict[str, list[str]] = {
    "Software Development Lifecycle (SDLC)": [
        "designed", "developed and deployed", "built and launched",
        "requirements", "maintained", "end-to-end", "full lifecycle", "deployment",
    ],
    "Agile Software Development": ["agile", "scrum", "sprint", "kanban", "standup"],
    "Team Collaboration": ["team", "collaborat", "pair programming", "code review"],
    "Cross-functional Collaboration": ["stakeholder", "cross-functional", "product manager", "designer"],
    "Software Design": ["architecture", "system design", "design pattern", "designed a"],
    "API Development": ["api", "rest", "endpoint", "graphql"],
    "Requirements Analysis": ["requirements", "specification", "user story", "scope"],
    "Testing & Debugging": ["test", "testing", "debug", "qa", "unit test", "integration test"],
    "Version Control": ["git", "github", "gitlab", "version control", "code review"],
    "Technical Documentation": ["document", "readme", "wiki", "spec", "documentation"],
    "CI/CD": ["ci/cd", "continuous integration", "continuous deployment", "pipeline", "github actions", "jenkins"],
}

# Problem Solving has no fixed trigger phrase — any real project/job entry
# that describes building or fixing something already demonstrates it (see
# resume_generation_agent._SYSTEM_PROMPT's existing soft-skill guidance),
# so its evidence check is structural (does the candidate have any real
# entries at all) rather than phrase-based.
_PROBLEM_SOLVING_KEYWORD = "Problem Solving"


def infer_available_keywords(profile: dict) -> list[str]:
    """
    Which INFERABLE_KEYWORDS (plus Problem Solving) have real textual
    evidence somewhere in the candidate's own profile text. Callers still
    need to check the job actually cares about a keyword before offering it
    as a missing_keyword candidate — see
    resume_generation_agent._augment_with_inferred_keywords.
    """
    haystack = _flatten_profile_text(profile).lower()
    available = [
        keyword
        for keyword, triggers in INFERABLE_KEYWORDS.items()
        if any(trigger in haystack for trigger in triggers)
    ]
    if _has_any_demonstrated_work(profile):
        available.append(_PROBLEM_SOLVING_KEYWORD)
    return available


def _has_any_demonstrated_work(profile: dict) -> bool:
    return bool(profile.get("work_experience") or profile.get("projects") or profile.get("github_repositories"))


def _flatten_profile_text(profile: dict) -> str:
    parts: list[str] = []
    for entry in profile.get("work_experience") or []:
        parts.extend(entry.get("bullets") or [])
    for project in profile.get("projects") or []:
        parts.append(project.get("description") or "")
        parts.extend(project.get("notable_achievements") or [])
        parts.append(project.get("problem") or "")
        parts.append(project.get("solution") or "")
        parts.extend(project.get("architecture") or [])
        parts.extend(project.get("responsibilities") or [])
        parts.extend(project.get("technical_achievements") or [])
        parts.extend(project.get("impact") or [])
        parts.extend(project.get("deployment") or [])
    for repo in profile.get("github_repositories") or []:
        parts.append(repo.get("description") or "")
        parts.append(repo.get("purpose") or "")
    return " ".join(parts)
