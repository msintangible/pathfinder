import json

from google import genai
from google.genai import types

from schemas.profile import CandidateProfileInput


_SYSTEM_PROMPT = """You are a candidate profile extractor. You receive raw information about a job candidate from multiple sources and extract a single, rich, structured profile.

Rules:
- Never invent skills, experience, or qualifications not present in the input.
- Never infer employment history that is not explicitly stated.
- Prefer exact extraction over paraphrasing. Preserve technical terminology.
- When the same information appears in multiple sources, merge it into one entry. Do not duplicate.
- Return null for string fields that cannot be determined.
- Return empty arrays for list fields with no data.
- Return valid JSON only. No explanation, no markdown, no extra text.

Return ONLY valid JSON with this exact structure:
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
        self._client = genai.Client(
            vertexai=True,
            project="farmpulse-496900",
            location="us-central1",
        )

    def analyze(self, input: CandidateProfileInput) -> dict:
        response = self._client.models.generate_content(
            model="gemini-2.5-flash",
            contents=self._build_content(input),
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        return json.loads(response.text)

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
