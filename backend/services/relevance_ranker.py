from dataclasses import dataclass

from schemas.resume import KeywordEvidence
from services.keyword_matcher import KeywordReport

# Caps keep the LLM optimization payload focused on what's relevant to the
# job, the same latency/token rationale as JobAnalysisAgent's text truncation.
_MAX_WORK_EXPERIENCE = 5
# The final rendered resume shows at most 3 projects (a hard product
# requirement, not just a token-budget one) — capping here, not just at
# render time, since entry order/count downstream is copied straight through
# from this ranked list (see resume_generation_agent.py/synthetic_profile_layout.py).
_MAX_PROJECTS = 3
_MAX_GITHUB_REPOS = 4

# Composite project score weights (see _rank_projects) — kept as named
# constants, even though all currently equal, so tuning has one obvious
# place to change rather than a magic number buried in an expression.
_WEIGHT_KEYWORD_COVERAGE = 1.0
_WEIGHT_TECHNICAL_DEPTH = 1.0
_WEIGHT_IMPACT = 1.0

# A different-category project is only preferred over the best same-category
# remaining project when its score is at least this fraction of it —
# diversity should never force a genuinely weak project in just to fill a
# category quota. See _select_diverse_projects.
_DIVERSITY_TOLERANCE = 0.75

# Populated-field signal for _technical_depth — these are the Phase A
# structured fields (schemas/profile.py::Project) that only exist when the
# candidate/extraction genuinely captured real engineering detail, not just
# a one-line description.
_DEPTH_FIELDS = ("architecture", "responsibilities", "technical_achievements")

_IMPACT_SIGNAL_WORDS = (
    "won", "winner", "award", "1st place", "first place", "users", "downloads", "stars", "adopted",
)

# category (display label) -> curated signal phrases, checked as substrings
# against a project's own flattened text (technologies + description +
# every structured evidence field). Deliberately coarse and reviewed, same
# closed-list philosophy as keyword_evidence.CATEGORY_MAP — this is a
# display/diversity label, not a claim about the candidate, so a slightly
# imprecise category costs nothing the way a wrong keyword-evidence claim
# would.
_PROJECT_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Data/AI", [
        "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "xgboost", "keras",
        "machine learning", "llm", "openai", "huggingface", "nlp", "data science",
    ]),
    ("Cloud/DevOps", [
        "docker", "kubernetes", "terraform", "aws", "azure", "gcp",
        "ci/cd", "jenkins", "github actions", "cloud infrastructure",
    ]),
    ("Frontend", ["react", "vue", "angular", "typescript", "next.js", "svelte", "html", "css"]),
    ("Mobile", ["swift", "kotlin", "flutter", "react native", "android", "ios"]),
    ("Backend/API", [
        "fastapi", "django", "flask", "asp.net", "express", "spring",
        "rest api", "graphql", "postgresql", "mysql", "mongodb", "websocket",
    ]),
]
_DEFAULT_CATEGORY = "Full-stack"


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
    # Why each ranked entry outranked the ones behind it: the actual matched
    # keyword terms found in that entry's technologies/skills_demonstrated
    # (etc.) fields, in the same order/positions as `profile`'s ranked
    # entries. An entry with an empty list ranked on tie-break (stable sort
    # preserving original order), not on any real overlap — surfaced so
    # "why this project and not that one" has a real answer instead of none.
    ranking_reasons: dict[str, list[list[str]]]


def _relevance(entry: dict, matched_lower: set[str], *fields: str) -> int:
    terms = {
        term.strip().lower()
        for field in fields
        for term in (entry.get(field) or [])
        if term
    }
    return len(terms & matched_lower)


def _matched_terms(entry: dict, matched_lower: set[str], *fields: str) -> list[str]:
    """The entry's own tag terms (original casing) that overlap
    matched_lower — the human-readable reason this entry ranked where it
    did. Order-preserving, deduplicated case-insensitively."""
    seen_lower: set[str] = set()
    result: list[str] = []
    for field in fields:
        for term in (entry.get(field) or []):
            if not term:
                continue
            term_lower = term.strip().lower()
            if term_lower in matched_lower and term_lower not in seen_lower:
                seen_lower.add(term_lower)
                result.append(term.strip())
    return result


