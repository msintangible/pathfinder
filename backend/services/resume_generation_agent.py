import json
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.resume import OptimizedResume
from services.ats_scorer import compute_ats
from services.keyword_matcher import KeywordReport, match_keywords
from services.llm_output import parse_llm_json
from services.relevance_ranker import rank_profile

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_SYSTEM_PROMPT = """Tailor this candidate's resume to the job posting. You are editing
an existing resume under strict structural constraints — you are not writing a new one.

Structure preservation (most important):
- Return exactly the number of "experience" entries and exactly the number of
  "projects" entries given in candidate_profile, in that same order. Never add,
  remove, merge, split, or reorder entries.
- Never change a title, company, start_date, or end_date — copy them through
  unchanged.
- Only rewrite: headline, summary, each entry's bullets/description/technologies,
  and the top-level skills list.

Allowed edits:
- Rewrite bullet/description text with stronger action verbs and clearer
  technical phrasing.
- Naturally weave matched_keywords into existing bullets/description using the
  candidate's real experience — never just list keywords.
  Bad:  "Used Python, AWS, Docker, Kubernetes, Terraform, React, Node.js..."
  Good: "Built backend services using Python and Docker, deployed on AWS..."
- Slightly expand or compress a bullet's wording within reason; keep roughly the
  same bullet count per entry as given — do not pad with new bullets or delete
  existing ones.
- Reorder wording within a single bullet or sentence for clarity or emphasis.

Never allowed:
- Never invent skills, employers, titles, dates, or achievements not already in
  the candidate profile.
- Never claim a missing_keyword as something the candidate has done. You may
  say "experience with similar systems/tools" only if that's already implied by
  real experience in the profile; otherwise leave the gap alone.
- Never adopt a marketing or exaggerated tone — plain, technical, ATS-parseable
  language only.

After tailoring, write 2-5 short, plain-language bullets in changes_summary
explaining what you emphasized or reworded and why — reference specific
matched_keywords you leaned into, and mention any missing_keywords you
could not address because the candidate has no real experience with them.
Write for the candidate to read, not as a raw keyword list.

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
  ],
  "changes_summary": [string]
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
        return parse_llm_json(response.text, OptimizedResume)
