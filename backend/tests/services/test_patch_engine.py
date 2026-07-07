from schemas.resume_layout import (
    ContentPatch,
    LayoutSection,
    ResumeLayoutDocument,
    RunSpan,
    SectionRole,
    TextBlock,
)
from services.patch_engine import apply_patches


def _document(*sections: LayoutSection) -> ResumeLayoutDocument:
    return ResumeLayoutDocument(source_format="docx", sections=list(sections))


def _block(block_id: str, text: str, runs: list[RunSpan] | None = None, kind: str = "paragraph") -> TextBlock:
    return TextBlock(block_id=block_id, kind=kind, text=text, runs=runs if runs is not None else [RunSpan(text=text)])


def _block_by_id(document: ResumeLayoutDocument, block_id: str) -> TextBlock:
    for section in document.sections:
        for block in section.blocks:
            if block.block_id == block_id:
                return block
    raise AssertionError(f"block_id not found: {block_id}")


# ---------------------------------------------------------------------------
# Single-run replace
# ---------------------------------------------------------------------------

def test_single_run_block_is_replaced_directly():
    document = _document(LayoutSection(
        section_id="s0",
        blocks=[_block("p[0]", "Built APIs.", [RunSpan(text="Built APIs.", bold=True)])],
    ))

    result = apply_patches(document, [ContentPatch(block_id="p[0]", new_text="Built scalable APIs.")])

    block = _block_by_id(result.document, "p[0]")
    assert block.text == "Built scalable APIs."
    assert len(block.runs) == 1
    assert block.runs[0].text == "Built scalable APIs."
    assert block.runs[0].bold is True  # formatting preserved


def test_block_with_no_runs_gets_a_new_plain_run():
    document = _document(LayoutSection(section_id="s0", blocks=[_block("p[0]", "Old.", runs=[])]))

    result = apply_patches(document, [ContentPatch(block_id="p[0]", new_text="New.")])

    block = _block_by_id(result.document, "p[0]")
    assert [r.text for r in block.runs] == ["New."]


# ---------------------------------------------------------------------------
# Multi-run word-level redistribution
# ---------------------------------------------------------------------------

def test_multi_run_redistribution_keeps_proportional_word_share():
    # Run 0 originally held 2 of 4 words (50%), run 1 held the other 2 (50%).
    runs = [
        RunSpan(text="Built scalable", bold=True),
        RunSpan(text="backend APIs.", bold=False),
    ]
    document = _document(LayoutSection(section_id="s0", blocks=[_block("p[0]", "Built scalable backend APIs.", runs)]))

    result = apply_patches(document, [ContentPatch(block_id="p[0]", new_text="Led the design of new backend services.")])

    block = _block_by_id(result.document, "p[0]")
    assert len(block.runs) == 2
    # 7 new words, 50/50 split, remainder to run 0 -> 4 words / 3 words.
    assert block.runs[0].text == "Led the design of"
    assert block.runs[1].text == "new backend services."
    assert block.runs[0].bold is True
    assert block.runs[1].bold is False


def test_multi_run_redistribution_uses_largest_remainder_for_uneven_split():
    # Run 0 held 1 of 3 words (1/3), run 1 held 2 of 3 (2/3).
    runs = [RunSpan(text="Led"), RunSpan(text="the team")]
    document = _document(LayoutSection(section_id="s0", blocks=[_block("p[0]", "Led the team", runs)]))

    # 7 new words: raw shares are 2.33 / 4.67 -> floor to 2 / 4 with one word left
    # over, which the largest-remainder method gives to run 1 (bigger fractional part).
    result = apply_patches(document, [ContentPatch(block_id="p[0]", new_text="Directed a growing team of five engineers")])

    block = _block_by_id(result.document, "p[0]")
    words = " ".join(r.text for r in block.runs).split()
    assert words == "Directed a growing team of five engineers".split()
    assert len(block.runs[0].text.split()) == 2
    assert len(block.runs[1].text.split()) == 5


