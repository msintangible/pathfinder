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


def parse_llm_json(text: str, schema: type[BaseModel]) -> dict:
    """Parse and validate a JSON LLM response against schema, returning a plain dict."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"LLM response was not valid JSON: {exc}") from exc

    try:
        validated = schema.model_validate(data)
    except ValidationError as exc:
        raise LLMOutputError(f"LLM response did not match {schema.__name__}: {exc}") from exc

    return validated.model_dump()
