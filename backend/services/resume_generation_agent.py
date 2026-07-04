import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.resume import OptimizationPatchResponse
from schemas.resume_layout import ContentPatch, ResumeLayoutDocument
from services.ats_scorer import compute_ats
from services.keyword_matcher import KeywordReport, match_keywords
from services.llm_output import parse_llm_json
from services.patch_engine import apply_patches
from services.profile_layout_correlator import correlate_profile_to_layout
from services.relevance_ranker import rank_profile
from services.synthetic_profile_layout import build_synthetic_layout, flatten_layout_to_resume

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

# Real in-place rendering only kicks in when at least this fraction of
# correlatable profile fields (bullets, descriptions, headline, summary)
# found a confident real-document match — below this, the correlation this
# run produced is too unreliable to trust, and generation falls back to the
# existing generic-template renderer instead of risking a half-updated file.
_RENDER_CONFIDENCE_THRESHOLD = 0.6

_SYSTEM_PROMPT = """Tailor this candidate's resume to the job posting. You are editing
existing wording under strict structural constraints — you are not writing a new resume.

You will receive editable_blocks: a list of {block_id, text}, where text is
that block's current wording ("" for blocks meant to be authored fresh — see
skills/changes_summary below). Return one patch per block_id you were given —
never fewer, never more, and never a block_id you weren't given. candidate_profile
is provided as read-only context for the whole profile (all skill categories,
full work history) to inform your rewrites — you can only ever change
wording through editable_blocks, never candidate_profile's structure directly.

Allowed edits:
- Rewrite bullet/description text with stronger action verbs and clearer
  technical phrasing.
- Naturally weave matched_keywords into existing bullets/description using the
  candidate's real experience — never just list keywords.
  Bad:  "Used Python, AWS, Docker, Kubernetes, Terraform, React, Node.js..."
  Good: "Built backend services using Python and Docker, deployed on AWS..."
- Slightly expand or compress a bullet's wording within reason — do not pad
  with unrelated content or drop the point it was making.
- For the "skills" block: write a single comma-separated list synthesizing
  candidate_profile's technical_skills, programming_languages, frameworks,
  libraries, databases, cloud_platforms, devops_tools, ai_ml_tools, and
  development_tools, prioritizing whatever's relevant to this job.
- For the "changes_summary" block: write 2-5 short, plain-language lines (one
  per line) explaining what you emphasized or reworded and why — reference
  specific matched_keywords you leaned into, and mention any missing_keywords
  you could not address because the candidate has no real experience with
  them. Write for the candidate to read, not as a raw keyword list.

Never allowed:
- Never invent skills, employers, titles, dates, or achievements not already in
  the candidate profile.
- Never claim a missing_keyword as something the candidate has done. You may
  say "experience with similar systems/tools" only if that's already implied by
  real experience in the profile; otherwise leave the gap alone.
- Never adopt a marketing or exaggerated tone — plain, technical, ATS-parseable
  language only.

Schema:
{
  "patches": [
    {"block_id": string, "new_text": string}
  ]
}"""


class ResumeGenerationAgent:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def generate(self, profile: dict, job: dict, layout_document: dict | None = None) -> dict:
        keyword_report = match_keywords(profile, job)
        ranked = rank_profile(profile, keyword_report)

        layout = build_synthetic_layout(ranked.profile)
        patches = await self._optimize(layout, ranked.profile, job, keyword_report)

        patch_result = apply_patches(layout, patches)
        if patch_result.rejected_block_ids:
            logger.warning("Optimization LLM referenced unknown block_ids: %s", patch_result.rejected_block_ids)

        optimized_resume = flatten_layout_to_resume(ranked.profile, patch_result.document)
        ats_score = compute_ats(keyword_report)
        render_layout, layout_preserved = self._build_render_layout(ranked.profile, layout_document, patches)

        return {
            "ats_score": ats_score,
            "matched_keywords": keyword_report.matched,
            "missing_keywords": keyword_report.missing,
            "optimized_resume": optimized_resume,
            "patches": [patch.model_dump() for patch in patches],
            "render_layout": render_layout,
            "layout_preserved": layout_preserved,
        }

    def _build_render_layout(
        self, ranked_profile: dict, layout_document: dict | None, patches: list[ContentPatch]
    ) -> tuple[dict | None, bool]:
        """
        Re-applies the LLM's synthetic-id patches to the *real* document
        layout, via a one-time text correlation (profile_layout_correlator.py)
        between the ranked profile and profile.layout_document — so
        docx_renderer_v2/pdf_renderer_v2 can edit the candidate's actual
        uploaded file instead of only ever producing optimized_resume for the
        API/DB/UI. Returns (None, False) whenever there's no source document,
        or the correlation wasn't confident enough to trust.
        """
        if layout_document is None:
            return None, False

        real_layout = ResumeLayoutDocument.model_validate(layout_document)
        correlation = correlate_profile_to_layout(ranked_profile, real_layout)
        if correlation.match_rate < _RENDER_CONFIDENCE_THRESHOLD:
            logger.warning(
                "Layout correlation confidence too low (%.0f%%) — falling back to the generic renderer",
                correlation.match_rate * 100,
            )
            return None, False

        real_patches = [
            ContentPatch(block_id=correlation.block_id_map[patch.block_id], new_text=patch.new_text)
            for patch in patches
            if patch.block_id in correlation.block_id_map
        ]
        real_patch_result = apply_patches(real_layout, real_patches)
        return real_patch_result.document.model_dump(), True

    async def _optimize(
        self, layout: ResumeLayoutDocument, ranked_profile: dict, job: dict, keyword_report: KeywordReport
    ) -> list[ContentPatch]:
        editable_blocks = [
            {"block_id": block.block_id, "text": block.text}
            for section in layout.sections
            for block in section.blocks
        ]
        content = json.dumps({
            "job": job,
            "candidate_profile": ranked_profile,
            "matched_keywords": keyword_report.matched,
            "missing_keywords": keyword_report.missing,
            "editable_blocks": editable_blocks,
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
        result = parse_llm_json(response.text, OptimizationPatchResponse)
        return [ContentPatch(**patch) for patch in result["patches"]]
