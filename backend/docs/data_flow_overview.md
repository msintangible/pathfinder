# Backend Data Flow Overview

This is a map of the Pathfinder backend for a developer picking up the codebase for the first time. It covers how data moves through the system end to end, and what each file is for. It is deliberately an overview — read the file itself for its internals.

## System summary

The backend is a FastAPI application (`backend/app/main.py`) backed by Postgres via SQLAlchemy's async ORM. All AI work — profile extraction, job-posting analysis, and resume tailoring — goes through Gemini (`google.genai`), called directly from three "agent" service classes; there is no other LLM provider wired up. The only client is the Chrome extension in `extension/`; there is no separate frontend web app, so every route is designed around what that extension calls.

Every route lives under `/v1` (mounted in `main.py`) and is grouped into four routers included by `api/v1/router.py`: `auth`, `profile`, `jobs`, `resume`. All routes except `POST /auth/anonymous` require a bearer JWT.

## Auth flow

`POST /v1/auth/anonymous` (`api/v1/auth.py`) is the only auth route. It creates a `User` row (`models/user.py`, via `services/repository/user_repository.py::UserRepository`) and returns a long-lived JWT (`core/security.py::create_anonymous_token`, 365-day expiry by default). There is no email/password login yet — `User.email`/`hashed_password` exist but are unused, reserved for a future upgrade path that would populate them on the same row rather than requiring a schema change.

Every other route depends on `core/security.py::get_current_user` (or, for the one route that needs to work from a plain browser navigation, `get_current_user_allow_query_token`) to decode that JWT and load the `User`, which is how per-user ownership checks work throughout the rest of the API.

## Profile ingestion flow

`POST /v1/profile/import` (`api/v1/profile.py`) accepts an optional CV file (PDF or DOCX, 10MB cap) plus optional LinkedIn/GitHub/portfolio URLs (LinkedIn has no live fetcher — only `linkedin_text` pasted by the client is used).

1. An uploaded file's text is pulled out by `services/pdf_text_extractor.py` or `services/docx_text_extractor.py`. The original file bytes are also saved via `services/storage/local_storage.py::LocalResumeStorage` purely for reference/download — they are no longer parsed for layout (see "Removed architecture" below).
2. `services/github_profile_fetcher.py::fetch_github_profile` and `services/portfolio_scraper.py::fetch_portfolio_text` run concurrently via `asyncio.gather`. Both never raise — a bad URL, private repo, rate limit, or network error just degrades to no data rather than failing the whole import. The portfolio scraper is SSRF-guarded: before every request (and before following each redirect hop) it resolves the target hostname and rejects anything that isn't a public IP, specifically blocking the cloud metadata address `169.254.169.254`. Private/loopback addresses are allowed only when `settings.environment == "development"`, so a developer can point it at localhost; this allowance must be turned off in production by setting the environment explicitly.
3. All gathered text is combined into one Gemini call via `services/candidate_profile_agent.py::CandidateProfileAgent.analyze`, which extracts a structured profile validated against `schemas/profile.py::CandidateProfile`.
4. The result is deduplicated by `services/profile_deduplicator.py::dedupe_profile` — a deterministic safety net that fuzzy-merges near-duplicate entries (e.g. the same job described slightly differently across resume/LinkedIn) and collapses bullets that restate each other, since the LLM's own "don't duplicate" instruction is only advisory.
5. The profile is persisted via `services/repository/profile_repository.py::ProfileRepository` into the `UserProfile` table (`models/profile.py`), which stores every extracted field as JSONB rather than a normalized relational schema (deliberate, until querying across profiles is actually needed).

If neither a file nor any usable URL/text yields content, the endpoint returns 422 rather than calling the LLM on nothing — an empty prompt tends to make the model fabricate a profile despite instructions not to.

`POST /v1/profile/restore` (`api/v1/profile.py`) re-persists a client-cached `CandidateProfile` with no LLM call — used when the client has profile data cached locally but the backend row is gone (e.g. after a database reset).

## Job analysis flow

`POST /v1/jobs/analyze` (`api/v1/jobs.py`) takes raw job-posting text (+ optional URL), runs one Gemini call via `services/job_analysis_agent.py::JobAnalysisAgent.analyze` (truncating the input to 5,000 characters first, for latency), and validates the result against `schemas/jobs.py::JobAnalysis`.

