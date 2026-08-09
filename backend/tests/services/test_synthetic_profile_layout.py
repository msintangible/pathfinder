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


def test_build_creates_one_block_per_project_achievement():
    profile = {
        "projects": [
            {"name": "pathfinder", "description": "Job assistant", "notable_achievements": ["500 stars", "Featured on HN"]},
        ],
    }

    layout = build_synthetic_layout(profile)

    assert _block_by_id(layout, "projects[0].achievements[0]").text == "500 stars"
    assert _block_by_id(layout, "projects[0].achievements[1]").text == "Featured on HN"


# ---------------------------------------------------------------------------
# Purpose-driven project bullets (Phase D of the Projects redesign)
# ---------------------------------------------------------------------------

def test_build_creates_blank_canvas_purpose_blocks_when_structured_evidence_exists():
    profile = {"projects": [{
        "name": "distill", "description": "AI meeting tool.",
        "architecture": ["FastAPI WebSocket backend"],
        "technical_achievements": ["Sub-second transcription latency"],
        "impact": ["Won Best Use of ElevenLabs at HackBelfast 2026"],
    }]}

    layout = build_synthetic_layout(profile)

    assert _block_by_id(layout, "projects[0].architecture_bullet").text == ""
    assert _block_by_id(layout, "projects[0].technical_achievement_bullet").text == ""
    assert _block_by_id(layout, "projects[0].impact_bullet").text == ""


def test_build_only_creates_purpose_blocks_for_fields_with_real_evidence():
    """A project with only technical_achievements populated must not get an
    architecture_bullet or impact_bullet block — never force a bullet slot
    the LLM would have to pad with filler."""
    profile = {"projects": [{"name": "x", "technical_achievements": ["Optimized query performance"]}]}

    layout = build_synthetic_layout(profile)
    block_ids = {block.block_id for section in layout.sections for block in section.blocks}

    assert "projects[0].technical_achievement_bullet" in block_ids
    assert "projects[0].architecture_bullet" not in block_ids
    assert "projects[0].impact_bullet" not in block_ids


def test_build_falls_back_to_notable_achievements_when_no_structured_fields_exist():
    """A project extracted before Phase A (no architecture/technical_achievements/
    impact populated) must render exactly like before — legacy
    notable_achievements-driven achievement blocks, no purpose blocks."""
    profile = {"projects": [{"name": "x", "notable_achievements": ["500 stars"]}]}

    layout = build_synthetic_layout(profile)
    block_ids = {block.block_id for section in layout.sections for block in section.blocks}

    assert "projects[0].achievements[0]" in block_ids
    assert not any(b.endswith("_bullet") for b in block_ids)


def test_build_fills_remaining_slots_with_achievements_when_purpose_fields_are_sparse():
    """Only 1 of the 3 purpose fields populated leaves 2 slots — real
    notable_achievements content should fill them rather than being
    silently dropped, up to the shared 3-extra-bullet cap."""
    profile = {"projects": [{
        "name": "x",
        "technical_achievements": ["Optimized query performance"],
        "notable_achievements": ["500 stars", "Featured on HN", "1000 downloads"],
    }]}

    layout = build_synthetic_layout(profile)
    block_ids = {block.block_id for section in layout.sections for block in section.blocks}

    assert "projects[0].technical_achievement_bullet" in block_ids
    assert "projects[0].achievements[0]" in block_ids
    assert "projects[0].achievements[1]" in block_ids
    # Cap is 3 extra bullets total: 1 purpose block + 2 achievements, third dropped.
    assert "projects[0].achievements[2]" not in block_ids
    assert _block_by_id(layout, "projects[0].achievements[0]").text == "500 stars"


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


def test_flatten_reflects_patched_project_achievement_text():
    profile = {
        "projects": [
            {"name": "pathfinder", "description": "Job assistant", "notable_achievements": ["500 stars"]},
        ],
    }
    layout = build_synthetic_layout(profile)
    _block_by_id(layout, "projects[0].achievements[0]").text = "500 GitHub stars and 50 forks"

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["projects"][0]["bullets"] == ["Job assistant", "500 GitHub stars and 50 forks"]


