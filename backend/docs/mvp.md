# Pathfinder MVP

**Goal:** A user opens a job posting, extracts it via the Chrome Extension, uploads a CV, and receives an ATS-optimised PDF tailored to that specific job.

Everything else is out of scope until this workflow is validated.

---

## Workflow

```
Chrome Extension (extension/src/)
        │  POST raw job text + URL
        ▼
POST /api/v1/jobs/analyze
        │
        ▼
JobAnalysisAgent                   ← backend/services/job_analysis_agent.py
        │  Gemini 2.5 Flash (Vertex AI)
        ▼
JobAnalysis (structured JSON)      ← backend/schemas/jobs.py → JobResponse
        │  persisted to Job model
        ▼
Job (Postgres)                     ← backend/models/job.py
        │
        ▼
[Phase 2] CandidateService
        │  CV upload + optional LinkedIn/GitHub URLs
        ▼
UserProfile (Postgres)             ← backend/models/profile.py
        │
        ▼
[Phase 3] ResumeService
        │  ResumeOptimisationAgent
        ▼
ResumeVersion + PDF                ← backend/models/application.py
```

---

## Current Status

| Phase | Responsibility | Status | Key Files |
|---|---|---|---|
| 1 — Job Analysis | Extract structured data from a job posting | **Built** | `services/job_analysis_agent.py`, `api/v1/jobs.py`, `models/job.py`, `schemas/jobs.py` |
| 2 — Candidate Profile | Build a structured profile from CV + optional links | Not started | `models/profile.py` (model exists, service not wired) |
| 3 — Resume Optimisation | Generate ATS-optimised resume and PDF | Not started | `models/application.py` (model exists, agent not built) |

---

## Phase 1 — Job Analysis

**Endpoint:** `POST /api/v1/jobs/analyze`

**Request** (`AnalyzeJobRequest`):
```json
{ "raw_text": "...", "url": "https://..." }
```

**Agent** (`JobAnalysisAgent`):
- Model: `gemini-2.5-flash` via Vertex AI (`farmpulse-496900`, `us-central1`)
- Temperature: 0 (deterministic extraction)
- Structured output: `application/json`
- Never invents. Returns `null` or `[]` for missing fields.

**Output stored** (`Job` model, `backend/models/job.py`):
```json
{
  "title": "...",
  "company": "...",
  "experience": "...",
  "skills": [],
  "technologies": [],
  "responsibilities": [],
  "qualifications": [],
  "keywords": []
}
```

**Response** (`JobResponse`, `backend/schemas/jobs.py`):
```json
{
  "id": "uuid",
  "url": "...",
  "title": "...",
  "company": "...",
  "experience": "...",
  "skills": [],
  "technologies": [],
  "responsibilities": [],
  "qualifications": [],
  "keywords": [],
  "analyzed_at": "..."
}
```

**Deduplication:** `posting_text_hash` (SHA-256 of normalised text) prevents re-analysing the same listing.

---

## Phase 2 — Candidate Profile

**Service:** `CandidateService` (not yet built)

**Input:** CV upload (PDF), optional LinkedIn URL, GitHub URL, Portfolio URL.

**Agent** (`CandidateProfileAgent`, not yet built):
- Extracts and combines personal info, skills, work experience, education, projects, certifications, links.
- Never invents. Returns empty arrays or null for missing fields.

**Output stored** (`UserProfile` model, `backend/models/profile.py`):
```json
{
  "name": "",
  "skills": [],
  "experience": [],
  "education": [],
  "projects": [],
  "links": {}
}
```

See `backend/docs/models.md` — Phase 2 section for full field reference.

---

## Phase 3 — Resume Optimisation

**Service:** `ResumeService` (not yet built)

**Input:** `UserProfile` + `Job` (both from Postgres by ID)

**Agent** (`ResumeOptimisationAgent`, not yet built):
- Tailors the resume to the job requirements.
- Improves keyword alignment without inventing experience.
- Emphasises relevant projects and achievements.
- Maintains factual accuracy and the candidate's own voice.

**Output stored** (`ResumeVersion` model, `backend/models/application.py`):
```json
{
  "summary": "",
  "skills": [],
  "experience": [{ "title": "", "company": "", "start": "", "end": "", "bullets": [] }],
  "education": [{ "institution": "", "degree": "", "year": "" }],
  "projects": [{ "name": "", "description": "", "tech": [] }]
}
```

**Rendering:** A docx-sourced profile gets its original file edited in place (preserving layout); otherwise a generic PDF template is rendered. URL/format stored in `rendered_file_url`/`rendered_file_format`.

**Immutability:** Each optimisation run inserts a new row. Existing rows are never updated.

---

## Chrome Extension

**Location:** `extension/`

| File | Responsibility |
|---|---|
| `manifest.json` | MV3 manifest, declares `sidePanel`, `storage`, `scripting` permissions |
| `src/background.js` | Service worker — auth, message routing, badge state |
| `src/content.js` | Page text extraction, sends raw text to background |
| `src/sidepanel/sidepanel.{html,js,css}` | Side panel UI — shows job summary, triggers workflow |

**Current behaviour:** On page visit the content script scrapes visible text and posts it to the side panel. The side panel sends `{ raw_text, url }` to `POST /api/v1/jobs/analyze` and displays the structured result.

---

## Backend Architecture

```
backend/
├── app/main.py                  FastAPI app, lifespan (DB init)
├── core/config.py               Settings via pydantic-settings
├── database/session.py          Async SQLAlchemy session + get_db dep
├── api/v1/
│   ├── router.py                Mounts all v1 routers
│   └── jobs.py                  POST /jobs/analyze
├── schemas/jobs.py              AnalyzeJobRequest, JobResponse
├── models/
│   ├── base.py                  DeclarativeBase, PrimaryKeyMixin (UUID)
│   ├── job.py                   Job — Phase 1
│   ├── profile.py               UserProfile — Phase 2
│   └── application.py          ResumeVersion — Phase 3
├── services/
│   ├── job_analysis_agent.py    JobAnalysisAgent (Gemini via Vertex AI)
│   └── repository/
│       └── job_repository.py   JobRepository — create_from_analysis
└── docs/
    └── models.md                Data model reference (all three phases)
```

**Rule:** Repositories are the only layer that talks to the database. Agents are pure transformation services — they never access the database directly.

---

## Definition of Done

The MVP is complete when a user can:

1. Open a job posting in Chrome.
2. Use the extension to extract the job text.
3. Receive a structured job analysis (Phase 1 — **done**).
4. Upload a CV and optionally provide LinkedIn / GitHub URLs.
5. Receive a professionally formatted, ATS-optimised PDF tailored to that specific job.

---

## Out of Scope (MVP)

Authentication, billing, payments, analytics, cover letters, AI form filling, interview prep, email integrations, browser sync, team features, notifications, recommendation systems, application tracking.
