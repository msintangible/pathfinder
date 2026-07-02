import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.profile import CandidateProfile, CandidateProfileInput
from services.llm_output import parse_llm_json

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


_SYSTEM_PROMPT = """Extract a candidate profile from the input sources into JSON.

Rules:
- Don't invent skills, experience, or qualifications not in the input.
- Don't infer employment history not explicitly stated.
- Merge the same info from multiple sources into one entry, not duplicates.
- Unknown values: null.
- Unknown arrays: [].

Schema:
{
  "name": string or null,
  "headline": string or null,
  "summary": string or null,
  "technical_skills": [string],
  "soft_skills": [string],
  "programming_languages": [string],
  "frameworks": [string],
  "libraries": [string],
  "databases": [string],
  "cloud_platforms": [string],
  "devops_tools": [string],
  "ai_ml_tools": [string],
  "development_tools": [string],
  "work_experience": [
    {
      "title": string or null,
      "company": string or null,
      "location": string or null,
      "start_date": string or null,
      "end_date": string or null,
      "current": boolean,
      "bullets": [string],
      "technologies": [string],
      "skills_demonstrated": [string]
    }
  ],
  "education": [
    {
      "institution": string or null,
      "degree": string or null,
      "field": string or null,
      "start_date": string or null,
      "end_date": string or null,
      "grade": string or null,
      "achievements": [string]
    }
  ],
  "projects": [
    {
      "name": string or null,
      "description": string or null,
      "url": string or null,
      "technologies": [string],
      "skills_demonstrated": [string],
      "notable_achievements": [string]
    }
  ],
  "github_repositories": [
    {
      "name": string or null,
      "description": string or null,
      "url": string or null,
      "languages": [string],
      "frameworks": [string],
      "technologies": [string],
      "purpose": string or null,
      "complexity": string or null,
      "skills_demonstrated": [string]
    }
  ],
  "open_source_contributions": [string],
  "certifications": [
    {
      "name": string or null,
      "issuer": string or null,
      "date": string or null,
      "url": string or null
    }
  ],
  "awards": [string],
  "achievements": [string],
  "leadership_experience": [string],
  "volunteer_work": [string],
  "publications": [string],
  "links": {"key": "url"}
}"""


class CandidateProfileAgent:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def analyze(self, input: CandidateProfileInput) -> dict:
        response = await self._client.aio.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=self._build_content(input),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return parse_llm_json(response.text, CandidateProfile)

    def _build_content(self, input: CandidateProfileInput) -> str:
        """
        Format all available sources into a single structured text block.
        Sections with no data are omitted so the model is not distracted by
        empty headers.
        """
        sections: list[str] = []

        if input.resume_text:
            sections.append(f"=== RESUME ===\n{input.resume_text}")

        if input.linkedin_text:
            sections.append(f"=== LINKEDIN PROFILE ===\n{input.linkedin_text}")

        if input.github_profile:
            sections.append(f"=== GITHUB PROFILE ===\n{input.github_profile}")

        if input.github_repositories:
            repo_blocks = []
            for i, repo in enumerate(input.github_repositories, start=1):
                lines = [f"[{i}] {repo.name}"]
                if repo.url:
                    lines.append(f"URL: {repo.url}")
                if repo.description:
                    lines.append(f"Description: {repo.description}")
                if repo.languages:
                    lines.append(f"Languages: {', '.join(repo.languages)}")
                if repo.topics:
                    lines.append(f"Topics: {', '.join(repo.topics)}")
                if repo.stars is not None:
                    lines.append(f"Stars: {repo.stars}")
                if repo.readme:
                    lines.append(f"README:\n{repo.readme}")
                repo_blocks.append("\n".join(lines))
            sections.append("=== GITHUB REPOSITORIES ===\n\n" + "\n\n---\n\n".join(repo_blocks))

        if input.portfolio_text:
            sections.append(f"=== PORTFOLIO / PERSONAL SITE ===\n{input.portfolio_text}")

        return "\n\n".join(sections)