def test_flatten_reflects_patched_purpose_bullet_text():
    profile = {"projects": [{
        "name": "distill", "description": "AI meeting tool.",
        "architecture": ["FastAPI WebSocket backend"],
        "impact": ["Won Best Use of ElevenLabs at HackBelfast 2026"],
    }]}
    layout = build_synthetic_layout(profile)
    _block_by_id(layout, "projects[0].architecture_bullet").text = (
        "Designed a real-time FastAPI WebSocket architecture for live audio processing."
    )
    _block_by_id(layout, "projects[0].impact_bullet").text = (
        "Won Best Use of ElevenLabs at HackBelfast 2026."
    )

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["projects"][0]["bullets"] == [
        "AI meeting tool.",
        "Designed a real-time FastAPI WebSocket architecture for live audio processing.",
        "Won Best Use of ElevenLabs at HackBelfast 2026.",
    ]


def test_flatten_omits_an_unpatched_blank_purpose_bullet():
    """A purpose block that never got patched (e.g. the model left it blank
    despite the block existing) must not render as an empty bullet string."""
    profile = {"projects": [{"name": "x", "description": "A tool.", "impact": ["Won an award"]}]}
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["projects"][0]["bullets"] == ["A tool."]


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


# ---------------------------------------------------------------------------
# links (see _normalize_links / _ensure_scheme)
# ---------------------------------------------------------------------------

def test_flatten_adds_https_scheme_to_a_bare_link():
    """Regression test: a link stored without a scheme (e.g. as a resume
    literally prints it, "linkedin.com/in/jane") renders as a real <a href>
    verbatim — without a scheme that's not an absolute URL, so the link is
    unclickable/dead in the PDF."""
    profile = {"links": {"linkedin": "linkedin.com/in/jane", "github": "github.com/jane"}}
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["links"]["linkedin"] == "https://linkedin.com/in/jane"
    assert resume["links"]["github"] == "https://github.com/jane"


def test_flatten_leaves_a_link_that_already_has_a_scheme_untouched():
    profile = {"links": {"linkedin": "https://linkedin.com/in/jane", "portfolio": "http://jane.dev"}}
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["links"]["linkedin"] == "https://linkedin.com/in/jane"
    assert resume["links"]["portfolio"] == "http://jane.dev"


def test_flatten_uses_explicit_source_urls_when_no_freeform_links_extracted():
    """Regression test: linkedin_url/github_url/portfolio_url are real,
    user-provided UserProfile columns (see schemas/profile.py's
    CandidateProfile) — they must reach the rendered resume even when the
    profile-analysis LLM never independently re-extracted the same URL into
    the freeform `links` dict."""
    profile = {
        "linkedin_url": "https://linkedin.com/in/jane",
        "github_url": "https://github.com/jane",
        "portfolio_url": "https://jane.dev",
    }
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["links"]["linkedin"] == "https://linkedin.com/in/jane"
    assert resume["links"]["github"] == "https://github.com/jane"
    assert resume["links"]["portfolio"] == "https://jane.dev"


def test_flatten_prefers_explicit_source_url_over_freeform_link_for_the_same_key():
    """The user deliberately typed linkedin_url into the import form — that
    must win over whatever the LLM happened to freeform-extract into `links`
    for the same key (e.g. a stale or differently-cased URL from resume text)."""
    profile = {
        "links": {"linkedin": "linkedin.com/in/jane-old-handle"},
        "linkedin_url": "https://linkedin.com/in/jane-current",
    }
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["links"]["linkedin"] == "https://linkedin.com/in/jane-current"


def test_flatten_keeps_freeform_link_for_a_key_with_no_explicit_source_url():
    """A freeform-extracted link (e.g. a Stack Overflow profile mentioned in
    resume text) has no explicit form field — it must still come through."""
    profile = {
        "links": {"stackoverflow": "stackoverflow.com/users/12345"},
        "linkedin_url": "https://linkedin.com/in/jane",
    }
    layout = build_synthetic_layout(profile)

    resume = flatten_layout_to_resume(profile, layout)

    assert resume["links"]["stackoverflow"] == "https://stackoverflow.com/users/12345"
    assert resume["links"]["linkedin"] == "https://linkedin.com/in/jane"
