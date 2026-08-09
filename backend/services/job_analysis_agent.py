import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.jobs import JobAnalysis
from services.llm_output import parse_llm_json
from services.text_utils import truncate_text

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Job descriptions rarely need more than this to extract all structured fields.
# Keeping the window tight reduces Gemini latency and prevents DB connection
# timeouts that occur when an oversized AI call holds the request open too long.
_MAX_CHARS = 5000


_SYSTEM_PROMPT = """Extract this job posting into JSON.

Unknown values: null.
Unknown arrays: [].
Do not infer missing information not present in the posting.

skills/technologies/keywords: pull out every concrete, atomic requirement
as its own short entry — not just named tools and languages, but also
methodologies ("Agile", "CI/CD"), certifications ("Azure Fundamentals"),
and explicitly named soft skills ("Stakeholder Communication",
"Leadership") whenever the posting states them as a requirement or
preference. Keyword-matching against a candidate's profile only ever looks
at these three fields plus responsibilities/qualifications, so a
requirement mentioned only in a long sentence and never pulled out as its
own short entry here cannot be matched later.

responsibilities/qualifications: still capture the full sentence-level
context for these same items (e.g. "5+ years of Agile development
experience") — they are complementary to skills/technologies/keywords, not
alternatives to them.

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
        text = truncate_text(raw_text, _MAX_CHARS, "\n[... text truncated for analysis]")
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