def test_multi_run_falls_back_to_first_run_when_original_runs_are_empty():
    runs = [RunSpan(text=""), RunSpan(text="")]
    document = _document(LayoutSection(section_id="s0", blocks=[_block("p[0]", "", runs)]))

    result = apply_patches(document, [ContentPatch(block_id="p[0]", new_text="Brand new bullet point.")])

    block = _block_by_id(result.document, "p[0]")
    assert block.runs[0].text == "Brand new bullet point."
    assert block.runs[1].text == ""


# ---------------------------------------------------------------------------
# Skills-section cap-and-replace-in-place
# ---------------------------------------------------------------------------

def test_skills_section_replaces_one_item_per_run_matching_count():
    runs = [RunSpan(text="Python, "), RunSpan(text="Django, "), RunSpan(text="PostgreSQL")]
    document = _document(LayoutSection(
        section_id="s0", role=SectionRole.SKILLS,
        blocks=[_block("skills[0]", "Python, Django, PostgreSQL", runs)],
    ))

    result = apply_patches(document, [ContentPatch(block_id="skills[0]", new_text="Go, Kubernetes, Terraform")])

    block = _block_by_id(result.document, "skills[0]")
    assert [r.text for r in block.runs] == ["Go, ", "Kubernetes, ", "Terraform"]


def test_skills_section_clears_unused_runs_when_fewer_new_items():
    runs = [RunSpan(text="Python, "), RunSpan(text="Django, "), RunSpan(text="PostgreSQL")]
    document = _document(LayoutSection(
        section_id="s0", role=SectionRole.SKILLS,
        blocks=[_block("skills[0]", "Python, Django, PostgreSQL", runs)],
    ))

    result = apply_patches(document, [ContentPatch(block_id="skills[0]", new_text="Go, Kubernetes")])

    block = _block_by_id(result.document, "skills[0]")
    assert [r.text for r in block.runs] == ["Go, ", "Kubernetes", ""]


def test_skills_section_caps_overflow_items_into_last_run():
    runs = [RunSpan(text="Python, "), RunSpan(text="Django")]
    document = _document(LayoutSection(
        section_id="s0", role=SectionRole.SKILLS,
        blocks=[_block("skills[0]", "Python, Django", runs)],
    ))

    result = apply_patches(
        document, [ContentPatch(block_id="skills[0]", new_text="Go, Kubernetes, Terraform, AWS")]
    )

    block = _block_by_id(result.document, "skills[0]")
    assert block.runs[0].text == "Go, "
    assert block.runs[1].text == "Kubernetes, Terraform, AWS"


def test_skills_section_without_a_detected_separator_falls_back_to_word_alignment():
    # No comma/pipe/semicolon/bullet in the original text -> not treated as a delimited list.
    runs = [RunSpan(text="Strong"), RunSpan(text="communication skills")]
    document = _document(LayoutSection(
        section_id="s0", role=SectionRole.SKILLS,
        blocks=[_block("skills[0]", "Strong communication skills", runs)],
    ))

    result = apply_patches(document, [ContentPatch(block_id="skills[0]", new_text="Excellent written communication")])

    block = _block_by_id(result.document, "skills[0]")
    assert " ".join(r.text for r in block.runs).split() == "Excellent written communication".split()


# ---------------------------------------------------------------------------
# Hyperlink runs are pinned, never rewritten
# ---------------------------------------------------------------------------

def test_hyperlink_run_keeps_its_original_text_and_url():
    runs = [
        RunSpan(text="Built APIs for "),
        RunSpan(text="GitHub", hyperlink_url="https://github.com/example"),
        RunSpan(text=" using Python."),
    ]
    document = _document(LayoutSection(
        section_id="s0",
        blocks=[_block("p[0]", "Built APIs for GitHub using Python.", runs)],
    ))

    result = apply_patches(
        document, [ContentPatch(block_id="p[0]", new_text="Engineered RESTful APIs using Python and AWS.")]
    )

    block = _block_by_id(result.document, "p[0]")
    assert block.runs[1].text == "GitHub"
    assert block.runs[1].hyperlink_url == "https://github.com/example"


