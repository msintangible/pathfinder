"""
Tests for GeminiVisionLayoutAgent.

Mocks google.genai the same way test_candidate_profile_agent.py and
test_resume_generation_agent.py do — no real Gemini call is made.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
import pytest

from schemas.resume_layout import TextBlock
from services.llm_output import LLMOutputError
from services.gemini_vision_layout_agent import GeminiVisionLayoutAgent
from services.pdf_layout_extractor import extract_pdf_layout

_PAGE_IMAGE = b"\x89PNG-fake-bytes"

_BLOCKS = [
    TextBlock(block_id="page[0].block[0].line[0]", kind="paragraph", text="Jane Doe"),
    TextBlock(block_id="page[0].block[1].line[0]", kind="paragraph", text="Python, Django, PostgreSQL"),
]

_LABELED_RESULT = {
    "sections": [
        {"role": "header_contact", "block_ids": ["page[0].block[0].line[0]"]},
        {"role": "skills", "block_ids": ["page[0].block[1].line[0]"]},
    ]
}


def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.text = json.dumps(data)
    return mock


@pytest.fixture
def mock_genai():
    with patch("services.gemini_vision_layout_agent.genai") as patched:
        mock_client = MagicMock()
        patched.Client.return_value = mock_client
        mock_client.aio.models.generate_content = AsyncMock()
        yield mock_client


@pytest.mark.anyio
async def test_labels_blocks_into_sections_with_roles(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_LABELED_RESULT)

    result = await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)

    assert result["sections"][0]["role"] == "header_contact"
    assert result["sections"][0]["block_ids"] == ["page[0].block[0].line[0]"]
    assert result["sections"][1]["role"] == "skills"


@pytest.mark.anyio
async def test_sends_page_image_as_inline_bytes(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_LABELED_RESULT)

    await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)

    contents = mock_genai.aio.models.generate_content.call_args.kwargs["contents"]
    image_part = contents[0]
    assert image_part.inline_data.data == _PAGE_IMAGE
    assert image_part.inline_data.mime_type == "image/png"


@pytest.mark.anyio
async def test_sends_block_ids_and_text_as_grounding_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_LABELED_RESULT)

    await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)

    contents = mock_genai.aio.models.generate_content.call_args.kwargs["contents"]
    grounding = json.loads(contents[1])
    assert grounding == [
        {"block_id": "page[0].block[0].line[0]", "text": "Jane Doe"},
        {"block_id": "page[0].block[1].line[0]", "text": "Python, Django, PostgreSQL"},
    ]


@pytest.mark.anyio
async def test_uses_flash_lite_model(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_LABELED_RESULT)

    await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)

    assert mock_genai.aio.models.generate_content.call_args.kwargs["model"] == "gemini-2.5-flash-lite"


@pytest.mark.anyio
async def test_uses_json_response_mode_and_zero_temperature(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(_LABELED_RESULT)

    await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)

    config = mock_genai.aio.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.temperature == 0


@pytest.mark.anyio
async def test_raises_llm_output_error_on_invalid_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = MagicMock(text="not json")

    with pytest.raises(LLMOutputError):
        await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)


@pytest.mark.anyio
async def test_raises_llm_output_error_on_wrong_shaped_json(mock_genai):
    mock_genai.aio.models.generate_content.return_value = _make_response(
        {"sections": [{"role": "not-a-real-role", "block_ids": []}]}
    )

    with pytest.raises(LLMOutputError):
        await GeminiVisionLayoutAgent().label_page(_PAGE_IMAGE, _BLOCKS)


# ---------------------------------------------------------------------------
# label_document — per-page orchestration
# ---------------------------------------------------------------------------

def _make_pdf(lines: list[str]) -> bytes:
    document = fitz.open()
    page = document.new_page()
    for index, text in enumerate(lines):
        page.insert_text((72, 100 + index * 20), text, fontsize=11)
    buffer = document.tobytes()
    document.close()
    return buffer


def _all_blocks(layout):
    return [block for section in layout.sections for block in section.blocks]


@pytest.mark.anyio
async def test_label_document_groups_blocks_into_role_labeled_sections(mock_genai):
    source_bytes = _make_pdf(["Jane Doe", "Python, Django, PostgreSQL"])
    layout = extract_pdf_layout(source_bytes)
    name_id, skills_id = (block.block_id for block in _all_blocks(layout))
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "sections": [
            {"role": "header_contact", "block_ids": [name_id]},
            {"role": "skills", "block_ids": [skills_id]},
        ]
    })

    result = await GeminiVisionLayoutAgent().label_document(source_bytes, layout)

    roles = {section.role.value: [b.block_id for b in section.blocks] for section in result.sections}
    assert roles["header_contact"] == [name_id]
    assert roles["skills"] == [skills_id]


@pytest.mark.anyio
async def test_label_document_keeps_page_unlabeled_when_response_is_invalid(mock_genai):
    source_bytes = _make_pdf(["Jane Doe", "Python, Django, PostgreSQL"])
    layout = extract_pdf_layout(source_bytes)
    mock_genai.aio.models.generate_content.return_value = MagicMock(text="not json")

    result = await GeminiVisionLayoutAgent().label_document(source_bytes, layout)

    assert [b.block_id for b in _all_blocks(result)] == [b.block_id for b in _all_blocks(layout)]
    assert result.sections[0].role == layout.sections[0].role


@pytest.mark.anyio
async def test_label_document_keeps_blocks_the_model_missed_in_a_trailing_section(mock_genai):
    source_bytes = _make_pdf(["Jane Doe", "Python, Django, PostgreSQL"])
    layout = extract_pdf_layout(source_bytes)
    name_id, skills_id = (block.block_id for block in _all_blocks(layout))
    # The model only labels the first block, omitting the second entirely.
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "sections": [{"role": "header_contact", "block_ids": [name_id]}]
    })

    result = await GeminiVisionLayoutAgent().label_document(source_bytes, layout)

    all_ids = {b.block_id for b in _all_blocks(result)}
    assert all_ids == {name_id, skills_id}  # nothing silently dropped
    unlabeled = [s for s in result.sections if s.section_id.endswith(".unlabeled")]
    assert len(unlabeled) == 1
    assert unlabeled[0].blocks[0].block_id == skills_id


@pytest.mark.anyio
async def test_label_document_ignores_block_ids_the_model_invented(mock_genai):
    source_bytes = _make_pdf(["Jane Doe"])
    layout = extract_pdf_layout(source_bytes)
    real_id = _all_blocks(layout)[0].block_id
    mock_genai.aio.models.generate_content.return_value = _make_response({
        "sections": [{"role": "header_contact", "block_ids": [real_id, "page[9].block[9].line[9]"]}]
    })

    result = await GeminiVisionLayoutAgent().label_document(source_bytes, layout)

    assert [b.block_id for b in _all_blocks(result)] == [real_id]
