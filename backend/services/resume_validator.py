"""
Structural completeness checks for the final OptimizedResume dict, run right
before it's rendered/persisted (see api/v1/resume.py::_render_resume).

This doesn't invent or fill in missing data — a candidate with no portfolio
link is not a pipeline bug — it only surfaces gaps so they're visible in
logs instead of silently shipping a resume that's missing contact info or
still carries duplicate entries the upstream dedup/ranking should have
caught (see services/profile_deduplicator.py, services/relevance_ranker.py).
"""

# Matches relevance_ranker._MAX_PROJECTS — kept as a separate constant here
# since this module checks the *rendered* resume's shape, independent of how
# that shape was produced.
_MAX_PROJECTS_IN_RESUME = 3


def validate_resume_structure(resume: dict) -> list[str]:
    """Returns human-readable structural gaps found in `resume` — empty when
    everything expected is present. Callers decide whether to log, surface
    to the user, or ignore; this never raises or mutates `resume`."""
    issues: list[str] = []

    if not (resume.get("name") or "").strip():
        issues.append("missing candidate name")

    if not (resume.get("summary") or "").strip():
        issues.append("missing summary")

    if not (resume.get("email") or "").strip() and not (resume.get("phone") or "").strip():
        issues.append("missing both email and phone")

    if not resume.get("links"):
        issues.append("missing all professional links (LinkedIn/GitHub/portfolio)")

    if not resume.get("experience") and not resume.get("projects"):
        issues.append("no experience or projects to show")

    project_count = len(resume.get("projects") or [])
    if project_count > _MAX_PROJECTS_IN_RESUME:
        issues.append(f"{project_count} projects present, exceeds the {_MAX_PROJECTS_IN_RESUME}-project maximum")

    issues.extend(_duplicate_experience_issues(resume.get("experience") or []))
    issues.extend(_duplicate_project_issues(resume.get("projects") or []))

    return issues


def _duplicate_experience_issues(experience: list[dict]) -> list[str]:
    issues: list[str] = []
    seen: set[tuple[str, str]] = set()
    for entry in experience:
        key = (_normalize(entry.get("title")), _normalize(entry.get("company")))
        if key == ("", ""):
            continue
        if key in seen:
            issues.append(f"duplicate experience entry: {entry.get('title')} at {entry.get('company')}")
        seen.add(key)
    return issues


def _duplicate_project_issues(projects: list[dict]) -> list[str]:
    issues: list[str] = []
    seen: set[str] = set()
    for project in projects:
        key = _normalize(project.get("name"))
        if not key:
            continue
        if key in seen:
            issues.append(f"duplicate project entry: {project.get('name')}")
        seen.add(key)
    return issues


def _normalize(value) -> str:
    return " ".join(str(value or "").strip().lower().split())
