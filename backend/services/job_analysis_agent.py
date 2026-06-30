import json

from google import genai
from google.genai import types

from core.config import settings

# Job descriptions rarely need more than this to extract all structured fields.
# Keeping the window tight reduces Gemini latency and prevents DB connection
# timeouts that occur when an oversized AI call holds the request open too long.
_MAX_CHARS = 500


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


_SYSTEM_PROMPT = """You are a job posting parser. Extract structured information from the job posting text.

Rules:
- Never invent information not present in the text.
- Return null for fields that cannot be determined.
- Return empty arrays for list fields with no data.
- Preserve the employer's wording where practical.
- Ignore marketing copy, navigation links, cookie notices, and unrelated page content.
- Do not infer years of experience unless explicitly stated in the posting.
- List required skills in "skills"; list preferred/nice-to-have skills there too if not distinguished.

Return ONLY valid JSON with these exact keys:
{
  "title": string or null,
  "company": string or null,
  "experience": string or null,
  "skills": [string],
  "technologies": [string],
  "responsibilities": [string],
  "qualifications": [string],
  "keywords": [string]
}"""


class JobAnalysisAgent:
    def __init__(self) -> None:
        self._client = genai.Client(
            vertexai=True,
            project="farmpulse-496900",
            location="us-central1",
        )

    async def analyze(self, raw_text: str, url: str | None = None) -> dict:
        text = _truncate(raw_text)
        content = f"Source URL: {url}\n\n{text}" if url else text
        response = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(response.text)
