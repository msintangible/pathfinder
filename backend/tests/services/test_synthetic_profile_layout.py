from services.synthetic_profile_layout import build_synthetic_layout, flatten_layout_to_resume


def _block_by_id(layout, block_id: str):
    for section in layout.sections:
        for block in section.blocks:
            if block.block_id == block_id:
                return block
    raise AssertionError(f"block_id not found: {block_id}")


_PROFILE = {
    "headline": "Backend Engineer",
    "summary": "Experienced with Python and AWS.",
    "work_experience": [
        {
            "title": "Software Engineer",
            "company": "Acme Corp",
            "start_date": "2020",
            "end_date": "Present",
            "bullets": ["Built APIs", "Reduced latency by 40%"],
        },
        {
            "title": "Junior Engineer",
            "company": "Startup Inc",
            "start_date": "2018",
            "end_date": "2020",
            "bullets": ["Wrote tests"],
        },
    ],
    "projects": [
        {"name": "pathfinder", "description": "Job application assistant", "technologies": ["Python", "React"]},
    ],
}


# ---------------------------------------------------------------------------
# build_synthetic_layout
# ---------------------------------------------------------------------------

def test_build_creates_headline_and_summary_blocks_with_original_text():
    layout = build_synthetic_layout(_PROFILE)

    assert _block_by_id(layout, "headline").text == "Backend Engineer"
    assert _block_by_id(layout, "summary").text == "Experienced with Python and AWS."


def test_build_creates_blank_canvas_blocks_for_skills_and_changes_summary():
    layout = build_synthetic_layout(_PROFILE)

    assert _block_by_id(layout, "skills").text == ""
    assert _block_by_id(layout, "changes_summary").text == ""


def test_build_creates_one_block_per_bullet_per_entry():
    layout = build_synthetic_layout(_PROFILE)

    assert _block_by_id(layout, "work_experience[0].bullets[0]").text == "Built APIs"
    assert _block_by_id(layout, "work_experience[0].bullets[1]").text == "Reduced latency by 40%"
    assert _block_by_id(layout, "work_experience[1].bullets[0]").text == "Wrote tests"


def test_build_creates_project_description_and_joined_technologies_blocks():
    layout = build_synthetic_layout(_PROFILE)

    assert _block_by_id(layout, "projects[0].description").text == "Job application assistant"
    assert _block_by_id(layout, "projects[0].technologies").text == "Python, React"


def test_build_creates_no_blocks_for_empty_experience_and_projects():
    layout = build_synthetic_layout({"headline": None, "summary": None})
    block_ids = {block.block_id for section in layout.sections for block in section.blocks}

    assert not any(bid.startswith("work_experience") for bid in block_ids)
    assert not any(bid.startswith("projects") for bid in block_ids)
    assert block_ids == {"headline", "summary", "skills", "changes_summary"}


# ---------------------------------------------------------------------------
# flatten_layout_to_resume
# ---------------------------------------------------------------------------

def test_flatten_reflects_patched_text():
    layout = build_synthetic_layout(_PROFILE)
    _block_by_id(layout, "headline").text = "Senior Backend Engineer"
    _block_by_id(layout, "skills").text = "Python, AWS, Docker"
    _block_by_id(layout, "work_experience[0].bullets[0]").text = "Built scalable APIs"
    _block_by_id(layout, "changes_summary").text = "Emphasized Python experience.\nHighlighted AWS work."

    resume = flatten_layout_to_resume(_PROFILE, layout)

    assert resume["headline"] == "Senior Backend Engineer"
    assert resume["skills"] == ["Python", "AWS", "Docker"]
    assert resume["experience"][0]["bullets"][0] == "Built scalable APIs"
    assert resume["changes_summary"] == ["Emphasized Python experience.", "Highlighted AWS work."]


def test_flatten_without_any_patches_keeps_placeholder_text():
    layout = build_synthetic_layout(_PROFILE)

    resume = flatten_layout_to_resume(_PROFILE, layout)

    assert resume["headline"] == "Backend Engineer"
    assert resume["experience"][0]["bullets"] == ["Built APIs", "Reduced latency by 40%"]
    assert resume["skills"] == []  # blank canvas, never patched
    assert resume["changes_summary"] == []


def test_flatten_preserves_title_company_and_dates_unconditionally():
    layout = build_synthetic_layout(_PROFILE)
    # Mutate every editable block to nonsense — title/company/dates must be
    # entirely unreachable from block text, since no block_id ever represents them.
    for section in layout.sections:
        for block in section.blocks:
            block.text = "anything"

    resume = flatten_layout_to_resume(_PROFILE, layout)

    assert resume["experience"][0]["title"] == "Software Engineer"
    assert resume["experience"][0]["company"] == "Acme Corp"
    assert resume["experience"][0]["start_date"] == "2020"
    assert resume["experience"][0]["end_date"] == "Present"


def test_flatten_preserves_entry_count_and_order_unconditionally():
    layout = build_synthetic_layout(_PROFILE)

    resume = flatten_layout_to_resume(_PROFILE, layout)

    assert len(resume["experience"]) == 2
    assert [e["company"] for e in resume["experience"]] == ["Acme Corp", "Startup Inc"]


def test_flatten_handles_profiles_with_no_experience_or_projects():
    layout = build_synthetic_layout({"headline": "X"})

    resume = flatten_layout_to_resume({"headline": "X"}, layout)

    assert resume["experience"] == []
    assert resume["projects"] == []


def test_flatten_null_headline_and_summary_stay_null_when_never_patched():
    profile = {"headline": None, "summary": None}
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["headline"] is None
    assert resume["summary"] is None
