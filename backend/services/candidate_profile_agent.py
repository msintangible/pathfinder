import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.profile import CandidateProfile, CandidateProfileInput
from services.llm_output import parse_llm_json
from services.profile_deduplicator import dedupe_profile

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


_SYSTEM_PROMPT = """Extract a candidate profile from the input sources into JSON.

Rules:
- Don't invent skills, experience, or qualifications not in the input.
- Don't infer employment history not explicitly stated.
- Merge the same info from multiple sources into one entry, not duplicates.
- When sources disagree on a single-valued fact (email, phone, name), prefer
  sources in this order and use the first one that has a value:
    1. Resume/CV text — the candidate deliberately wrote/uploaded this.
    2. LinkedIn text.
    3. GitHub profile bio.
    4. Portfolio site text — often contains a generic "contact us" address
       or a webmaster/form-relay email that is NOT the candidate's own; only
       use a portfolio-sourced email/phone if no higher-priority source has
       one.
- Phone numbers appear in many formats (+1 555 123 4567, (555) 123-4567,
  555.123.4567, an international format with a country code, etc.) and
  aren't always on their own labeled line — scan every source's full text
  for anything shaped like a phone number, the same care you'd give to
  finding an email address, before concluding "phone": null. Don't require
  an explicit "Phone:" label to find one.
- For each project, separate its evidence into distinct facts instead of
  one flattened description: "problem" (what need/challenge it addressed),
  "solution" (what was actually built to address it, 1-2 sentences),
  "architecture" (real technical components/design decisions — e.g. "FastAPI
  WebSocket backend", "multi-stage LLM pipeline"), "responsibilities" (what
  the candidate specifically owned — most useful for a team/hackathon
  project; omit for a solo project where it would just restate "solution"),
  "technical_achievements" (a specific engineering win or hard problem
  solved — a technique, an optimization, a validation approach), "impact"
  (a measurable outcome: an award, a metric, adoption, deployment reach),
  and "deployment" (where it actually runs, e.g. "Azure", "Vercel" — only
  if genuinely stated, never inferred from the tech stack alone). Every
  field is a fact that must actually be present in the source text — leave
  it null/[] rather than inferring or padding it, the same rule as every
  other field in this schema. notable_achievements remains the catch-all
  for genuine detail that doesn't cleanly fit one of these more specific
  buckets.
- For each project, if one of the input's github_repositories is clearly
  the same project (matching or near-matching name, or the project's
  description references the same subject matter as a repo's description/
  README), mine that repo's README for genuine additional detail and route
  it into the specific field it actually describes — a design decision into
  "architecture", a hard problem solved into "technical_achievements", a
  measurable outcome into "impact", a hosting detail into "deployment" —
  rather than dumping everything into notable_achievements. Only pull
  details that are actually stated in the README; never pad with a
  rephrasing of something already captured elsewhere in the same project.
- If a project or work_experience entry's source text describes multiple
  distinct facts or outcomes run together in one dense paragraph, split
  them into separate bullets/notable_achievements — one fact per entry —
  rather than leaving them merged into a single block of text.
- Classify every skill into the most specific matching category below (e.g.
  a programming language always goes in programming_languages, never
  technical_skills, even if it's also mentioned generically elsewhere).
  technical_skills is only for skills that genuinely don't fit any of the
  more specific categories — it's a last resort, not a default.
- Unknown values: null.
- Unknown arrays: [].
- For "summary": write 3-5 sentences that read like a short, specific
  narrative about this individual, in third person using their actual first
  name — not a generic label. Ground it in what the input sources actually
  show: what kinds of problems they've chosen to work on, what they seem
  motivated by (inferred from project choices, descriptions, and any
  personal framing already present in the sources — e.g. a hackathon-winning
  project suggests genuine interest, not just a class requirement), and 1-2
  concrete, specific achievements.
  Reject and rewrite any sentence built from generic resume-filler phrasing
  — "passionate about building [X] systems", "results-driven", "team
  player", "eager to adapt to new technologies", "contribute skills to a
  dynamic team", "extensive experience across the [X] lifecycle" — even if
  a phrase like this already appears in the candidate's own source resume
  text. The test is not "did I copy this from somewhere" but "could this
  exact sentence describe thousands of other candidates unchanged" — if so,
  it must be rewritten to be specific to this one, using the same real
  facts the generic version was gesturing at.
  Example — same underlying facts (CS student, full-stack intern, backend
  focus, several self-driven projects), rewritten from generic to specific:
    Bad:  "Final-year Computer Science student passionate about building
           robust systems. Extensive Full-Stack Developer experience across
           the software development lifecycle, with a focus on backend
           systems and infrastructure. Eager to adapt to new technologies
           and contribute skills to a dynamic team."
    Good: "Michael is a final-year Computer Science student who enjoys
           building software that solves practical problems — from an
           AI-powered meeting-notes tool that won Best Use of ElevenLabs at
           HackBelfast to a stock valuation model combining machine
           learning with real market data. His FluxPro internship deepened
           this into backend engineering and cloud infrastructure, and he's
           motivated by making systems that are both technically solid and
           genuinely useful."
  Every claim about motivation or interest must trace to something concrete
  in the input — never invent an interest or personality trait with no
  textual anchor. If the input is too sparse to support a personalized
  narrative (e.g. only a bare skills list, no project descriptions), fall
  back to a competent, specific-to-their-skills-and-experience summary
  rather than inventing
  color.
- certifications, awards, achievements, leadership_experience,
  volunteer_work, publications, languages, recommendations_received,
  interests, and references each render as their own resume section
  whenever populated, and are omitted entirely when empty — there's no
  downside to filling one in when the input genuinely supports it, so
  actively look for them rather than defaulting to []. When a LinkedIn
  source is present, map explicitly from its own section names, since
  LinkedIn is the most reliably structured source for these:
    - LinkedIn "Licenses & Certifications" -> certifications (name, issuer,
      date, credential URL if present).
    - LinkedIn "Honors & Awards" -> awards.
    - LinkedIn "Volunteering" -> volunteer_work (cause/organization/role).
    - LinkedIn "Publications" -> publications.
    - LinkedIn "Languages" -> languages, one entry per language, including
      the stated proficiency when given (e.g. "Spanish (Conversational)"),
      just the language name otherwise.
    - LinkedIn "Recommendations received" -> recommendations_received: pull
      the specific claim(s) a recommender makes about the candidate's real
      skills/traits (e.g. "consistently the person the team turned to for
      tricky debugging"), not the recommender's own name/title or generic
      praise with no substance ("great to work with").
  Outside a dedicated list, a "Certified..." or "Certificate in..." mention
  is still a certification; a hackathon placement, a "Dean's List" mention,
  or a competition result is an award; mentoring, leading a team/project, or
  organizing an event is leadership experience; an "Interests" or "Outside
  of work" section is interests; anything reading like a formal reference
  contact or "References available on request" belongs in references. Only
  extract what's actually stated — never invent a certification, award,
  language, recommendation, or reference that isn't genuinely in the input.

Schema:
{
  "name": string or null,
  "email": string or null,
  "phone": string or null,
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
  "languages": [string],
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
      "notable_achievements": [string],
      "problem": string or null,
      "solution": string or null,
      "architecture": [string],
      "responsibilities": [string],
      "technical_achievements": [string],
      "impact": [string],
      "deployment": [string]
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
  "interests": [string],
  "references": [string],
  "recommendations_received": [string],
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
        profile = parse_llm_json(response.text, CandidateProfile)
        return dedupe_profile(profile)

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
