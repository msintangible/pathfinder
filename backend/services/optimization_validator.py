"""
Integrity checks comparing the source candidate profile against
ResumeGenerationAgent's final optimized_resume output.

Distinct concern from resume_validator.py: that module only ever looks at
the final resume's shape in isolation (is a name present, are there
duplicate entries). This module compares the final resume against where it
came from, so a dropped identity field, an unexplained entry-count change,
or a keyword-coverage regression is visible in logs instead of shipping
silently — exactly the class of bug the phone/links fields had before this
module existed.

Never raises and never mutates its inputs — same contract as
resume_validator.validate_resume_structure; callers decide whether to log,
surface to the user, or ignore.
"""

from services.keyword_matcher import PROFILE_SKILL_FIELDS

# If more than this fraction of the candidate's own flat-field skills are
# missing from the resume's rendered skills list, something likely went
# wrong in the skills block's patch/flatten step rather than the LLM having
# made a deliberate, reasonable trim.
_SKILLS_DROP_WARNING_RATIO = 0.5


def validate_optimization_integrity(
    candidate_profile: dict,
    ranked_profile: dict,
    optimized_resume: dict,
    ats_score_before: float,
    ats_score_after: float,
) -> list[str]:
    """Returns human-readable integrity issues found across the
    profile -> ranking -> optimization pipeline for one generation run —
    empty when nothing looks wrong."""
    issues: list[str] = []
    issues.extend(_identity_issues(candidate_profile, optimized_resume))
    issues.extend(_entry_count_issues(ranked_profile, optimized_resume))
    issues.extend(_ats_regression_issues(ats_score_before, ats_score_after))
    issues.extend(_skills_retention_issues(candidate_profile, optimized_resume))
    issues.extend(_thin_project_issues(candidate_profile, optimized_resume))
    return issues


# A project with this few bullets that also has a plausibly-matching
# github_repositories entry is worth a human glance — candidate_profile_agent's
# repo-mining rule (see its prompt) may have missed a real, extractable detail.
_THIN_PROJECT_BULLET_THRESHOLD = 3


def _thin_project_issues(candidate_profile: dict, optimized_resume: dict) -> list[str]:
    repo_names = {
        _normalize_name(repo.get("name"))
        for repo in (candidate_profile.get("github_repositories") or [])
        if repo.get("name")
    }
    if not repo_names:
        return []

    issues: list[str] = []
    for project in optimized_resume.get("projects") or []:
        bullet_count = len(project.get("bullets") or [])
        if bullet_count >= _THIN_PROJECT_BULLET_THRESHOLD:
            continue
        project_name = _normalize_name(project.get("name"))
        if any(project_name in repo_name or repo_name in project_name for repo_name in repo_names if repo_name):
            issues.append(
                f"project '{project.get('name')}' has only {bullet_count} bullet(s) but a "
                f"similarly-named github repository exists in the profile — its README may "
                f"hold unmined detail (see candidate_profile_agent.py's repo-mining rule)"
            )
    return issues


def _normalize_name(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _identity_issues(candidate_profile: dict, optimized_resume: dict) -> list[str]:
    """email/phone/links are copy-through fields — flatten_layout_to_resume
    never gives the LLM a block_id for them (see synthetic_profile_layout.py),
    so any mismatch here means a pipeline bug, not an LLM judgment call."""
    issues: list[str] = []
    for field in ("email", "phone"):
        source_value = (candidate_profile.get(field) or "").strip()
        result_value = (optimized_resume.get(field) or "").strip()
        if source_value and source_value != result_value:
            issues.append(f"{field} changed: '{source_value}' -> '{result_value}'")

    source_links = candidate_profile.get("links") or {}
    result_links = optimized_resume.get("links") or {}
    for key in ("linkedin", "github", "portfolio"):
        if source_links.get(key) and key not in result_links:
            issues.append(f"link '{key}' present in source profile but missing from resume")
    return issues


def _entry_count_issues(ranked_profile: dict, optimized_resume: dict) -> list[str]:
    """Compares against ranked_profile (post-cap, post-relevance-sort), not
    the raw candidate_profile — relevance_ranker's own caps (_MAX_PROJECTS
    etc.) are intentional and shouldn't be flagged as a bug here."""
    issues: list[str] = []
    section_map = {"work_experience": "experience", "projects": "projects"}
    for ranked_key, resume_key in section_map.items():
        ranked_count = len(ranked_profile.get(ranked_key) or [])
        result_count = len(optimized_resume.get(resume_key) or [])
        if result_count > ranked_count:
            issues.append(
                f"{resume_key}: resume has MORE entries ({result_count}) than the "
                f"ranked profile ({ranked_count}) — should never happen"
            )
        elif result_count < ranked_count:
            # Informational, not necessarily a bug — resume_page_fitter.py
            # legitimately trims a whole entry to hit the page budget.
            issues.append(
                f"{resume_key}: trimmed from {ranked_count} to {result_count} entries "
                f"(informational — expected when the page budget forces a trim)"
            )
    return issues


def _ats_regression_issues(ats_score_before: float, ats_score_after: float) -> list[str]:
    if ats_score_after < ats_score_before:
        return [
            f"ATS score regressed: {ats_score_before:.1f} -> {ats_score_after:.1f} "
            f"— optimization should never decrease keyword coverage"
        ]
    return []


def _skills_retention_issues(candidate_profile: dict, optimized_resume: dict) -> list[str]:
    source_skills = {
        skill.strip().lower()
        for field in PROFILE_SKILL_FIELDS
        for skill in (candidate_profile.get(field) or [])
        if skill
    }
    if not source_skills:
        return []
    result_skills = {skill.strip().lower() for skill in (optimized_resume.get("skills") or [])}
    dropped = source_skills - result_skills
    if len(dropped) > len(source_skills) * _SKILLS_DROP_WARNING_RATIO:
        return [f"{len(dropped)}/{len(source_skills)} candidate skills dropped from the resume's skills section"]
    return []
