import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.jobs import JobAnalysis
from services.llm_output import parse_llm_json

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Job descriptions rarely need more than this to extract all structured fields.
# Keeping the window tight reduces Gemini latency and prevents DB connection
# timeouts that occur when an oversized AI call holds the request open too long.
_MAX_CHARS = 5000


def _truncate(text: str) -> str:
    """Trim text to _MAX_CHARS, cutting at the last newline or space."""
    if len(text) <= _MAX_CHARS:
        return text
    cut = text.rfind("\n", 0, _MAX_CHARS)
    if cut == -1:
        cut = text.rfind(" ", 0, _MAX_CHARS)
    if cut == -1:
        cut = _MAX_CHARS
    return text[:cut] + "\n[... text truncated for analysis]"


_SYSTEM_PROMPT = """Extract this job posting into JSON.

Unknown values: null.
Unknown arrays: [].
Do not infer missing information.

Schema:
{
  "title": string|null,
  "company": string|null,
  "experience": string|null,
  "skills": [string],
  "technologies": [string],
  "responsibilities": [string],
  "qualifications": [string],
  "keywords": [string]
}"""


class JobAnalysisAgent:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def analyze(self, raw_text: str, url: str | None = None) -> dict:
        # url is accepted for API compatibility but isn't sent to the model —
        # it doesn't help extraction and only adds prompt tokens/latency.
        text = _truncate(raw_text)
        response = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=text,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return parse_llm_json(response.text, JobAnalysis)