def _sort_section(
    entries: list[dict] | None, matched_lower: set[str], cap: int, *fields: str
) -> tuple[list[dict], list[int], list[list[str]]]:
    if not entries:
        return [], [], []
    indexed = sorted(
        enumerate(entries),
        key=lambda item: _relevance(item[1], matched_lower, *fields),
        reverse=True,
    )[:cap]
    ranked_entries = [entry for _, entry in indexed]
    ranked_indices = [index for index, _ in indexed]
    reasons = [_matched_terms(entry, matched_lower, *fields) for entry in ranked_entries]
    return ranked_entries, ranked_indices, reasons


# ---------------------------------------------------------------------------
# Project ranking — multi-criteria (job relevance/ATS coverage, technical
# depth, impact) plus category diversity, replacing plain tag-overlap
# counting for this section only (work_experience/github_repositories still
# use _sort_section above; projects specifically need a richer signal since
# they're what a recruiter reads closest, per the Projects-redesign plan).
# ---------------------------------------------------------------------------

def _project_evidence_text(project: dict) -> str:
    """Every real fact this project has to offer, flattened and lowercased —
    the search corpus for both keyword coverage and category detection.
    Includes the Phase A structured fields (schemas/profile.py::Project) so
    a project only richly extracted into e.g. `architecture`/`impact`, not
    the flat `technologies` list, still gets full credit."""
    parts = [project.get("description") or "", project.get("problem") or "", project.get("solution") or ""]
    for field in (
        "technologies", "skills_demonstrated", "notable_achievements",
        "architecture", "responsibilities", "technical_achievements", "impact", "deployment",
    ):
        parts.extend(project.get(field) or [])
    return " ".join(parts).lower()


def _project_keyword_score(
    text_lower: str, matched: list[str], evidence_by_keyword: dict[str, KeywordEvidence],
) -> tuple[float, list[str]]:
    """
    How well this project's own evidence covers the job's matched keywords.
    Prefers real per-keyword evidence (crediting a semantic/experience-tier
    match's confidence, not just an exact tag — the whole point of routing
    project ranking through the same keyword_evidence engine as ATS scoring)
    — a project whose real technologies satisfy a semantic keyword (e.g.
    "relational databases" via "Azure SQL") gets credit even without the
    literal job phrase anywhere in its own tags.

    Falls back to a literal substring match at full credit for a keyword
    with no evidence entry (e.g. a caller/test building KeywordReport
    directly without classify_keyword) — the same signal this ranking used
    before evidence-based matching existed, so older callers keep working
    unchanged.
    """
    score = 0.0
    covered: list[str] = []
    for keyword in matched:
        key = keyword.strip().lower()
        if not key:
            continue
        item = evidence_by_keyword.get(key)
        if item is not None:
            if any((piece or "").strip().lower() in text_lower for piece in item.evidence):
                score += item.confidence
                covered.append(keyword)
        elif key in text_lower:
            score += 1.0
            covered.append(keyword)
    return score, covered


def _technical_depth(project: dict) -> float:
    """Deterministic proxy for engineering depth: how many of the
    structured evidence fields are actually populated, plus a small bonus
    for technology-stack diversity. No LLM judgment call — see Part 14's
    determinism-first rule."""
    populated_fields = sum(1 for field in _DEPTH_FIELDS if project.get(field))
    tech_diversity = min(len(project.get("technologies") or []), 5) * 0.3
    return populated_fields + tech_diversity