def test_new_text_is_redistributed_only_across_non_hyperlink_runs():
    runs = [
        RunSpan(text="Built APIs for "),
        RunSpan(text="GitHub", hyperlink_url="https://github.com/example"),
        RunSpan(text=" using Python."),
    ]
    document = _document(LayoutSection(
        section_id="s0",
        blocks=[_block("p[0]", "Built APIs for GitHub using Python.", runs)],
    ))

    result = apply_patches(
        document, [ContentPatch(block_id="p[0]", new_text="Engineered RESTful APIs using Python and AWS.")]
    )

    block = _block_by_id(result.document, "p[0]")
    non_hyperlink_words = " ".join(r.text for r in block.runs if r.hyperlink_url is None).split()
    assert non_hyperlink_words == "Engineered RESTful APIs using Python and AWS.".split()
    # The pinned run's own words never got merged into the surrounding text.
    assert "GitHub" not in non_hyperlink_words


def test_block_that_is_only_a_hyperlink_is_left_completely_unchanged():
    runs = [RunSpan(text="https://myportfolio.dev", hyperlink_url="https://myportfolio.dev")]
    document = _document(LayoutSection(
        section_id="s0", blocks=[_block("p[0]", "https://myportfolio.dev", runs)],
    ))

    result = apply_patches(document, [ContentPatch(block_id="p[0]", new_text="My Portfolio")])

    block = _block_by_id(result.document, "p[0]")
    assert block.runs[0].text == "https://myportfolio.dev"


# ---------------------------------------------------------------------------
# Table-cell blocks
# ---------------------------------------------------------------------------

def test_table_cell_block_is_patched_like_any_other_block():
    document = _document(LayoutSection(
        section_id="s0",
        blocks=[_block("table[0].row[0].col[0].paragraph[0]", "Python", kind="table_cell")],
    ))

    result = apply_patches(
        document, [ContentPatch(block_id="table[0].row[0].col[0].paragraph[0]", new_text="Go")]
    )

    block = _block_by_id(result.document, "table[0].row[0].col[0].paragraph[0]")
    assert block.text == "Go"
    assert block.kind == "table_cell"


# ---------------------------------------------------------------------------
# Unknown block_id rejection
# ---------------------------------------------------------------------------

def test_unknown_block_id_is_rejected_not_raised():
    document = _document(LayoutSection(section_id="s0", blocks=[_block("p[0]", "Existing.")]))

    result = apply_patches(document, [ContentPatch(block_id="p[999]", new_text="Ghost.")])

    assert result.rejected_block_ids == ["p[999]"]
    assert _block_by_id(result.document, "p[0]").text == "Existing."


def test_valid_patches_still_apply_alongside_a_rejected_one():
    document = _document(LayoutSection(
        section_id="s0",
        blocks=[_block("p[0]", "First."), _block("p[1]", "Second.")],
    ))

    result = apply_patches(document, [
        ContentPatch(block_id="p[0]", new_text="Updated first."),
        ContentPatch(block_id="p[999]", new_text="Ghost."),
    ])

    assert result.rejected_block_ids == ["p[999]"]
    assert _block_by_id(result.document, "p[0]").text == "Updated first."
    assert _block_by_id(result.document, "p[1]").text == "Second."


# ---------------------------------------------------------------------------
# Purity — input document is never mutated
# ---------------------------------------------------------------------------

def test_original_document_is_not_mutated():
    document = _document(LayoutSection(section_id="s0", blocks=[_block("p[0]", "Original.")]))

    apply_patches(document, [ContentPatch(block_id="p[0]", new_text="Changed.")])

    assert _block_by_id(document, "p[0]").text == "Original."
