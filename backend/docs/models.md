# Data Models

**Design principle:** Pipeline first, database second. Every model must justify
its existence by serving the current phase. Nothing is built ahead of need.

---

## Active Models (Phase 1–3)

| Model | File | Phase | Purpose |
|---|---|---|---|
| `Job` | models/job.py | 1 — Job Analysis | Stores job posting + structured AI analysis output |
| `UserProfile` | models/profile.py | 2 — Profile Ingestion | Stores unified candidate data from all sources |
| `ResumeVersion` | models/application.py | 3 — Resume Optimiser | Stores AI-generated resume content + PDF URL |

---

## Phase 1 — Job Analysis

**Model:** `Job`

**Input:** Job posting URL or raw text

**Output stored:**
```json
{
  "title": "",
  "company": "",
  "skills": [],
  "technologies": [],
  "experience": "",
  "responsibilities": [],
  "qualifications": [],
  "keywords": []
}
```

**Key fields:**
- `raw_text` — the original posting text sent to the AI
- `posting_text_hash` — SHA-256 of the normalised text, unique index prevents re-analysing the same listing
- `title`, `company`, `skills`, `technologies`, `experience`, `responsibilities`, `qualifications`, `keywords` — direct output of the Job Analysis Agent stored as JSONB
- `analyzed_at` — when analysis ran

**What it answers:** Can we understand what the ATS is looking for?

---

## Phase 2 — User Profile Ingestion

**Model:** `UserProfile`

**Input:** Resume PDF, LinkedIn URL, GitHub URL, Portfolio URL (optional)

**Output stored:**
```json
{
  "name": "",
  "skills": [],
  "projects": [],
  "experience": [],
  "education": [],
  "links": {}
}
```

**Key fields:**
- `resume_pdf_url`, `linkedin_url`, `github_url`, `portfolio_url` — ingestion sources
- `skills`, `experience`, `education`, `projects` — JSONB arrays populated by the ingestion agents
- `links` — JSONB dict of all candidate URLs
- `name`, `email` — identity fields (no User FK until auth is introduced)
- `updated_at` — tracks when the profile was last refreshed from any source

**Why JSONB instead of separate tables:** Ingestion agents write structured JSON directly.
Separate relational tables (WorkExperience, Skill, etc.) are only introduced when a
later phase needs to query or filter across profiles at the database level. Right now
everything passes through the AI, so flat JSONB is sufficient and far simpler.

**What it answers:** Can we accurately understand the candidate?

---

## Phase 3 — Resume Optimiser

**Model:** `ResumeVersion`

**Input:** `UserProfile` + `Job`

**Output stored:**
```json
{
  "summary": "",
  "skills": [],
  "experience": [{ "title": "", "company": "", "start": "", "end": "", "bullets": [] }],
  "education": [{ "institution": "", "degree": "", "year": "" }],
  "projects": [{ "name": "", "description": "", "tech": [] }]
}
```

**Key fields:**
- `user_profile_id` → FK to `UserProfile`
- `job_id` → FK to `Job`
- `content` — JSONB structured resume produced by the CV Optimisation Agent
- `ats_score` — keyword match score (0–100) set by ATS Optimisation Agent
- `rendered_pdf_url` — S3 URL populated by the render worker once the PDF is ready

**Immutability:** Each optimisation run inserts a new row. Existing rows are never
updated. This means the full generation history is preserved for every profile/job pair.

**What it answers:** Can we produce a tailored, exportable resume?

---

## Shared Infrastructure

**`base.py`** — two classes used by all three models:
- `Base` (`DeclarativeBase`) — SQLAlchemy's single registry. All models inherit from it.
  Required for `Base.metadata.create_all` in the app lifespan.
- `PrimaryKeyMixin` — UUID primary key shared across all models. UUID is used over
  integer so IDs are safe to generate without a database round-trip and don't expose row counts.

`TimestampMixin` is defined but unused — will be removed in the next cleanup pass.

---

## Deferred Models

These do not exist in the codebase. They are listed here so the decision is documented,
not forgotten.

| Model | Introduce when |
|---|---|
| `User` + `UserSession` | Auth / user management is added |
| `CoverLetterVersion` | Phase 4 — Cover letter generation |
| `ApplicationQuestion` + `AnswerVersion` | Phase 5 — Application question answering |
| `Application` | Phase 5 — Application tracking |
| `Certification` | Ingestion pipeline handles certs distinctly |
| `SensitiveFact` | Question agent handles sensitive routing |
| `WritingSample` + `WritingFeedback` | Style engine is built |
| `ProfileEvent` | GDPR audit compliance is required |
| `Embedding` | RAG retrieval replaces full-context injection |
| `PreferenceSignal` | Learning agent is built |
| `Company` | Analytics require cross-profile company queries |
| `Event` | Analytics funnel is worth measuring |