The result is persisted via `services/repository/job_repository.py::JobRepository`, keyed by a SHA-256 hash of the normalized posting text (`Job.posting_text_hash`, unique-indexed) so the same listing is never analyzed twice — reposted/cross-posted listings resolve to the same `Job` row. Jobs are not owned by a user (any authenticated caller can analyze/reuse one).

**Known inefficiency**: the Gemini call happens before the hash-dedup check (`JobRepository.create_from_analysis` computes the hash and checks for an existing row only after the caller already awaited `agent.analyze`), so a genuine duplicate posting still pays for a wasted LLM call. This is a known issue, not something addressed by this doc.

## Resume generation flow

`POST /v1/resumes/generate` (`api/v1/resume.py`) is the core pipeline. Given a `job_id` and `user_profile_id`, it loads both rows (404 if the profile isn't found or isn't owned by the caller — the same 404 is used for "doesn't exist" and "isn't yours" so a guessed ID can't be used to probe ownership), then runs `services/resume_generation_agent.py::ResumeGenerationAgent.generate`, which orchestrates the rest of this flow:

1. **Keyword matching** — `services/keyword_matcher.py::match_keywords` compares the job's `skills`/`technologies`/`keywords` against the candidate's flat skill-list fields plus per-entry tags (`work_experience`/`projects`/`github_repositories` each carry their own `technologies`/`skills_demonstrated` fields) to produce matched/missing keyword lists.
2. **Inferred keywords** — `services/inferable_keywords.py::infer_available_keywords` offers a curated, evidence-gated set of process/methodology/soft-skill keywords (e.g. "Agile", "CI/CD", "Problem Solving") the candidate's own text supports even when never mentioned literally. `resume_generation_agent.py::_augment_with_inferred_keywords` adds these to the missing-keyword list only when the job actually cares about them; nothing is auto-credited as matched.
3. **Ranking** — `services/relevance_ranker.py::rank_profile` reorders and caps `work_experience` (max 5), `projects` (max 3 — a hard product requirement), and `github_repositories` (max 4) by overlap with matched keywords. This is the only place that decides which entries survive and in what order; nothing downstream can add or reorder entries.
4. **Synthetic layout** — `services/synthetic_profile_layout.py::build_synthetic_layout` flattens the ranked profile into a `ResumeLayoutDocument` (`schemas/resume_layout.py`) of `{block_id, text}` blocks. Only wording-bearing fields (headline, summary, skills, bullets, project descriptions/achievements) get block IDs — title, company, dates, and entry count are never given one, making them structurally untouchable by the LLM.
5. **Optimization (the one Gemini call)** — `ResumeGenerationAgent._optimize` sends the job, ranked profile, matched/missing keywords, and editable blocks to Gemini, and gets back `{patches, highlights, keywords_skipped}` validated against `schemas/resume.py::OptimizationPatchResponse`. This is a deliberate, load-bearing architecture rule: the LLM only ever returns `ContentPatch[]` (`{block_id, new_text}`) — never a modified layout or resume structure directly. Everything else (counts, scores) is computed in code from the same run so it can't drift from what actually happened.
6. **Patch application** — `services/patch_engine.py::apply_patches` is the sole component permitted to turn those patches into an updated `ResumeLayoutDocument`, redistributing each block's new text across its `RunSpan`s. Most of this module's redistribution logic (multi-run/hyperlink-preserving) was written for real in-place document editing and is currently unreachable dead code in production, since the only caller today always produces single-run blocks — see "Removed architecture" below.
7. **Flattening back** — `synthetic_profile_layout.py::flatten_layout_to_resume` rebuilds the external `OptimizedResume` shape from the patched layout, copying title/company/dates/entry-count straight through from the ranked profile (never from the LLM).
8. **Second dedup pass** — `profile_deduplicator.py::merge_overlapping_bullets` collapses bullets that ended up restating each other after tailoring, since a patch can only reword a block, never delete one.
9. **Validation (log-only)** — `services/optimization_validator.py::validate_optimization_integrity` compares the final resume back against its source profile (identity fields preserved, no unexplained entry-count growth, ATS score never regressed, etc.), and `services/resume_validator.py::validate_resume_structure` checks the final resume's shape in isolation (name/contact/links present, no duplicate or suspiciously-similar-sounding projects). Both only log warnings; neither ever blocks generation — e.g. a candidate with no portfolio link is a real, expected gap, not a bug.
10. **Page-budget rendering** — `services/resume_page_fitter.py::render_within_page_limit` renders via `services/resume_renderer.py::render_pdf` (Jinja2 template `templates/resume.html` + xhtml2pdf) and, if the PDF exceeds the 2-page budget, trims progressively — the single shortest bullet from the lowest-relevance entry first, and only once no entry has a spare bullet, a whole project or experience entry (lowest-relevance last, since both sections are already sorted most-relevant-first) — re-rendering after each trim.
11. **Scoring** — `services/ats_scorer.py::compute_ats` turns a `KeywordReport` (matched/missing counts) into a 0–100 score, computed both before and after optimization.
12. **Persistence** — the result (rendered PDF bytes saved via `LocalResumeStorage`, plus matched/missing/added keywords, ATS score, and the full `OptimizationReport`) is persisted via `services/repository/resume_repository.py::ResumeRepository` into `ResumeVersion` (`models/application.py`). Each generation run is immutable — a new row every time, not an update.

`GET /v1/resumes/{id}/download` (`api/v1/resume.py`) serves the saved PDF back via `FileResponse`, gated on ownership derived through the linked `UserProfile` (since `ResumeVersion` has no `user_id` of its own). It uses `get_current_user_allow_query_token` specifically because opening a PDF via a plain browser-tab link can't attach an `Authorization` header.

## File reference

### `api/v1/`
- `router.py` — mounts the four sub-routers (`auth`, `jobs`, `profile`, `resume`) under one `APIRouter`.
- `auth.py` — `POST /auth/anonymous`, the only auth route; issues the anonymous JWT.
- `profile.py` — `POST /profile/import` and `POST /profile/restore`; file/URL intake, extraction, and persistence for candidate profiles.
- `jobs.py` — `POST /jobs/analyze`; job-posting intake, analysis, and dedup-by-hash persistence.
- `resume.py` — `POST /resumes/generate` and `GET /resumes/{id}/download`; the resume tailoring pipeline and file serving.

### `services/` (agents and pipeline logic)
- `candidate_profile_agent.py` — `CandidateProfileAgent`; the one Gemini call that turns raw resume/LinkedIn/GitHub/portfolio text into a structured `CandidateProfile`.
- `job_analysis_agent.py` — `JobAnalysisAgent`; the one Gemini call that turns a raw job posting into structured `JobAnalysis`.
- `resume_generation_agent.py` — `ResumeGenerationAgent`; orchestrates the full resume-tailoring pipeline and owns the one Gemini call that produces wording patches.
- `docx_text_extractor.py` / `pdf_text_extractor.py` — plain-text extraction from an uploaded DOCX/PDF.
- `github_profile_fetcher.py` — fetches a public GitHub profile bio and top repos by star count via the GitHub REST API; never raises.
- `portfolio_scraper.py` — SSRF-guarded fetch-and-clean of a candidate's portfolio site text.
- `profile_deduplicator.py` — deterministic dedup: `dedupe_profile` runs after profile extraction (merges near-duplicate entries/bullets); `merge_overlapping_bullets` runs after resume optimization (collapses bullets a tailoring rewrite left overlapping).
- `keyword_matcher.py` — `match_keywords` (job keywords vs. candidate profile), `unused_candidate_skills`, `find_added_keywords`, `filter_backed_keywords` (only credit an added keyword if it has real textual basis in the profile).
- `inferable_keywords.py` — curated, evidence-gated taxonomy of process/methodology/soft-skill keywords inferable from how a candidate describes real work, not just literal skill tags.
- `relevance_ranker.py` — `rank_profile`; reorders and caps work experience/projects/GitHub repos by relevance to matched keywords — the sole authority on entry survival/order.
- `synthetic_profile_layout.py` — builds the profile-relative `ResumeLayoutDocument` the LLM edits (`build_synthetic_layout`) and rebuilds the external resume shape from a patched layout (`flatten_layout_to_resume`).
- `patch_engine.py` — `apply_patches`; the only component permitted to turn LLM-authored `ContentPatch[]` into an updated `ResumeLayoutDocument`.
- `optimization_validator.py` — log-only integrity checks comparing the final resume against the source profile it came from.
- `resume_validator.py` — log-only structural completeness checks on the final resume in isolation.
- `resume_page_fitter.py` — enforces the 2-page PDF budget via graduated trimming and re-rendering.
- `resume_renderer.py` — renders an `OptimizedResume` dict to PDF via `templates/resume.html` (Jinja2 + xhtml2pdf); the sole renderer for every resume now.
- `ats_scorer.py` — `compute_ats`; turns a `KeywordReport` into a 0–100 score.
- `llm_output.py` — `parse_llm_json`; shared JSON-parse-and-schema-validate helper used by all three Gemini agents.
- `storage/__init__.py` — `ResumeStorage` abstract interface, the storage boundary so the backing implementation can be swapped (e.g. for S3) without touching the generation pipeline.
- `storage/local_storage.py` — `LocalResumeStorage`; writes rendered PDFs to a local directory, current concrete implementation of `ResumeStorage`.

### `services/repository/`
- `user_repository.py` — `UserRepository`; create/lookup `User` rows.
- `profile_repository.py` — `ProfileRepository`; persist a `CandidateProfile` analysis into `UserProfile`, lookup by id.
- `job_repository.py` — `JobRepository`; persist a `JobAnalysis` into `Job`, with hash-based dedup lookup.
- `resume_repository.py` — `ResumeRepository`; persist a generation run into `ResumeVersion`, lookup by id.

### `models/`
- `base.py` — `Base` (SQLAlchemy declarative base), `PrimaryKeyMixin` (shared UUID primary key), `TimestampMixin`.
- `user.py` — `User`; anonymous or registered account.
- `profile.py` — `UserProfile`; everything known about a candidate, stored mostly as JSONB columns mirroring `CandidateProfile`.
- `job.py` — `Job`; raw posting plus structured analysis, deduplicated by `posting_text_hash`.
- `application.py` — `ResumeVersion`; one immutable row per resume generation run, linking a `UserProfile` and a `Job`.

### `schemas/`
- `auth.py` — `TokenResponse`.
- `profile.py` — `CandidateProfileInput` (agent input), `CandidateProfile` (agent output / API shape), `ProfileImportResponse`/`ProfileRestoreRequest`/`ProfileRestoreResponse`.
- `jobs.py` — `AnalyzeJobRequest`, `JobAnalysis` (agent output), `JobResponse`.
- `resume.py` — `GenerateResumeRequest`, `OptimizedResume` and its nested entry types, `ChangeHighlight`, `KeywordSkipReason`, `ProjectRankingEntry`, `OptimizationReport`, `OptimizationPatchResponse` (the LLM's actual patch-only contract), `ResumeGenerationResponse`.
- `resume_layout.py` — `ResumeLayoutDocument`, `LayoutSection`, `TextBlock`, `RunSpan`, `ContentPatch`, `SectionRole`, plus `DocxAnchor`/`PdfAnchor` (unused now, see below).

### `core/`
- `config.py` — `Settings` (pydantic-settings, env-driven via `.env`) and the module-level `settings` singleton.
- `security.py` — JWT issuance (`create_anonymous_token`) and the `get_current_user`/`get_current_user_allow_query_token` FastAPI dependencies every protected route uses.

### `database/`
- `session.py` — async SQLAlchemy engine/session setup; `get_db` is the FastAPI dependency every route uses to get a session.

### `templates/`
- `resume.html` — the single Jinja2 template every resume renders through, in a fixed canonical section order (`resume_renderer.py::CANONICAL_SECTION_ORDER`).

## Removed architecture: in-place document editing

An earlier architecture parsed a candidate's actual uploaded DOCX/PDF layout and patched it directly in place, preserving their original formatting. This was fully removed as of a 2026-08 dead-code cleanup. Every resume now renders through the one generic HTML template (`resume_renderer.py` + `templates/resume.html`) regardless of whether the candidate uploaded a source document at all (a LinkedIn/GitHub-only profile renders exactly the same way as one built from an uploaded CV).

A few traces of that era remain, deliberately not yet cleaned up:
- `UserProfile.layout_document` and `ResumeVersion.layout_preserved` (DB columns) and the corresponding `layout_preserved` field on `ResumeGenerationResponse` still exist but are always `None`/`False` now.
- `schemas/resume_layout.py`'s `DocxAnchor`/`PdfAnchor` and `RunSpan.hyperlink_url` were designed for real-document parsing; `synthetic_profile_layout.py` (the only builder of a `ResumeLayoutDocument` today) never populates them.
- `patch_engine.py`'s multi-run and hyperlink-preserving redistribution branches are unreachable in production, since the only caller now always produces single-run, no-hyperlink blocks.

These are a deliberate, not-yet-made decision to drop, not an oversight — worth knowing so a future reader doesn't go looking for "the docx renderer" and wonder why it's gone.
