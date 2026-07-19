"""
Builds a synthetic, profile-relative ResumeLayoutDocument so
ResumeGenerationAgent can use the same ContentPatch[]-only contract for every
candidate, regardless of whether they uploaded a source document.

Block ids are minted from the ranked profile dict's own structure (e.g.
"work_experience[0].bullets[1]"), not a real document position — docx_anchor
and pdf_anchor are always None here. The LLM only ever sees and patches these
profile-relative ids; profile_layout_correlator.py separately maps them to
real document block ids (profile.layout_document) for in-place rendering, so
this module stays usable for every profile regardless of source format —
including profiles with no source document at all (LinkedIn/GitHub-only),
where no correlation is possible and generation falls back to the generic
template renderer.
"""

from schemas.resume_layout import LayoutSection, ResumeLayoutDocument, RunSpan, TextBlock

_LIST_SEPARATOR = ", "

_SKILL_GROUP_SOURCES = (
    ("Languages", ("programming_languages",)),
    ("Cloud", ("cloud_platforms",)),
    ("Backend", ("frameworks", "libraries")),
    ("Databases", ("databases",)),
    ("DevOps", ("devops_tools",)),
    ("AI / ML", ("ai_ml_tools",)),
    ("Tools", ("development_tools",)),
    ("Technical", ("technical_skills",)),
)


def build_synthetic_layout(ranked_profile: dict) -> ResumeLayoutDocument:
    blocks: list[TextBlock] = [
        _block("headline", ranked_profile.get("headline") or ""),
        _block("summary", ranked_profile.get("summary") or ""),
        # Blank canvas blocks: these were always LLM-synthesized from the
        # broader profile context (all skill categories; nothing to summarize
        # a wording *change* against), not a lightly-edited existing field.
        _block("skills", ""),
        _block("changes_summary", ""),
    ]

    for i, entry in enumerate(ranked_profile.get("work_experience") or []):
        for j, bullet in enumerate(entry.get("bullets") or []):
            blocks.append(_block(f"work_experience[{i}].bullets[{j}]", bullet or ""))

    for i, project in enumerate(ranked_profile.get("projects") or []):
        blocks.append(_block(f"projects[{i}].description", project.get("description") or ""))
        blocks.append(_block(f"projects[{i}].technologies", join_comma_list(project.get("technologies"))))

    return ResumeLayoutDocument(source_format="synthetic", sections=[LayoutSection(section_id="profile", blocks=blocks)])


def flatten_layout_to_resume(ranked_profile: dict, layout: ResumeLayoutDocument) -> dict:
    """
    Inverse of build_synthetic_layout: reads the (already patched) layout's
    block text back into the exact external shape OptimizedResume expects.

    Fields the LLM was never given a block_id for at all — title, company,
    dates, entry order and count — are copied straight through from
    ranked_profile, so they can't change no matter what patches say. Any
    block with no matching patch simply keeps the placeholder text
    build_synthetic_layout gave it, rather than erroring.
    """
    text_by_id = {block.block_id: block.text for section in layout.sections for block in section.blocks}

    experience = []
    for i, entry in enumerate(ranked_profile.get("work_experience") or []):
        bullet_count = len(entry.get("bullets") or [])
        experience.append({
            "title": entry.get("title"),
            "company": entry.get("company"),
            "location": entry.get("location"),
            "start_date": entry.get("start_date"),
            "end_date": entry.get("end_date"),
            "bullets": [text_by_id[f"work_experience[{i}].bullets[{j}]"] for j in range(bullet_count)],
        })

    projects = []
    for i, project in enumerate(ranked_profile.get("projects") or []):
        projects.append({
            "name": project.get("name"),
            "description": text_by_id[f"projects[{i}].description"] or None,
            "url": project.get("url"),
            "technologies": split_comma_list(text_by_id[f"projects[{i}].technologies"]),
            "bullets": [item for item in [
                text_by_id[f"projects[{i}].description"] or "",
                *project.get("notable_achievements", []),
            ] if item],
        })

    skills = split_comma_list(text_by_id["skills"])

    return {
        "name": ranked_profile.get("name"),
        "email": ranked_profile.get("email"),
        "phone": ranked_profile.get("phone"),
        "headline": text_by_id["headline"] or None,
        "summary": text_by_id["summary"] or None,
        "links": _normalize_links(ranked_profile.get("links") or {}),
        "skills": skills,
        "skill_groups": _build_skill_groups(ranked_profile, skills),
        "experience": experience,
        "projects": projects,
        "education": ranked_profile.get("education") or [],
        "certifications": ranked_profile.get("certifications") or [],
        "awards": ranked_profile.get("awards") or ranked_profile.get("achievements") or [],
        "leadership": ranked_profile.get("leadership_experience") or [],
        "volunteering": ranked_profile.get("volunteer_work") or [],
        "publications": ranked_profile.get("publications") or [],
        "interests": ranked_profile.get("interests") or [],
        "references": ranked_profile.get("references") or [],
        "changes_summary": [line.strip() for line in text_by_id["changes_summary"].split("\n") if line.strip()],
    }


def _block(block_id: str, text: str) -> TextBlock:
    return TextBlock(block_id=block_id, kind="paragraph", text=text, runs=[RunSpan(text=text)])


def join_comma_list(items: list[str] | None) -> str:
    return _LIST_SEPARATOR.join(items) if items else ""


def split_comma_list(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]


def _build_skill_groups(ranked_profile: dict, optimized_skills: list[str]) -> list[dict]:
    profile_items_by_group: list[tuple[str, list[str]]] = []
    used_profile_items: set[str] = set()
    for label, fields in _SKILL_GROUP_SOURCES:
        items = _unique_items(
            item
            for field in fields
            for item in (ranked_profile.get(field) or [])
        )
        if items:
            profile_items_by_group.append((label, items))
            used_profile_items.update(_normalize_skill(item) for item in items)

    if not optimized_skills:
        return [{"label": label, "items": items} for label, items in profile_items_by_group]

    grouped: list[dict] = []
    assigned: set[str] = set()
    for label, profile_items in profile_items_by_group:
        profile_lookup = {_normalize_skill(item): item for item in profile_items}
        items = [
            skill
            for skill in optimized_skills
            if _normalize_skill(skill) in profile_lookup and _normalize_skill(skill) not in assigned
        ]
        if items:
            grouped.append({"label": label, "items": items})
            assigned.update(_normalize_skill(item) for item in items)

    uncategorized = [
        skill
        for skill in optimized_skills
        if _normalize_skill(skill) not in assigned and _normalize_skill(skill) not in used_profile_items
    ]
    if uncategorized:
        grouped.append({"label": "Additional", "items": uncategorized})

    return grouped


def _unique_items(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item:
            continue
        key = _normalize_skill(str(item))
        if key in seen:
            continue
        seen.add(key)
        result.append(str(item))
    return result


def _normalize_skill(item: str) -> str:
    return item.strip().lower()


def _normalize_links(links: dict) -> dict:
    normalized: dict[str, str] = {}
    for key, value in links.items():
        if not value:
            continue
        link_key = str(key).strip().lower().replace("_url", "")
        normalized[link_key] = str(value)
    return normalized
