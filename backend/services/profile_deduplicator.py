"""
Deduplicates a CandidateProfile dict after LLM extraction.

CandidateProfileAgent's system prompt asks the model to merge the same info
from multiple sources (resume + LinkedIn + portfolio often describe the same
job or project) into one entry, but that's advisory only — in practice the
model routinely returns two near-identical entries when the same real job or
project is described slightly differently across sources. This runs as a
deterministic safety net after every analyze() call, not a replacement for
the prompt instruction.
"""

from difflib import SequenceMatcher

# How similar two key-field values (e.g. two job titles) must be to be
# treated as "the same", once both are non-empty. High on purpose — this
# only needs to catch minor rewording/formatting drift across sources
# ("Co.Donegal" vs "County Donegal, Ireland"), not judge whether two
# genuinely different jobs happen to sound alike.
_ENTRY_MATCH_THRESHOLD = 0.85

_STRING_LIST_FIELDS = (
    "technical_skills", "soft_skills", "programming_languages", "frameworks",
    "libraries", "databases", "cloud_platforms", "devops_tools", "ai_ml_tools",
    "development_tools", "open_source_contributions", "awards", "achievements",
    "leadership_experience", "volunteer_work", "publications", "interests", "references",
)

# How much of a bullet's significant words must already appear somewhere in
# an earlier bullet/description before it's dropped as restating the same
# point. Lower than _ENTRY_MATCH_THRESHOLD on purpose: two *entries* being
# merged needs near-certainty they're the same real job/project, but two
# *bullets* within the one entry restating the same fact in slightly
# different words is a much more common, less risky thing to collapse —
# the worst case of a false positive here is losing one redundant-sounding
# but genuinely distinct bullet, not merging two unrelated jobs.
#
# Word-overlap, not character overlap: two short bullets that share a common
# scaffold ("Did X" / "Did Y") can be 80%+ similar by longest-contiguous-
# character-run while describing completely different things, since the
# characters that actually differ are a small fraction of the string. Whole
# significant words are a much more reliable unit for "says the same thing."
_BULLET_OVERLAP_THRESHOLD = 0.6

_STOPWORDS = {"a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with", "did"}


def dedupe_profile(profile: dict) -> dict:
    profile = dict(profile)

    for field in _STRING_LIST_FIELDS:
        if field in profile:
            profile[field] = _dedupe_strings(profile.get(field) or [])

    profile["work_experience"] = _dedupe_entries(
        profile.get("work_experience") or [],
        key_fields=("title", "company"),
        list_fields=("bullets", "technologies", "skills_demonstrated"),
    )
    profile["work_experience"] = [
        {**entry, "bullets": _dedupe_similar_texts(entry.get("bullets") or [])}
        for entry in profile["work_experience"]
    ]

    profile["projects"] = _dedupe_entries(
        profile.get("projects") or [],
        key_fields=("name",),
        list_fields=("technologies", "skills_demonstrated", "notable_achievements"),
        text_fields=("description",),
    )
    profile["projects"] = [
        {
            **project,
            "notable_achievements": _dedupe_similar_texts(
                project.get("notable_achievements") or [], against=[project.get("description") or ""],
            ),
        }
        for project in profile["projects"]
    ]
    profile["education"] = _dedupe_entries(
        profile.get("education") or [],
        key_fields=("institution", "degree"),
        list_fields=("achievements",),
    )
    profile["github_repositories"] = _dedupe_entries(
        profile.get("github_repositories") or [],
        key_fields=("name",),
        list_fields=("languages", "frameworks", "technologies", "skills_demonstrated"),
        text_fields=("description", "purpose"),
    )
    profile["certifications"] = _dedupe_entries(
        profile.get("certifications") or [],
        key_fields=("name", "issuer"),
    )

    return profile


