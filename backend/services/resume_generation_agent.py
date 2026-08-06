import json
import logging
import os
import re
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from schemas.resume import ChangeHighlight, KeywordSkipReason, OptimizationPatchResponse, OptimizationReport
from schemas.resume_layout import ContentPatch, ResumeLayoutDocument
from services.ats_scorer import compute_ats
from services.keyword_matcher import (
    PROFILE_SKILL_FIELDS,
    KeywordReport,
    _keyword_appears_in,
    filter_backed_keywords,
    find_added_keywords,
    match_keywords,
    unused_candidate_skills,
)
from services.inferable_keywords import infer_available_keywords
from services.llm_output import parse_llm_json
from services.optimization_validator import validate_optimization_integrity
from services.patch_engine import apply_patches
from services.profile_deduplicator import merge_overlapping_bullets
from services.relevance_ranker import rank_profile
from services.synthetic_profile_layout import build_synthetic_layout, flatten_layout_to_resume

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a professional resume editor, not a resume writer. Think Microsoft
Word's Track Changes, not an AI generating a new document: you are making
targeted edits to an existing resume, and if the candidate compared the
original and your output side-by-side, it should read as the same document,
professionally sharpened — not a rewrite.

You will receive editable_blocks: a list of {block_id, text}, where text is
that block's current wording ("" for blocks meant to be authored fresh — see
skills below, and changes_summary, which this pipeline no longer displays:
always return "" for it). Return one patch per block_id you were given —
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

In any bullet, summary, or project description, wrap the 1-3 most
ATS-relevant technologies/tools/metrics in **double asterisks** (the
renderer turns this into bold text) so they visually stand out — but only
around real, specific terms (a technology name, a framework, a measurable
outcome like "40% faster"), never around generic phrases or whole sentences.
  Bad:  "**Built RESTful APIs using ASP.NET Core and SQL Server**"
  Good: "Built RESTful APIs using **ASP.NET Core** and **SQL Server**"
This doesn't apply to the skills block, which renders as a plain list.

Editing philosophy — apply this exact two-step test to every editable
block, not just the ones that obviously need it (summary and skills
included):

STEP 1: Does this job have a missing_keyword, required_skill, or
preferred_skill that this block's real, described work could truthfully
demonstrate (per the ATS keyword test below)?

  IF NO applicable keyword exists for this block:
    Leave the block's core content unchanged. Only fix objective
    weaknesses (a weak verb, awkward phrasing, a genuinely stronger
    quantification of the same fact) — this bullet should still read as
    clearly "the same bullet," light polish only.

  IF YES — one or more missing/required/preferred keywords genuinely
  apply:
    Rewrite the block enough that a reader placing the original and your
    version side-by-side can immediately see WHERE the new emphasis is,
    not just that a synonym changed. Lead with the angle this job cares
    about. This is not a light polish — restructure the sentence around
    the newly-surfaced concept if that reads more naturally, while
    keeping every fact truthful and traceable to candidate_profile. A
    rewrite that only swapped one or two words while a real keyword gap
    existed has failed this test.

Never invent to satisfy STEP 1's "yes" branch — if no genuine angle
exists, the honest answer was actually "no"; treat it as such.

When a bullet or project description honestly supports more than one angle,
lead with whichever angle this specific job cares about most — don't default
to the candidate's own original emphasis or chronological framing if a
different genuine detail in the same block is more relevant to this posting.

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
4. Preserve writing style ONLY when STEP 1 above found no applicable
   keyword for this block. Once a genuine keyword gap exists, restructuring
   the sentence (STEP 2) outranks preserving the original phrasing — don't
   let "the original already reads fine" talk you out of a rewrite STEP 2
   actually calls for.
5. Improve impact — stronger action verbs, technical specificity, and
   sharper quantification. Apply this whenever STEP 2 already applies to a
   block, not just as an afterthought: if candidate_profile has a number,
   scale, or concrete detail for this same fact that the current wording
   understates or omits (team size, client count, before/after values,
   which specific technique was used), use it. Never invent a number or
   detail that isn't genuinely in candidate_profile.
   Bad:  "Collaborated via Git, enabling the team to complete tasks faster."
         (candidate_profile elsewhere states this was "20% faster" — that
         real detail is sitting unused)
   Good: "Collaborated via Git for version control and code review,
         enabling the team to complete routine tasks 20% faster."

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

