import json

from pydantic import BaseModel, ValidationError


class LLMOutputError(Exception):
    """
    Raised when an LLM response is not valid JSON or doesn't match the
    expected schema. Represents an upstream (LLM provider) contract
    violation, not a problem with the caller's input — the LLM-response
    analogue of PDFExtractionError (services/pdf_text_extractor.py) for a
    different upstream dependency.
    """


def parse_llm_json(text: str | None, schema: type[BaseModel]) -> dict:
    """Parse and validate a JSON LLM response against schema, returning a plain dict."""
    # google-genai's response.text is None (not "") when the model returns no
    # text part at all — e.g. a safety/recitation block — rather than malformed
    # JSON. json.loads(None) raises TypeError, which json.JSONDecodeError below
    # wouldn't catch, so it's handled explicitly here as the same upstream
    # contract violation.
    if text is None:
        raise LLMOutputError("LLM response contained no text (likely blocked by the provider)")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"LLM response was not valid JSON: {exc}") from exc

    try:
        validated = schema.model_validate(data)
    except ValidationError as exc:
        raise LLMOutputError(f"LLM response did not match {schema.__name__}: {exc}") from exc

    return validated.model_dump()