def merge_overlapping_bullets(optimized_resume: dict) -> dict:
    """
    Second dedup pass, run on ResumeGenerationAgent's final output after
    every bullet has been reworded. dedupe_profile above runs pre-generation
    on the raw candidate profile and can only prevent overlap the LLM didn't
    itself introduce — the tailoring step can still leave two bullets
    covering the same ground (a project bullet and a notable_achievement
    both restating one outcome, worded differently by the model), since
    patch_engine only ever rewrites a block_id's text and can't drop one
    (see resume_generation_agent.py's patch-only contract). Once bullets are
    flattened into optimized_resume's plain lists there's no block_id left
    to preserve, so this can safely drop one outright rather than just
    reword it.
    """
    optimized_resume = dict(optimized_resume)

    optimized_resume["experience"] = [
        {**entry, "bullets": _dedupe_similar_texts(entry.get("bullets") or [])}
        for entry in optimized_resume.get("experience") or []
    ]
    optimized_resume["projects"] = [
        {**project, "bullets": _dedupe_similar_texts(project.get("bullets") or [])}
        for project in optimized_resume.get("projects") or []
    ]

    return optimized_resume


def _normalize(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item:
            continue
        key = _normalize(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(str(item))
    return result


def _entries_match(a: dict, b: dict, key_fields: tuple[str, ...]) -> bool:
    """
    All key_fields that are non-empty on both sides must match (exactly or
    via similarity); at least one field pair must actually be comparable, so
    two entries that are both missing every key field are never merged just
    because neither has a name.
    """
    comparable = False
    for field in key_fields:
        norm_a = _normalize(a.get(field) or "")
        norm_b = _normalize(b.get(field) or "")
        if not norm_a or not norm_b:
            continue
        comparable = True
        if norm_a == norm_b:
            continue
        if SequenceMatcher(None, norm_a, norm_b).ratio() >= _ENTRY_MATCH_THRESHOLD:
            continue
        return False
    return comparable


def _merge_entries(
    base: dict, other: dict, list_fields: tuple[str, ...], text_fields: tuple[str, ...]
) -> dict:
    merged = dict(base)

    for field in list_fields:
        merged[field] = _dedupe_strings([*(base.get(field) or []), *(other.get(field) or [])])

    for field in text_fields:
        base_text = base.get(field) or ""
        other_text = other.get(field) or ""
        merged[field] = base_text if len(base_text) >= len(other_text) else other_text

    # Fill any field left null/empty on the kept entry from the duplicate,
    # instead of silently dropping detail the duplicate had and base didn't.
    for field, value in other.items():
        if field in list_fields or field in text_fields:
            continue
        if not merged.get(field) and value:
            merged[field] = value

    return merged


def _dedupe_entries(
    entries: list[dict],
    key_fields: tuple[str, ...],
    list_fields: tuple[str, ...] = (),
    text_fields: tuple[str, ...] = (),
) -> list[dict]:
    kept: list[dict] = []
    for entry in entries:
        match_index = next(
            (i for i, existing in enumerate(kept) if _entries_match(existing, entry, key_fields)),
            None,
        )
        if match_index is None:
            kept.append(dict(entry))
        else:
            kept[match_index] = _merge_entries(kept[match_index], entry, list_fields, text_fields)
    return kept


def _dedupe_similar_texts(texts: list[str], against: list[str] = ()) -> list[str]:
    """
    Keeps each text in `texts` unless most of its significant words already
    appear in `against` or in an earlier kept text — collapses a project's
    own notable_achievements restating its own description, or one
    work_experience bullet restating another, the way a resume bullet-izes
    the same paragraph into several near-identical points. This is a
    within-entry concern, distinct from _dedupe_entries above (which merges
    duplicate *entries*, not duplicate *lines inside one entry*) — the LLM
    that later tailors wording can only reword a bullet, never remove one
    (see resume_generation_agent.py's patch-only contract), so this has to
    run before that step, not after.
    """
    kept: list[str] = []
    reference_pool = [_normalize(text) for text in against if text]
    for text in texts:
        if not text:
            continue
        normalized = _normalize(text)
        if any(_is_substantially_contained(normalized, reference) for reference in reference_pool):
            continue
        kept.append(text)
        reference_pool.append(normalized)
    return kept


def _significant_words(text: str) -> list[str]:
    return [word for word in text.split() if word not in _STOPWORDS and len(word) > 2]


def _is_substantially_contained(short_text: str, long_text: str) -> bool:
    if not short_text or not long_text:
        return False
    words = _significant_words(short_text)
    if not words:
        return False
    long_words = set(_significant_words(long_text))
    matched = sum(1 for word in words if word in long_words)
    return matched / len(words) >= _BULLET_OVERLAP_THRESHOLD
