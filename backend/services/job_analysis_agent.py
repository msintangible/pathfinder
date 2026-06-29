import json

from google import genai
from google.genai import types

from core.config import settings


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

    def analyze(self, raw_text: str, url: str | None = None) -> dict:
        content = f"Source URL: {url}\n\n{raw_text}" if url else raw_text
        response = self._client.models.generate_content(
            model="gemini-2.5-flash",
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(response.text)
