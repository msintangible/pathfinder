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
        blocks.append(_block(f"projects[{i}].technologies", _join(project.get("technologies"))))

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
            "start_date": entry.get("start_date"),
            "end_date": entry.get("end_date"),
            "bullets": [text_by_id[f"work_experience[{i}].bullets[{j}]"] for j in range(bullet_count)],
        })

    projects = []
    for i, project in enumerate(ranked_profile.get("projects") or []):
        projects.append({
            "name": project.get("name"),
            "description": text_by_id[f"projects[{i}].description"] or None,
            "technologies": _split(text_by_id[f"projects[{i}].technologies"]),
        })

    return {
        "headline": text_by_id["headline"] or None,
        "summary": text_by_id["summary"] or None,
        "skills": _split(text_by_id["skills"]),
        "experience": experience,
        "projects": projects,
        "changes_summary": [line.strip() for line in text_by_id["changes_summary"].split("\n") if line.strip()],
    }


def _block(block_id: str, text: str) -> TextBlock:
    return TextBlock(block_id=block_id, kind="paragraph", text=text, runs=[RunSpan(text=text)])


def _join(items: list[str] | None) -> str:
    return _LIST_SEPARATOR.join(items) if items else ""


def _split(text: str) -> list[str]:
    return [item.strip() for item in text.split(",") if item.strip()]
