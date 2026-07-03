from schemas.resume_layout import (
    Block,
    BlockType,
    DocumentMetadata,
    ResumeLayoutModel,
    Section,
    SourceFormat,
)


def _sample_layout() -> ResumeLayoutModel:
    return ResumeLayoutModel(
        metadata=DocumentMetadata(source_format=SourceFormat.DOCX),
        sections=[
            Section(
                title="Experience",
                blocks=[
                    Block(type=BlockType.HEADING, text="Senior Engineer"),
                    Block(type=BlockType.BULLET_LIST, items=["Shipped X", "Led Y"]),
                ],
            ),
            Section(
                title="Projects",
                blocks=[Block(type=BlockType.PARAGRAPH, text="Built Z")],
            ),
        ],
    )


def test_block_ids_are_unique_within_a_document():
    layout = _sample_layout()

    ids = [block.block_id for section in layout.sections for block in section.blocks]

    assert len(ids) == len(set(ids))


def test_block_ids_survive_a_serialize_deserialize_round_trip():
    layout = _sample_layout()
    original_ids = layout.block_ids()

    reloaded = ResumeLayoutModel.model_validate(layout.model_dump())

    assert reloaded.block_ids() == original_ids


def test_block_ids_helper_matches_manual_collection():
    layout = _sample_layout()

    expected = {block.block_id for section in layout.sections for block in section.blocks}

    assert layout.block_ids() == expected


def test_every_planned_block_type_is_constructible():
    for block_type in BlockType:
        block = Block(type=block_type)
        assert block.block_id
        assert block.type == block_type
