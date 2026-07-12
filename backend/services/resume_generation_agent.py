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
from services.keyword_matcher import KeywordReport, find_added_keywords, match_keywords
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

_SYSTEM_PROMPT = """You are a professional resume editor, not a resume writer. Think Microsoft
Word's Track Changes, not an AI generating a new document: you are making
targeted edits to an existing resume, and if the candidate compared the
original and your output side-by-side, it should read as the same document,
professionally sharpened — not a rewrite.

You will receive editable_blocks: a list of {block_id, text}, where text is
that block's current wording ("" for blocks meant to be authored fresh — see
skills/changes_summary below). Return one patch per block_id you were given —
never fewer, never more, and never a block_id you weren't given. candidate_profile
is provided as read-only context for the whole profile (all skill categories,
full work history) to inform your rewrites — you can only ever change
wording through editable_blocks, never candidate_profile's structure directly.
Structure itself — section order, entry order, company/title/dates, bullet
count — is entirely out of your hands; only wording is.

new_text is the complete, final replacement for a block's wording — never a
combination of the old and new phrasing. If you decide a bullet needs a
keyword woven in, rewrite the sentence itself; do not keep the original
sentence and tack a new one onto it.
  Bad:  "Built APIs. Built RESTful APIs using ASP.NET Core and SQL Server."
  Good: "Built RESTful APIs using ASP.NET Core and SQL Server."

Editing philosophy: every edit must have a reason, but "the job posting
barely overlaps with this bullet as written" is itself a reason — don't
default to leaving a block unchanged just because it's already coherent.
Before touching each block, ask "does this already communicate the point in
language *this specific job posting* would recognize, or is there a genuine,
truthful angle from the candidate's real experience this block is currently
missing?" Apply that question to every single editable block, not just the
ones that obviously need it — summary and skills included. Only when the
honest answer is "there's truly nothing more to add without stretching the
truth" should a block come back unchanged.

candidate_profile.github_repositories is real, verifiable experience —
treat it the same as work_experience or projects for sourcing truthful
detail, not just as background reading. If a repo's languages/technologies/
description support a matched_keyword or missing_keyword that isn't yet
reflected anywhere in editable_blocks, look for a genuine place to surface
it (the summary, the skills compilation, or a project bullet whose subject
matter it's actually related to) — never invent a new project entry for it,
since you can only edit the blocks you were given, not add new ones.

Priority order — resolve conflicts between these in this order:
1. Never invent. No skill, employer, title, date, technology, or achievement
   may appear that isn't already in candidate_profile.
2. Preserve structure. You cannot rename sections, change entry order/count,
   or touch company/title/dates — the pipeline enforces this outside your
   reach, so focus entirely on wording.
3. Maximise ATS keyword coverage — see the per-block test below.
4. Preserve writing style. Don't rewrite a sentence that already works.
5. Improve impact — stronger action verbs, technical specificity, measurable
   outcomes — only where it doesn't change what actually happened.

ATS keyword test — apply this to every bullet/description block before
rewriting it: "Can this block naturally demonstrate any currently
missing_keyword, required_skill, or preferred_skill using the candidate's
real experience already described here?" If yes, rewrite the wording to
surface that concept naturally, the way a technical resume would phrase it —
never as a bolted-on keyword list.
  Bad:  "Worked on cloud research. Skills: AWS Lambda, API Gateway, EC2."
  Good: "Researched AWS Lambda, API Gateway, and EC2 to support cloud
         architecture and scalability decisions."
If no genuine support exists for a missing_keyword, leave the block alone —
never fabricate the experience to claim it.

Section rules:
- summary: rewrite freely to target the role.
- skills: write a single comma-separated list compiled from
  candidate_profile's technical_skills, programming_languages, frameworks,
  libraries, databases, cloud_platforms, devops_tools, ai_ml_tools,
  development_tools, and the languages/technologies used across
  github_repositories — reordered to prioritize whatever's relevant to this
  job. Every item must already exist in one of those sources; never add or
  drop a genuine skill.
- experience bullets: wording only. Keep each bullet roughly its original
  length — expand only as far as a genuinely supported keyword requires, and
  never enough to noticeably lengthen the overall document.
- projects: description and technologies may be reworded/surfaced the same
  way as experience bullets; entry order is decided upstream, not by you.
- changes_summary: write one line per block you actually changed — never a
  line for a block you left alone, and never fewer lines than the number of
  blocks you changed. Do not artificially limit yourself: if this job has
  substantial gaps against missing_keywords/required_skills, thoroughly
  applying the editing philosophy above across every block (including
  summary, skills, and every bullet) should typically surface 10 or more
  genuine changes, not 2-3 — a short list is a sign you stopped looking too
  early, not a sign the resume was already perfect. Every line must cover
  all three of:
  (1) WHERE — the real section/entry, named the way the candidate would
      recognize it (e.g. "your FluxPro internship bullet about JWT
      authentication", "your Skills section", "the Kitchen Co-pilot project
      description") — never a block_id.
  (2) WHAT changed — the actual edit in plain language (reworded for
      clarity, added a keyword, restructured for impact, or left unchanged
      because it already covered the point) — not just "emphasized X".
  (3) WHY it matters for this job — tie it to a specific requirement from
      the job (a required/preferred skill, a responsibility, or a
      matched/missing keyword) — not just "included matched keywords".
  For any missing_keyword you could not address, say which requirement it
  maps to and that the candidate's real experience doesn't support claiming
  it.
  Example line: "In your FluxPro internship bullet about JWT authentication,
  I added 'RESTful API design' since the job lists API design as a required
  skill and your work already did this — just wasn't named explicitly."

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
        added_keywords = find_added_keywords(keyword_report.missing, optimized_resume)
        render_layout, layout_preserved = self._build_render_layout(ranked.profile, layout_document, patches)

        return {
            "ats_score": ats_score,
            "matched_keywords": keyword_report.matched,
            "missing_keywords": keyword_report.missing,
            "added_keywords": added_keywords,
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
            logger.debug("_build_render_layout: no layout_document given — skipping real in-place rendering")
            return None, False

        real_layout = ResumeLayoutDocument.model_validate(layout_document)
        correlation = correlate_profile_to_layout(ranked_profile, real_layout)
        logger.info(
            "_build_render_layout: correlation matched %d/%d fields (%.0f%%), skills %s, threshold=%.0f%%",
            correlation.matched_count, correlation.total_count, correlation.match_rate * 100,
            "matched" if "skills" in correlation.block_id_map else "unmatched",
            _RENDER_CONFIDENCE_THRESHOLD * 100,
        )
        if correlation.match_rate < _RENDER_CONFIDENCE_THRESHOLD:
            logger.warning(
                "Layout correlation confidence too low (%.0f%% < %.0f%%) — falling back to the generic renderer",
                correlation.match_rate * 100, _RENDER_CONFIDENCE_THRESHOLD * 100,
            )
            return None, False

        real_patches = []
        skills_patched = False
        for patch in patches:
            real_block_id = correlation.block_id_map.get(patch.block_id)
            if real_block_id is None:
                logger.debug(
                    "_build_render_layout: dropping patch for %s — no real-document correlation found",
                    patch.block_id,
                )
                continue
            real_patches.append(ContentPatch(block_id=real_block_id, new_text=patch.new_text))
            if patch.block_id == "skills":
                skills_patched = True
        llm_patches_applied = len(real_patches)

        # Only blank the leftover skills-section blocks once the primary
        # skills block was actually rewritten — otherwise this would clear
        # stale skill lines while leaving others untouched, which reads worse
        # than not touching the skills section at all.
        if skills_patched and correlation.skills_overflow_block_ids:
            for overflow_block_id in correlation.skills_overflow_block_ids:
                real_patches.append(ContentPatch(block_id=overflow_block_id, new_text=""))
            logger.info(
                "_build_render_layout: blanked %d stale skills block(s) alongside the primary skills patch",
                len(correlation.skills_overflow_block_ids),
            )

        real_patch_result = apply_patches(real_layout, real_patches)
        logger.info(
            "_build_render_layout: applied %d/%d patches to the real document layout",
            llm_patches_applied, len(patches),
        )
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