def _impact_score(project: dict) -> float:
    """Deterministic proxy for measurable impact: populated `impact`
    entries, plus curated outcome-signal words and any digit/percentage
    found in impact/notable_achievements text (an award, a metric, a
    user count)."""
    impact_entries = project.get("impact") or []
    text = " ".join([*impact_entries, *(project.get("notable_achievements") or [])]).lower()
    signal_hits = sum(1 for word in _IMPACT_SIGNAL_WORDS if word in text)
    has_metric = "%" in text or any(ch.isdigit() for ch in text)
    return len(impact_entries) + min(signal_hits, 3) + (1 if has_metric else 0)


def _project_category(text_lower: str) -> str:
    best_category, best_count = _DEFAULT_CATEGORY, 0
    for category, signals in _PROJECT_CATEGORIES:
        count = sum(1 for signal in signals if signal in text_lower)
        if count > best_count:
            best_category, best_count = category, count
    return best_category


def _select_diverse_projects(
    scored: list[tuple[int, dict, float, str, list[str]]], cap: int,
) -> list[tuple[int, dict, float, str, list[str]]]:
    """
    scored is (original_index, project, score, category, covered_keywords),
    already sorted by score descending. Takes the top-scored project
    unconditionally, then for each remaining slot prefers the best-scored
    project from a not-yet-represented category — but only when it scores
    within _DIVERSITY_TOLERANCE of the best remaining project overall, so
    diversity never forces a genuinely weak project in just to fill a
    category quota. Falls back to pure top-by-score once every category is
    already represented (or only one category exists at all).
    """
    if not scored:
        return []
    remaining = list(scored)
    picked = [remaining.pop(0)]
    used_categories = {picked[0][3]}

    while len(picked) < cap and remaining:
        best_overall = remaining[0]
        candidate = next((item for item in remaining if item[3] not in used_categories), None)
        if (
            candidate is not None
            and candidate is not best_overall
            and candidate[2] >= best_overall[2] * _DIVERSITY_TOLERANCE
        ):
            chosen = candidate
        else:
            chosen = best_overall
        picked.append(chosen)
        used_categories.add(chosen[3])
        remaining.remove(chosen)

    return picked


def _rank_projects(
    entries: list[dict] | None, matched: list[str], evidence: list[KeywordEvidence], cap: int,
) -> tuple[list[dict], list[int], list[list[str]]]:
    if not entries:
        return [], [], []

    evidence_by_keyword = {item.keyword.strip().lower(): item for item in evidence}
    scored: list[tuple[int, dict, float, str, list[str]]] = []
    for index, project in enumerate(entries):
        text_lower = _project_evidence_text(project)
        keyword_score, covered = _project_keyword_score(text_lower, matched, evidence_by_keyword)
        score = (
            keyword_score * _WEIGHT_KEYWORD_COVERAGE
            + _technical_depth(project) * _WEIGHT_TECHNICAL_DEPTH
            + _impact_score(project) * _WEIGHT_IMPACT
        )
        scored.append((index, project, score, _project_category(text_lower), covered))

    scored.sort(key=lambda item: item[2], reverse=True)
    picked = _select_diverse_projects(scored, cap)
    picked.sort(key=lambda item: item[2], reverse=True)

    ranked_entries = [item[1] for item in picked]
    ranked_indices = [item[0] for item in picked]
    reasons = [item[4] for item in picked]
    return ranked_entries, ranked_indices, reasons


def rank_profile(profile: dict, keyword_report: KeywordReport) -> RankedProfile:
    """Reorder and trim profile sections so entries relevant to the job's matched keywords come first."""
    matched_lower = {term.lower() for term in keyword_report.matched}

    work_experience, work_experience_indices, work_experience_reasons = _sort_section(
        profile.get("work_experience"), matched_lower, _MAX_WORK_EXPERIENCE,
        "technologies", "skills_demonstrated",
    )
    projects, project_indices, project_reasons = _rank_projects(
        profile.get("projects"), keyword_report.matched, keyword_report.evidence, _MAX_PROJECTS,
    )
    github_repositories, github_repository_indices, github_repository_reasons = _sort_section(
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
        ranking_reasons={
            "work_experience": work_experience_reasons,
            "projects": project_reasons,
            "github_repositories": github_repository_reasons,
        },
    )
