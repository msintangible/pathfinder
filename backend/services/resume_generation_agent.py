import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from services.ats_scorer import compute_ats
from services.keyword_matcher import KeywordReport, match_keywords
from services.relevance_ranker import rank_profile

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_SYSTEM_PROMPT = """Tailor this candidate's resume to the job posting.

Rules:
- Never invent skills, experience, or achievements not in the candidate profile.
- Naturally emphasize the matched keywords using the candidate's real experience.
- Never claim a missing keyword as a skill the candidate has.
- Preserve factual accuracy: companies, titles, dates stay as given.
- Rewrite bullets/summary to highlight relevance to the job; do not fabricate.

Schema:
{
  "headline": string|null,
  "summary": string|null,
  "skills": [string],
  "experience": [
    {
      "title": string|null,
      "company": string|null,
      "start_date": string|null,
      "end_date": string|null,
      "bullets": [string]
    }
  ],
  "projects": [
    {
      "name": string|null,
      "description": string|null,
      "technologies": [string]
    }
  ]
}"""


class ResumeGenerationAgent:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def generate(self, profile: dict, job: dict) -> dict:
        keyword_report = match_keywords(profile, job)
        ranked_profile = rank_profile(profile, keyword_report)
        optimized_resume = await self._optimize(ranked_profile, job, keyword_report)
        ats_score = compute_ats(keyword_report)

        return {
            "ats_score": ats_score,
            "matched_keywords": keyword_report.matched,
            "missing_keywords": keyword_report.missing,
            "optimized_resume": optimized_resume,
        }

    async def _optimize(self, ranked_profile: dict, job: dict, keyword_report: KeywordReport) -> dict:
        content = json.dumps({
            "job": job,
            "candidate_profile": ranked_profile,
            "matched_keywords": keyword_report.matched,
            "missing_keywords": keyword_report.missing,
        })
        response = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=content,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(response.text)