Never force a keyword into a block whose real subject matter doesn't
actually match it, even if the two sound topically adjacent. A keyword only
belongs in a block if the underlying work it names is genuinely what that
block is about — not just genuinely true of the candidate somewhere else.
  Bad:  original "Optimized websites for SEO, hosting, and analytics
         integration" (a WordPress freelance bullet) rewritten to "Optimized
         scalable data pipelines..." — the candidate may have real data
         pipeline experience, but not in this bullet's project.
  Good: leave that bullet's subject matter (SEO/hosting/analytics) alone,
        and place "data pipelines" in the block that's actually about that
        work instead.
This applies within a project too: only mention a technology in a project's
description/tech-stack/achievement blocks if candidate_profile actually
shows that project used it — never borrow a technology from a different
project or from work_experience just because it's a missing_keyword.

Some missing_keywords describe a general practice or soft skill rather than
a specific tool (e.g. "problem solving", "full lifecycle development", "data
science", "collaboration", "agile", "continuous integration"). These follow
the exact same test as any other keyword — genuine truthful support, never
fabrication — but the truthful basis is often the *shape* of real work
already in candidate_profile, not a literal mention of the phrase:
  - Any real project that built something or fixed an issue already
    demonstrates "problem solving" — no project explicitly says that phrase.
  - A project or job the candidate took from requirements through to
    deployment/maintenance demonstrates "full lifecycle development" (or
    "full lifecycle" / "end-to-end"), even worded differently in the bullet.
  - A project or job that used data analysis, statistics, or ML libraries
    (e.g. pandas, scikit-learn, XGBoost) demonstrates "data science", even if
    "data science" itself is never the term the candidate used.
Surface these the same way as any other keyword — reworded naturally into
the relevant bullet or summary, never a bare label — and only when the
candidate's real profile genuinely shows that shape of work.

Section rules:
- summary: retarget which achievements/interests are foregrounded to match
  this job, but preserve the candidate's actual voice and narrative from
  candidate_profile.summary — don't flatten a specific, personal summary
  into generic filler ("passionate about", "results-driven", "team player",
  "experienced X professional", "eager to contribute to a dynamic team").
  If candidate_profile.summary is already specific and personal, retargeting
  means changing which real achievement/interest leads, not rewriting it
  into something generic. Keep it roughly the same length as its current
  text (about 4 lines) — this is the candidate's first impression, not a
  place to introduce a wall of text.
- skills: write a single comma-separated list compiled from
  candidate_profile's technical_skills, programming_languages, frameworks,
  libraries, databases, cloud_platforms, devops_tools, ai_ml_tools,
  development_tools, and the languages/technologies used across
  github_repositories — reordered to prioritize whatever's relevant to this
  job. Every item must already exist in one of those sources; never add or
  drop a genuine skill. Write it compactly: a flat comma-separated list, with
  no per-category label prefixes ("Languages:", "Tools:", ...).
- experience bullets: wording only, and concise — aim for about 1-2 lines
  (roughly 110-220 characters). This is a length target, not a hard ceiling
  on top of STEP 2's restructuring above: when a genuine keyword gap or an
  unused quantified detail justifies a rewrite, a few extra words to fit it
  in cleanly is fine — prefer cutting a weaker word elsewhere first, but
  don't leave real, supportable detail out just to match the original's
  exact length. A resume that runs long loses an entire project or
  experience entry to fit the 2-page budget (see resume_page_fitter.py),
  not just this one bullet — so this is still a real constraint, just not
  one that should silently override STEP 2.
- projects: description, technologies, and each notable_achievements bullet
  may all be reworded/surfaced the same way as experience bullets — every
  project bullet is a real block_id you were given, not just the
  description. Lead with the outcome/impact of the project (what it did,
  what changed as a result), not just what it's built with; entry order is
  decided upstream, not by you.
  If two or more projects share similar high-level subject matter (e.g. two
  projects that are both, at a glance, "a stock valuation tool"), don't let
  their descriptions restate the same angle — you can see every project in
  candidate_profile, so differentiate them by each project's actual
  distinct technical approach or outcome (a different modeling technique, a
  different interface, a different specific problem solved), using that
  project's own real details. A reader skimming the Projects section should
  be able to tell what's actually different about each one, not read the
  same idea twice in different words.
Reasoning output — separate from editable_blocks, this is how you explain
what you did instead of the resume itself:
- highlights: one entry per *section* you touched (Summary, Skills,
  Experience, Projects — not one per bullet), grouping everything you did
  in that section into a single sentence. Never write a separate highlight
  for every small edit — that reads as repetitive noise, not a report. Each
  highlight's summary must say what changed AND why it matters for this
  job in one sentence (a specific required/preferred skill, responsibility,
  or matched/missing keyword — not just "included matched keywords").
  Distinguish precisely what kind of change this was:
    - reordering existing content needs no hedging: "Reordered technical
      skills to prioritize Python, React, and AWS."
    - surfacing something already true of the candidate is not the same as
      adding something new — say "included" or "surfaced from your
      profile", never "added", when the underlying fact already existed
      somewhere in candidate_profile: "Included Apache Spark from your
      GitHub projects since the job lists it as a required skill."
    - a genuinely new phrase woven into wording (same fact, clearer words)
      can say "highlighted" or "rewrote": "Highlighted JWT authentication
      in your FluxPro bullet because secure auth is explicitly required."
  impact: rate each highlight "high" (summary rewrite, skills reordering,
  a bullet that now demonstrates a required skill it didn't before),
  "medium" (a bullet reworded for clarity/impact without closing a
  keyword gap), or "low" (a small wording/phrasing tweak).
  If you left a section entirely unchanged because it already covered the
  job well, do not write a highlight for it — silence means no change.
- keywords_skipped: one entry per missing_keyword you deliberately did not
  weave in, with a one-sentence reason tied to the actual gap ("Candidate
  profile has no demonstrated Redis experience", not "not relevant").
  Never include a missing_keyword here that you did in fact address
  somewhere in editable_blocks.

Never allowed:
- Never invent skills, employers, titles, dates, or achievements not already in
  the candidate profile.
- Never claim a missing_keyword as something the candidate has done. You may
  say "experience with similar systems/tools" only if that's already implied by
  real experience in the profile; otherwise leave the gap alone.
- Never adopt a marketing or exaggerated tone — plain, technical, ATS-parseable
  language only.
- Never move a technology or keyword into a block whose real subject
  matter doesn't genuinely involve it, even when it's true of the candidate
  elsewhere — see the ATS keyword test section above.

Schema:
{
  "patches": [
    {"block_id": string, "new_text": string}
  ],
  "highlights": [
    {"section": string, "summary": string, "impact": "high" | "medium" | "low"}
  ],
  "keywords_skipped": [
    {"keyword": string, "reason": string}
  ]
}"""


class ResumeGenerationAgent:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def generate(self, profile: dict, job: dict, layout_document: dict | None = None) -> dict:
        # layout_document is accepted for call-site compatibility with
        # api/v1/resume.py (which reads it from UserProfile.layout_document)
        # but no longer used — real in-place document editing was removed
        # (see the 2026-08 dead-code cleanup); every resume renders via the
        # generic template (resume_renderer.py) now. The column/parameter
        # itself is a separate, not-yet-made decision to drop.
        keyword_report = match_keywords(profile, job)
        keyword_report = _augment_with_inferred_keywords(keyword_report, profile, job)
        ranked = rank_profile(profile, keyword_report)

        layout = build_synthetic_layout(ranked.profile)
        patches, highlights, keywords_skipped = await self._optimize(layout, ranked.profile, job, keyword_report)

        patch_result = apply_patches(layout, patches)
        if patch_result.rejected_block_ids:
            logger.warning("Optimization LLM referenced unknown block_ids: %s", patch_result.rejected_block_ids)

        optimized_resume = flatten_layout_to_resume(ranked.profile, patch_result.document)
        optimized_resume = merge_overlapping_bullets(optimized_resume)
        ats_score = compute_ats(keyword_report)

        added_keyword_candidates = find_added_keywords(keyword_report.missing, optimized_resume)
        added_keywords = filter_backed_keywords(profile, added_keyword_candidates)
        unbacked_keywords = [kw for kw in added_keyword_candidates if kw not in added_keywords]
        if unbacked_keywords:
            logger.warning(
                "generate: %d keyword(s) appear in the optimized wording with no textual basis "
                "anywhere in the candidate profile — not crediting as added: %s",
                len(unbacked_keywords), unbacked_keywords,
            )

        report = self._build_report(
            ranked.profile, job, layout, patch_result.document, optimized_resume,
            keyword_report, added_keywords, highlights, keywords_skipped,
            ranked.ranking_reasons.get("projects") or [],
        )

        for issue in validate_optimization_integrity(
            profile, ranked.profile, optimized_resume, report.ats_score_before, report.ats_score_after,
        ):
            logger.warning("generate: optimization integrity issue — %s", issue)

        # Always None/False now — see the comment on layout_document above.
        render_layout, layout_preserved = None, False

        return {
            "ats_score": ats_score,
            "matched_keywords": keyword_report.matched,
            "missing_keywords": keyword_report.missing,
            "added_keywords": added_keywords,
            "optimized_resume": optimized_resume,
            "patches": [patch.model_dump() for patch in patches],
            "render_layout": render_layout,
            "layout_preserved": layout_preserved,
            "report": report.model_dump(),
        }

    def _build_report(
        self,
        ranked_profile: dict,
        job: dict,
        layout: ResumeLayoutDocument,
        patched_document: ResumeLayoutDocument,
        optimized_resume: dict,
        keyword_report: KeywordReport,
        added_keywords: list[str],
        highlights: list[ChangeHighlight],
        keywords_skipped: list[KeywordSkipReason],
        project_ranking_reasons: list[list[str]],
    ) -> OptimizationReport:
        """
        Assembles OptimizationReport from this same generation run. Only
        `highlights` and `keywords_skipped` are the LLM's own words (see
        _SYSTEM_PROMPT's Reasoning output section) — every count/score below
        is derived here from patches/keyword data, not asked of the model,
        so it can't drift from what actually happened.
        """
        ats_score_before = compute_ats(keyword_report)
        after_report = KeywordReport(
            matched=[*keyword_report.matched, *added_keywords],
            missing=[kw for kw in keyword_report.missing if kw not in added_keywords],
        )
        ats_score_after = compute_ats(after_report)

        modified = _modified_block_ids(layout, patched_document)
        project_indices_modified = {
            int(match.group(1))
            for block_id in modified
            if (match := re.match(r"projects\[(\d+)\]", block_id))
        }
        rewrite_similarity_avg, rewrite_quality_issues = _rewrite_quality(
            layout, patched_document, added_keywords,
        )
        project_ranking = [
            {"name": project.get("name"), "matched_on": reasons}
            for project, reasons in zip(ranked_profile.get("projects") or [], project_ranking_reasons)
        ]

        return OptimizationReport(
            ats_score_before=ats_score_before,
            ats_score_after=ats_score_after,
            matched_keywords_before=len(keyword_report.matched),
            matched_keywords_after=len(after_report.matched),
            keywords_added=added_keywords,
            # Trust but verify: only credit a skip reason the model didn't
            # contradict by also successfully weaving that keyword in.
            keywords_skipped=[kw for kw in keywords_skipped if kw.keyword not in added_keywords],
            unused_candidate_skills=unused_candidate_skills(ranked_profile, job),
            skills_reordered=_skills_reordered(ranked_profile, optimized_resume.get("skills") or []),
            summary_rewritten="summary" in modified,
            experience_bullets_modified=sum(1 for block_id in modified if block_id.startswith("work_experience[")),
            projects_modified=len(project_indices_modified),
            highlights=highlights,
            rewrite_similarity_avg=rewrite_similarity_avg,
            rewrite_quality_issues=rewrite_quality_issues,
            project_ranking=project_ranking,
        )

    async def _optimize(
        self, layout: ResumeLayoutDocument, ranked_profile: dict, job: dict, keyword_report: KeywordReport
    ) -> tuple[list[ContentPatch], list[ChangeHighlight], list[KeywordSkipReason]]:
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
        patches = [ContentPatch(**patch) for patch in result["patches"]]
        highlights = [ChangeHighlight(**h) for h in result.get("highlights") or []]
        keywords_skipped = [KeywordSkipReason(**k) for k in result.get("keywords_skipped") or []]
        return patches, highlights, keywords_skipped


def _augment_with_inferred_keywords(keyword_report: KeywordReport, profile: dict, job: dict) -> KeywordReport:
    """
    Offers inferable process/methodology/soft-skill keywords (see
    inferable_keywords.py) as additional missing_keyword candidates,
    whenever the job cares about one (its label overlaps a job
    skill/technology/keyword/responsibility/qualification term) and the
    candidate's own text already evidences it. Closes the structural gap
    where match_keywords only ever compares literal technology tags —
    these still go through the optimization LLM's normal truthful-support
    test (see _SYSTEM_PROMPT's ATS keyword test) before being woven in;
    this function only ever adds to `missing`, never to `matched`, since
    nothing has actually been credited on the resume yet.
    """
    job_terms_lower = {
        term.strip().lower()
        for field in ("skills", "technologies", "keywords", "responsibilities", "qualifications")
        for term in (job.get(field) or [])
        if term
    }
    if not job_terms_lower:
        return keyword_report

    already_known_lower = {term.strip().lower() for term in (*keyword_report.matched, *keyword_report.missing)}
    inferred = [
        keyword for keyword in infer_available_keywords(profile)
        if keyword.lower() not in already_known_lower and _job_cares_about(keyword, job_terms_lower)
    ]
    if not inferred:
        return keyword_report
    return KeywordReport(matched=keyword_report.matched, missing=[*keyword_report.missing, *inferred])


def _job_cares_about(keyword: str, job_terms_lower: set[str]) -> bool:
    # Substring match in either direction: handles the job stating a short
    # form ("Agile", "SDLC") against a longer taxonomy label, and vice versa.
    keyword_lower = keyword.lower()
    return any(term in keyword_lower or keyword_lower in term for term in job_terms_lower)


def _modified_block_ids(before: ResumeLayoutDocument, after: ResumeLayoutDocument) -> set[str]:
    before_text = {block.block_id: block.text for section in before.sections for block in section.blocks}
    after_text = {block.block_id: block.text for section in after.sections for block in section.blocks}
    return {
        block_id
        for block_id, text in after_text.items()
        if (before_text.get(block_id) or "").strip() != (text or "").strip()
    }


# A block whose text stayed >= this similar to its original wording despite
# claiming to now carry a newly-added keyword is a strong signal the keyword
# was stitched onto the end rather than woven into a genuine rewrite — see
# the STEP 1/STEP 2 editing philosophy in _SYSTEM_PROMPT. Only flagged
# (logged), never blocking — a real diff-based signal is still coarser than
# the LLM's own judgment, so this surfaces the suspicion, it doesn't decide.
_STITCHED_KEYWORD_SIMILARITY_THRESHOLD = 0.92


def _rewrite_similarity(before: str, after: str) -> float:
    return SequenceMatcher(None, before.strip().lower(), after.strip().lower()).ratio()


def _rewrite_quality(
    before: ResumeLayoutDocument, after: ResumeLayoutDocument, added_keywords: list[str]
) -> tuple[float | None, list[str]]:
    """
    Measures how much each *changed* block's wording actually moved, and
    flags a specific failure shape: a block that claims to now carry an
    added keyword (find_added_keywords found the keyword's text inside it)
    but is implausibly similar to its original wording. Returns (mean
    similarity across changed blocks, or None if nothing changed; the list
    of flagged block_ids with a reason).
    """
    before_text = {block.block_id: block.text for section in before.sections for block in section.blocks}
    after_text = {block.block_id: block.text for section in after.sections for block in section.blocks}

    similarities: list[float] = []
    issues: list[str] = []
    for block_id, new_text in after_text.items():
        old_text = before_text.get(block_id) or ""
        if not old_text.strip() or not (new_text or "").strip():
            continue
        if old_text.strip() == new_text.strip():
            continue  # unchanged blocks don't count toward "rewrite" magnitude
        similarity = _rewrite_similarity(old_text, new_text)
        similarities.append(similarity)

        carries_added_keyword = any(
            _keyword_appears_in(kw, new_text.lower()) for kw in added_keywords
        )
        if carries_added_keyword and similarity >= _STITCHED_KEYWORD_SIMILARITY_THRESHOLD:
            issues.append(
                f"{block_id}: claims a newly-added keyword but is {similarity:.0%} similar "
                f"to its original wording — likely stitched on rather than woven in"
            )

    avg = round(sum(similarities) / len(similarities), 4) if similarities else None
    return avg, issues


def _skills_reordered(ranked_profile: dict, optimized_skills: list[str]) -> bool:
    """
    True if the optimized skills list's relative order differs from the
    order skills naturally appear across the profile's own fields — the
    synthetic layout's skills block always starts blank (see
    synthetic_profile_layout.py), so there's no single "original skills
    text" to diff against; this compares against that natural baseline
    order instead. Only the subset of skills present in both is compared,
    so a genuinely dropped/renamed skill doesn't by itself count as
    "reordered".
    """
    baseline = [
        item.strip().lower()
        for field in PROFILE_SKILL_FIELDS
        for item in (ranked_profile.get(field) or [])
        if item
    ]
    optimized = [item.strip().lower() for item in optimized_skills if item]
    common_baseline = [item for item in baseline if item in optimized]
    common_optimized = [item for item in optimized if item in baseline]
    return common_baseline != common_optimized
