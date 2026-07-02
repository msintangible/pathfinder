# Pathfinder Backend — Production Readiness Review

**Scope**: `backend/` (FastAPI + SQLAlchemy async + Postgres + Gemini LLM agents). Reviewed as of this repo's current working-tree state.
**Method**: Five parallel deep-dive passes over architecture/persistence, AI agent reliability, ingestion/API surface, security, and testing/observability/deployment. Every finding below is grounded in a specific `file:line` reference — this is not generic advice.
**Verdict up front**: the product logic (job analysis → profile import → resume tailoring) is well-factored and the happy path is solid. The gaps are almost entirely in *what happens when something goes wrong* and *who's allowed to do this at all* — there is no auth, no logging, no LLM timeout/retry, no migrations, and no containerization. None of that is unusual for a phase 1–3 prototype; all of it needs to change before "thousands of concurrent users" or "commercial SaaS."

---

## 1. High-Level Architecture Review

**Structure**: three parallel domain triads — `Job`/`JobRepository`/`JobAnalysisAgent`, `UserProfile`/`ProfileRepository`/`CandidateProfileAgent`, `ResumeVersion`/`ResumeRepository`/`ResumeGenerationAgent` — each following the same shape (`services/repository/*.py`: `__init__(session)`, `get_by_id`, `create_from_*`). This consistency is a real strength; a fourth domain (e.g. cover letters) would slot in cleanly.

**Layer separation — mostly good, one outlier**:
- `jobs.py:14-27` and `resume.py:32-75` are thin orchestrators: agent → repository, no inline business rules.
- `profile.py:26-91` is the outlier — it contains real domain logic directly in the route: file-type/size validation, a multi-source sufficiency gate, a documented LLM-hallucination workaround, and hand-rolled `asyncio.gather` concurrency (lines 21-22, 41-42, 49-66, 52-55). This is the largest, most rule-heavy handler in the codebase and the only one without a service object behind it. As more ingestion sources are added, this function will keep growing. **Recommend**: extract a `ProfileImportService`.

**Dependency flow**: clean, one-directional (`api/v1` → `services` → `models`/`schemas`), no circular imports. `get_db` (`database/session.py:22-24`) is idiomatic FastAPI DI. No broader DI container exists, and every route instantiates its own agent/repository fresh per request (e.g. a new `genai.Client` per call — `resume_generation_agent.py:56`) — fine at current scale, a missed reuse opportunity at higher volume.

**Domain organization**: `services/` is a flat folder mixing agents, scrapers, extractors, scorers, and renderers with no subgrouping — inconsistent with `services/repository/` and `services/storage/`, which *do* have their own subpackages. Will get noisy as more of these accumulate.

**Naming drift**: router prefixes are inconsistent — `/jobs` and `/resumes` are plural, `/profile` is singular (`jobs.py:10`, `resume.py:21`, `profile.py:14`). Cosmetic, but visible to every API consumer.

**What will hurt as this grows**:
- No auth/user model — `UserProfile` explicitly has no owner FK (`models/profile.py:16,30`); every ingestion inserts a new row. Retrofitting auth later touches every table.
- No background-job infrastructure — LLM calls and PDF rendering run synchronously inline in the request/response cycle. Notably, **`settings.redis_url` is already defined (`core/config.py:18`) but never used anywhere in `backend/`** — evidence a task queue was planned but never wired up. This will need to happen before real load (see §11 Scalability).
- `app/main.py:16-21`'s `Base.metadata.create_all` implicitly depends on all models having been imported via the router import chain before startup — works today, but is an implicit mechanism a future router refactor could silently break (`models/__init__.py` already re-exports everything for exactly this reason, but `main.py` doesn't use it).

---

## 2. Code Quality Review

**Readability/naming**: generally strong and consistent — agent/repository/model naming mirrors 1:1 across the three domains, docstrings explain *why* not just *what* (e.g. `job_analysis_agent.py:11-14`'s comment on the 5000-char truncation, `profile.py:57-66`'s comment on the blank-prompt-fabrication guard). This is a good sign for maintainability.

**Duplication**:
- The Gemini model name `"gemini-2.5-flash-lite"` is hardcoded identically in three separate files (`candidate_profile_agent.py:109`, `job_analysis_agent.py:57`, `resume_generation_agent.py:79`) with no shared constant — a model upgrade/rollback requires three coordinated edits.
- `resume_generation_agent.py:5,13` independently calls `load_dotenv()` and reads `os.getenv("GEMINI_API_KEY")` directly, bypassing the `Settings.gemini_api_key` field that already exists in `core/config.py:32` for this exact purpose — two parallel mechanisms for the same secret.

**Abstraction quality**: no LLM provider abstraction exists — each agent directly instantiates `genai.Client(...)` in its own `__init__`. Swapping providers (or adding a fallback provider) means touching three files individually. This directly conflicts with this project's own CLAUDE.md guidance ("avoid tight coupling to a specific AI provider... use a thin abstraction at the boundary").

**Type safety / configuration management smell**: `core/config.py` defines several settings that are **never actually wired up anywhere**: `rate_limit_default`/`rate_limit_generation` (lines 45-46), `cors_origins` (line 27, `main.py` hardcodes the origin list instead), and `debug` (line 11, never passed to `FastAPI(debug=...)`). This is dead configuration — it looks like these features exist (a reader would reasonably assume rate limiting and configurable CORS are implemented) but they're inert. This is a real code-quality issue independent of the missing-feature issue itself: config that isn't connected to behavior is actively misleading.

**Type safety inconsistency**: `GenerateResumeRequest` (`schemas/resume.py:6-8`) types both fields as `uuid.UUID` — Pydantic enforces this automatically. By contrast, `AnalyzeJobRequest.url` and all three profile-import URL fields (`linkedin_url`, `github_url`, `portfolio_url` — `profile.py:28-31`) are plain `str | None`, not `pydantic.HttpUrl`. This inconsistency isn't just cosmetic — it's the direct mechanism that makes the SSRF finding in §9 reachable.

**Error handling consistency**: two different error response shapes exist — the global handler's `{"error": {...}}` envelope (`app/main.py:61-74`) for unhandled exceptions, vs. FastAPI's default `{"detail": "..."}` for every explicit `HTTPException` (7 call sites across `profile.py`/`resume.py`). No shared error-response Pydantic model.

---

## 3. Reliability Review

| Failure mode | Current behavior | Recommended behavior |
|---|---|---|
| LLM call hangs | **Unbounded wait.** Verified against the installed `google-genai` SDK: no `HttpOptions.timeout` is passed anywhere (`candidate_profile_agent.py`, `job_analysis_agent.py`, `resume_generation_agent.py`), and the SDK's default when timeout is `None` is `max_allowed_time = float('inf')`. | Set an explicit per-call timeout (e.g. 30-60s) via `HttpOptions`, and return a clean 504/503 to the client on expiry. |
| LLM call fails transiently (429/500/503) | **No retry.** The SDK's default retry policy when none is configured is `stop_after_attempt(1)` with `reraise=True` — a single unretried attempt. The exception propagates to the generic 500 handler with no indication it was a provider failure. | Configure `HttpRetryOptions` with bounded exponential backoff (2-3 attempts) for retryable status codes only. |
| LLM returns malformed/truncated JSON | **Unhandled.** All three agents do a bare `json.loads(response.text)` (`candidate_profile_agent.py:117`, `job_analysis_agent.py:65`, `resume_generation_agent.py:87`) with no try/except — `JSONDecodeError` propagates to a generic 500. | Catch parse failures, log the raw response for diagnosis, return a typed "AI response invalid, please retry" error rather than a generic 500. |
| LLM returns well-formed-but-wrong-shaped JSON | **Unhandled and unvalidated.** The parsed dict is never validated against the Pydantic output schemas (`CandidateProfile`, `OptimizedResume`) before being used — `ProfileRepository.create_from_analysis` and the resume PDF renderer consume the raw dict directly via `.get(...)`/`**dict` unpacking. A wrong-typed field either silently persists bad data (JSONB is permissive) or throws deep inside the Jinja template renderer. | Validate via `.model_validate()` immediately after parsing, before any persistence or rendering — fail fast with a clear error instead of writing possibly-corrupt data. |
| DB connection drops mid-request | **Handled.** `pool_pre_ping=True` (`database/session.py`) transparently detects and replaces dead connections before use. | Already correct for a single-instance deployment. |
| Two requests analyze the same job posting concurrently | **Race condition.** `JobRepository.create_from_analysis` does check-then-insert (`get_by_hash` then unconditional insert) with no exception handling around the commit; the DB-level unique index on `posting_text_hash` will reject the second insert with an unhandled `IntegrityError` → generic 500, instead of gracefully returning the existing row. | Catch `IntegrityError` on the insert and re-fetch-and-return the existing row (upsert pattern), or use `INSERT ... ON CONFLICT DO NOTHING RETURNING`. |
| Resume PDF render succeeds, DB write fails | **Orphaned file.** `resume.py:54-67` writes the PDF to disk *before* the DB commit — a failure between those two steps leaves an unreferenced file with no cleanup mechanism. | Either write the DB row first (with a placeholder/pending PDF URL) and update it after render, or run a periodic orphan-file sweep. Low severity today (local disk), matters more once storage has a billing cost (S3). |
| GitHub/portfolio fetch fails (timeout, 404, bad JSON) | **Handled well.** Both fetchers use a documented "never raise" pattern — blanket `except (httpx.HTTPError, ValueError)` degrades to `(None, [])`/`None` so a flaky third-party site never blocks CV import (`github_profile_fetcher.py:42-44`, explicit and correct). | Already correct — good example of graceful degradation to follow for the LLM calls above. |
| Re-analyzing the same job posting | **Half-idempotent.** The DB write is deduplicated via the hash lookup, but `agent.analyze()` is called *before* that check (`jobs.py:18-19`) — so a duplicate request still burns a full LLM call every time even though no duplicate row results. | Move the hash check before the LLM call (hash the raw text up front, short-circuit if it already exists). |
| Calling resume generation twice for the same profile+job | **Not idempotent at all.** No lookup keyed on `(user_profile_id, job_id)` — every call creates a new `Resume` row and a new PDF file on disk with a fresh random filename; nothing is ever overwritten or cleaned up. | Add a lookup (or unique constraint) on `(user_profile_id, job_id)`, and either return the existing resume or explicitly version it, but stop silently duplicating LLM spend and storage. |

---

## 4. Edge Case Analysis

### User Input

| Case | Why it matters | Current behavior | Recommended behavior |
|---|---|---|---|
| Empty import request (no CV, no URLs) | Prevents wasted LLM calls on nothing | **Handled** — 400 before reaching the agent (`profile.py:49-50`) | Keep |
| All sources present but all empty/unusable after fetch | LLM fabricates a profile from a blank prompt despite "never invent" instructions (observed and documented by the team) | **Handled** — explicit 422 guard (`profile.py:57-66`) with an inline comment explaining the exact failure mode this guards against | Keep — this is a good pattern, worth applying elsewhere |
| Extremely large upload body | Memory exhaustion DoS | **Not handled** — `file.read()` buffers the entire body into memory *before* the 10MB check (`profile.py:40-42`); no ASGI-level body size cap exists | Enforce a body-size limit at the ASGI/reverse-proxy layer, or stream-read with an early abort once the cap is exceeded |
| Invalid/malformed portfolio URL | SSRF (see §9) | **Not handled** — no format validation, no scheme/host restriction | Type as `HttpUrl`, resolve+validate the host before fetching |
| Invalid GitHub URL | Should degrade gracefully | **Handled** — regex extraction fails gracefully to `None` (`github_profile_fetcher.py:10,13-16`) | Keep |
| Duplicate profile uploads (same user re-imports) | Unbounded storage growth | **Not handled** — every import inserts a new row, no dedup, no User FK to even key on yet (`models/profile.py:16`) | Deferred pending auth, but worth a cleanup/retention policy in the interim |
| Missing required fields | Bad requests should fail clearly | **Handled** for typed fields via Pydantic (e.g. `GenerateResumeRequest`'s UUID fields reject non-UUIDs with 422 automatically) | Keep, extend to URL fields |
| Unicode / special characters / unusual encodings | Scraped/uploaded text can contain anything | **Not verified by this review** — no explicit encoding handling or test coverage found for non-ASCII/malformed-encoding input anywhere in the ingestion pipeline | Add explicit tests with non-Latin scripts, emoji, and mixed encodings through the PDF/scrape/LLM pipeline |

### AI Integration

| Case | Why it matters | Current behavior | Recommended behavior |
|---|---|---|---|
| LLM timeout | Hung requests block the worker indefinitely | **Not handled** — verified unbounded wait (§3) | Explicit timeout + clean error |
| LLM rate-limited (429) | Should degrade, not crash | **Not handled** — no retry, propagates as generic 500 | Retry with backoff, then a clear "try again shortly" error |
| LLM returns invalid JSON | Should not corrupt data or crash unhelpfully | **Not handled** — unhandled `JSONDecodeError` → 500 | Catch, log, typed error |
| Hallucinated output (plausible but fabricated) | Product-integrity issue — a fabricated resume claim could actively harm the user in a real job application | **Partially handled** — real code-level guard only for the all-sources-empty case; beyond that, "never invent" is prompt-instruction-only with zero output-side verification | Add a lightweight post-hoc check: e.g. verify claimed skills/keywords appear (token-overlap) in the source text before including them in the final resume |
| Empty/partial LLM response | Same failure class as malformed JSON | **Not handled** — same unguarded `json.loads` path | Same fix as above |
| Model deprecation/change | Google can deprecate model versions | **Fragile** — model name hardcoded in 3 places with no fallback or version pinning strategy beyond the literal string | Centralize in one config constant; consider a fallback model on hard failure |
| Provider outage | Should degrade or queue, not fail every request hard | **Not handled** — no retry, no circuit breaker, no queued-retry path | At minimum, retry + clear user-facing "service temporarily unavailable" |

### File Processing

| Case | Why it matters | Current behavior | Recommended behavior |
|---|---|---|---|
| Password-protected PDF | Common real-world case | **Handled** — caught via `PdfReadError` hierarchy, returns 400 (`pdf_text_extractor.py:13-17`) | Keep |
| Scanned/image-only PDF (no extractable text) | Should degrade gracefully, not crash | **Handled** — returns empty string, falls through to the "no usable content" 422 if no other source exists | Consider a clearer user-facing message distinguishing "scanned, no OCR" from "empty file" (UX, Low priority) |
| Corrupted/malformed PDF bytes | Common with bad uploads/interrupted transfers | **Not handled** — `pypdf.errors.ParseError`/`DependencyError` and raw parser exceptions (`zlib.error`, `struct.error`, `KeyError`) are **not** subclasses of the `PdfReadError` this code catches; they propagate to the generic 500 handler instead of the intended 400 | Broaden the except clause to `pypdf.errors.PyPdfError` (the actual common base) or catch `Exception` narrowly around just the parse call |
| Extremely large PDF (many pages) | CPU-bound extraction blocks the async event loop for every other concurrent request | **Not handled** — no page-count/size limit; extraction runs synchronously inside an `async def` route with no thread-pool offload | Cap page count, and/or run extraction via `asyncio.to_thread` |
| DOCX / non-PDF resume formats | Users commonly have resumes in Word format | **Out of scope by design** — only PDF is supported at all; a `.docx` upload is rejected by the `_is_pdf` check | Acceptable scope limitation for now — just ensure the rejection message is clear (currently it is: `Message.PDF_ONLY` client-side) |
| Large LinkedIn paste (from the extension's "scrape open tab" feature) | Could be very large text blobs | **Not explicitly capped** — no size limit found on the `linkedin_text` form field | Add an explicit length cap, mirroring the job-posting 5000-char truncation pattern already used elsewhere |
| Invalid GitHub URL | — | **Handled**, see above | Keep |

### Database

| Case | Why it matters | Current behavior | Recommended behavior |
|---|---|---|---|
| Lost DB connection | Should recover, not hard-fail every subsequent request | **Handled** — `pool_pre_ping=True` | Keep |
| Race condition (duplicate job analysis) | Data integrity / clean error UX | **Partially handled** — DB-level unique constraint exists, but the race surfaces as an unhandled `IntegrityError` → 500 instead of a graceful return of the existing row | Catch and handle gracefully (§3) |
| Duplicate records (profile imports) | Unbounded growth | **Not handled** — by design, pending auth | See §1/§3 |
| Transaction failures (partial multi-step writes) | Data consistency | **Low current risk** — each route performs exactly one repository write today; the one exception is the PDF-write-then-DB-commit ordering in resume generation (§3) | Monitor as more multi-step flows are added |
| Migration failures | Schema evolution | **No migration tooling exists at all** — see §12, Critical | Adopt Alembic before any real deployment |
| Deadlocks | Concurrent writes to the same row | **Not observed as a current risk** — no code path does concurrent multi-row updates to the same entity today | Re-assess once background jobs/concurrent writers are introduced |

### API

| Case | Why it matters | Current behavior | Recommended behavior |
|---|---|---|---|
| Double/duplicate submission (user double-clicks "Optimize CV") | Wasted LLM spend, duplicate data | **Not handled** — resume generation is not idempotent (§3) | Add idempotency key or `(profile_id, job_id)` uniqueness |
| Concurrent requests | Event-loop blocking from sync PDF work serializes unrelated requests | **Partially handled** — async I/O is used correctly for DB/HTTP, but PDF extraction and PDF rendering are synchronous CPU-bound calls not offloaded to a thread pool | Offload via `asyncio.to_thread` (§10) |
| Invalid/no authentication | — | **N/A — no authentication exists on any endpoint at all.** This is the single largest gap in the entire review; see §9. | Add auth before any real launch |
| Payload size limits | Memory exhaustion | **Not handled**, see §4 User Input | ASGI-level cap |
| Slow clients | Could hold connections/workers open | **Not specifically analyzed** — no explicit slow-client protection (read timeouts) found at the ASGI server level | Configure server-level (uvicorn/reverse-proxy) request timeouts |

### Chrome Extension (backend-facing contract)

*(Light pass — extension internals were reviewed in depth in a prior session; this is specifically about what the backend does/doesn't do to protect against extension-originated failure modes.)*

| Case | Why it matters | Current behavior | Recommended behavior |
|---|---|---|---|
| Backend unavailable | Extension should degrade gracefully | **Handled on the extension side** — `background/api.js` catches network errors and returns `{ok:false, error}` rather than throwing; the backend itself is stateless per-request so has nothing special to do here | Keep |
| Extension retries a request automatically | Could cause duplicate LLM calls/rows if retried after a slow-but-successful request | **Not handled** — extension does not currently auto-retry (confirmed in prior session), and the backend has no idempotency protection if it did (§3) | If retry logic is ever added client-side, backend idempotency (§3) becomes mandatory, not optional |
| Duplicate job-page extraction (user re-clicks "Analyse this page") | Wasted LLM spend | **Partially handled** — DB dedup exists but LLM call still re-runs (§3) | Fix the check-before-LLM-call ordering |
| Invalid/garbage extracted page content | Should not corrupt data or crash | **Handled** — length-based truncation and the same "no usable content" guard pattern applies | Keep |

---

## 5. API Review

### Route inventory

| Method | Path | Response model | File |
|---|---|---|---|
| POST | `/v1/jobs/analyze` | `JobResponse` | `jobs.py:13` |
| POST | `/v1/profile/import` | `ProfileImportResponse` | `profile.py:25` |
| POST | `/v1/resumes/generate` | `ResumeGenerationResponse` | `resume.py:32` |
| GET | `/v1/resumes/{resume_id}/download` | `FileResponse` | `resume.py:78` |
| GET | `/health` | plain dict | `app/main.py:87` |

No list/`GET` endpoints exist for jobs or profiles — reasonable for now, but also means there's no way to enumerate or clean up the unbounded profile rows noted in §3/§4.

**Status codes**: mostly correct and intentional (all explicit errors are 4xx, no accidental 5xx). Specific inconsistencies:
- Oversized upload returns `400` (`profile.py:42`) where `413 Payload Too Large` is the more precise status.
- "Couldn't extract usable content" returns `422` (`profile.py:63`) alongside three separate `400`s for conceptually similar "bad input" cases in the same file (lines 38, 42, 50) — inconsistent convention.
- Resume download's `404` (`resume.py:85`) conflates "resume id doesn't exist" with "resume exists but its PDF file is missing from disk" — the latter is a server-side data-integrity issue, arguably a 500.

**Request validation**: `GenerateResumeRequest` is strongly typed (UUIDs, auto-rejected by Pydantic). By contrast, all URL-shaped fields across the API (`AnalyzeJobRequest.url`, and all three profile-import URL form fields) are untyped strings with no format validation — this is both a validation gap (§6) and the direct enabler of the SSRF finding (§9).

**Response consistency**: two incompatible error shapes exposed to clients — see §2/§7.

**Idempotency**: neither job analysis (partially) nor resume generation (fully) is idempotent in terms of LLM cost, even though job analysis *is* idempotent in terms of DB rows. See §3 for detail.

**Versioning**: `/v1/` prefix only, applied centrally and consistently (`app/main.py:81`). Adequate for current maturity; no forward-looking strategy exists but none is urgently needed yet.

**CORS**: `app/main.py:37-43` — hardcoded to `http://localhost:3000`, not `*`, with `allow_credentials=True`. Properly scoped for dev, but two issues: (1) it's hardcoded rather than driven by the already-defined-but-unused `settings.cors_origins`, meaning a production origin change requires a code edit; (2) the actual client is a **browser extension**, not a `localhost:3000` web app — worth confirming this CORS config is even the relevant control for the real deployment (extension background-script fetches aren't subject to CORS the same way page-script fetches are), since the current config appears to target a different client than what's actually shipping.

---

## 6. Validation Review

| Layer | Assessment |
|---|---|
| Request validation (Pydantic) | Strong where used (`GenerateResumeRequest`, `AnalyzeJobRequest.raw_text` with `min_length=1`). Weak/absent on all URL fields (plain `str`, no `HttpUrl`) — see §2, §5, §9. |
| DTO validation | The bigger gap is **response-side**: LLM output dicts are never validated against their own Pydantic schemas (`CandidateProfile`, `OptimizedResume`) before being persisted or rendered (§3). The schemas exist and are well-designed; they're just not actually enforced at the point that matters. |
| Domain validation | The "never invent" / hallucination guards are prompt-level only, with one solid code-level backstop (all-sources-empty case) and no others (§3, §4). |
| Database constraints | `Job.posting_text_hash` has a real DB-level unique index (`models/job.py:36`) — good. `UserProfile` has no constraints at all beyond the primary key — no dedup key exists because there's no user identity to key on yet. |
| File validation | `_is_pdf` (`profile.py:21-22`) checks `Content-Type` OR filename suffix — no magic-byte (`%PDF-`) check. Practical impact is limited because `pypdf` itself will reject non-PDF content downstream (see §4's corrupted-PDF gap for what happens when that rejection isn't caught cleanly). |
| URL validation | Effectively absent across the board — this is the single most consequential validation gap in the codebase given its downstream security impact (§9). |

**Recommendation, ranked**: (1) validate LLmvsoutput against Pydantic schemas before persistence — cheap, high-value, prevents corrupt data at the source; (2) type all URL fields as `HttpUrl` and add host/scheme restrictions before any fetch; (3) add PDF magic-byte sniffing as defense-in-depth.

---

## 7. Error Handling

**What exists**:
- A global unhandled-exception handler (`app/main.py:61-74`) returns a sanitized envelope — no stack traces or raw exception messages leak to the client for genuinely unhandled errors. This is good practice and already matches a documented section of the project's own TDD.
- A request-ID middleware (`app/main.py:49-55`) generates a UUID per request, attaches it to `request.state`, returns it via `X-Request-ID`, and includes it in the error envelope — a solid foundation for correlation.

**What's missing or inconsistent**:
- **The request ID currently correlates against nothing** — because there is no logging anywhere (§8), a client-reported request ID has no server-side log line to look up. The correlation mechanism is built but the other half (logging) doesn't exist.
- Explicit `HTTPException(detail=...)` responses use a different shape (`{"detail": "..."}`) than the global handler's `{"error": {...}}` envelope — a client has to branch on which shape it received.
- A few explicit 400s leak raw internal exception text to the client (e.g. `profile.py:47`'s `detail=str(exc)` surfaces the raw `pypdf` parser error message) — low severity (parser internals, not secrets) but inconsistent with the sanitization discipline used for the 500 path.
- **Retryable vs non-retryable is not distinguished anywhere.** An LLM 429 (retryable) and a malformed-PDF 400 (not retryable) both currently surface to the client with no signal about whether retrying would help.

**Recommendations**: unify on one error envelope shape for both `HTTPException` and unhandled-exception paths (a custom exception handler for `HTTPException` that reuses the same envelope is a small, high-value fix); add logging so request IDs are actually useful; add a `retryable: bool` field to the error envelope for programmatic client handling.

---

## 8. Logging & Observability

**Logging: the single largest observability gap.** A repo-wide search for `import logging`, `logger.`, `logging.getLogger`, or `print(` across all non-test files in `backend/` returns **zero matches**. There is no logging anywhere in the route, service, or repository layers. Concretely: if an LLM call times out, a DB write fails, or a JSON parse error occurs, **nothing is written anywhere** before the exception reaches the generic 500 handler. From an operations standpoint, every failure mode described in §3 and §4 is currently invisible except as a client-facing 500 — there is no way to know *why* something failed without reproducing it live.

**What exists**: the request-ID middleware (§7) — a good foundation with nothing plugged into it yet.

**What's missing**:
- No structured logging library (no `structlog`, no configured `logging` handlers/formatters).
- No metrics (no Prometheus/StatsD/OpenTelemetry — confirmed via repo-wide search).
- No distributed tracing.
- `/health` (`app/main.py:87-89`) is a static `{"status": "ok"}` with no DB connectivity check — an orchestrator relying on this to route traffic or restart unhealthy instances would never detect a DB outage via this endpoint.

**What should be logged** (once logging exists): every LLM call (provider, model, latency, success/failure, token usage if available) — *never* log full prompt/response content containing candidate PII by default, only metadata, unless a debug flag is explicitly enabled in a non-production environment; every DB write failure; every external HTTP fetch failure (GitHub/portfolio) with the target host (not full response body); request start/end with method/path/status/duration, tagged with the request ID already being generated.

**What should never be logged**: raw resume/CV text, raw LLM prompts/responses containing candidate PII, the Gemini API key, any DB connection string with embedded credentials.

**Recommendation priority**: this is cheap to add (a `logging.getLogger(__name__)` + a handful of `logger.exception(...)` calls at the points already identified as unhandled in §3) and has an outsized impact on the ability to operate this service at all — treat as near-Critical alongside the reliability fixes it would make diagnosable.

---

## 9. Security Review

*(Full review conducted; cross-verified independently by two separate research passes, which converged on the same two Critical findings.)*

### 9.1 Authentication & Authorization — **Critical**
Zero auth exists anywhere — no middleware, no `Depends()` auth check, on any of the four endpoints. `UserProfile`, `Job`, and `Resume` have no owner field at all (`models/profile.py:16,30` explicitly documents this as a known gap pending future auth work). UUID identifiers are **not** a substitute for authorization here: `GET /v1/resumes/{resume_id}/download` (`resume.py:78-91`) returns a candidate's full PDF resume (name, contact info, full work history — real PII) to anyone who has or can obtain the `resume_id`, which is routinely exposed in the `/generate` response body, browser history, and proxy/access logs. **Concrete exploit**: anyone who can reach the API — no browser/CORS involvement required, since CORS only constrains browser-JS callers, not `curl`/server-to-server calls — can generate resumes against arbitrary `job_id`/`user_profile_id` pairs and download any resume whose ID they've observed or guessed. **This is the highest-priority finding in the entire review.**

### 9.2 SSRF — **Critical**, confirmed independently by two research passes
`portfolio_scraper.py:19-21` takes a client-supplied `portfolio_url` (typed as a plain `str`, no format/scheme/host validation anywhere upstream — `profile.py:31`) and fetches it directly via `httpx` with `follow_redirects=True` and no private-IP/localhost/cloud-metadata-address blocking. **Concrete exploit**: `portfolio_url=http://169.254.169.254/latest/meta-data/iam/security-credentials/<role>` (AWS) or the GCP metadata equivalent is fetched server-side, and the extracted text is both persisted to the profile *and* echoed back to the client in the import response (`profile.py:87-91`) — a full SSRF read-and-exfiltrate primitive, capable of leaking cloud IAM credentials if the backend runs with an attached role, plus access to any internal-network service (admin panels, unauthenticated internal services). `follow_redirects=True` means even a naive "check the initial URL's host" mitigation would be insufficient without also validating the post-redirect destination. The GitHub fetcher, by contrast, is **not** vulnerable — it only ever regex-extracts a username and always calls a hardcoded trusted host.

### 9.3 Rate Limiting — **High**
`rate_limit_default`/`rate_limit_generation` are defined in config (`core/config.py:45-46`) but never wired into any middleware — confirmed dead code. Combined with §9.1 (no auth), this means unbounded, unauthenticated calls to `/v1/resumes/generate` and `/v1/profile/import` are possible — each is a real-money LLM invocation, and the latter also triggers the SSRF-capable fetch in §9.2. This is a direct, low-effort financial-DoS vector, not just a hygiene issue.

### 9.4 File Upload Security — Medium
No magic-byte (`%PDF-`) validation — only `Content-Type`/filename-suffix checks (`profile.py:21-22`), trivially spoofable. Practical impact is limited because the raw file is never persisted (only extracted text is), and `pypdf` will reject genuinely non-PDF content downstream — though see §4 for the gap in *how* that rejection is currently handled for corrupted (as opposed to non-PDF) files.

### 9.5 Template/Output Injection — Mitigated
Jinja2 autoescaping is explicitly enabled (`resume_renderer.py:8`, `autoescape=True`) and no `|safe` filter is used anywhere in `templates/resume.html` — LLM-generated content (which is influenceable by attacker-controlled job postings via prompt injection, §9.7) is HTML-escaped before reaching the PDF renderer. This closes off the most direct injection vector. Residual, unconfirmed risk: `xhtml2pdf` (the underlying PDF engine) has a history of CSS/`@font-face`/local-file-inclusion CVEs in some versions — worth an explicit version check (see §9.8, no lockfile currently exists to check against).

### 9.6 Path Traversal — Mitigated
`LocalResumeStorage.save`'s filename is always server-generated (`f"{uuid.uuid4().hex}.pdf"`, `resume.py:56`) — no user input ever reaches the storage path. Not exploitable today; flagged only as a "no defense-in-depth if this ever changes" note.

### 9.7 Prompt Injection — Real, bounded blast radius (Low-Medium)
Scraped job postings, resume text, and portfolio/GitHub text all flow unsanitized into LLM prompts. A crafted job posting could plausibly manipulate the model's output (e.g. inflate an ATS score or insert misleading `changes_summary` text). Assessed impact is bounded because agent output only ever flows into typed JSONB columns (via parameterized ORM writes — confirmed no raw SQL anywhere in the codebase) and an autoescaped PDF template — there is no path from LLM output to shell commands, file paths, SQL, or another user's data. Worst case is self-directed: a user who pastes a malicious job posting can corrupt the quality of *their own* generated resume, not compromise the system or other users.

### 9.8 Dependency Vulnerabilities — Medium (process gap)
No lockfile exists anywhere in the repository — the only `pyproject.toml` in the repo contains solely `[tool.pytest.ini_options]`, no dependency list at all. This means builds are not reproducible and there is currently no artifact for `pip-audit`/Dependabot/Snyk to scan. This is itself the finding: fix the lockfile gap (§12) as a prerequisite to any real dependency-vulnerability process.

### 9.9 Secrets Management — Good, one dead landmine
No hardcoded secrets found; `.env` is correctly git-ignored and confirmed never committed. One latent risk: `core/config.py:21` ships a hardcoded fallback `jwt_secret_key: str = "change-me-in-production"`. JWT is entirely unused today, so this is currently inert — but if auth is added later (as it must be, per §9.1) and this default is ever left unoverridden in a real deployment, tokens become forgeable. Flag for removal or a startup assertion once auth lands.

### 9.10 Sensitive Data Exposure in Errors — Mitigated, one minor gap
The global exception handler is properly sanitized (no stack traces to clients). One inconsistency: a few explicit 400s leak raw parser exception text (§7) — low severity but worth normalizing.

**Security priority ranking**: (1) Auth + resource ownership — Critical, blocks any real launch. (2) SSRF allowlist/private-IP blocking in `portfolio_scraper.py` — Critical, independently exploitable today. (3) Rate limiting — High. (4) PDF magic-byte validation — Medium. (5) Dependency lockfile + scan — Medium.

---

## 10. Performance Review

**Confirmed bottlenecks**:
- `render_pdf()` (`resume_renderer.py`, using `xhtml2pdf`) is a synchronous, CPU-bound call invoked directly inside an `async def` route (`resume.py:54`) with no `asyncio.to_thread` offload — blocks the event loop for the full render duration on every resume generation, serializing unrelated concurrent requests on a single-worker deployment.
- PDF text extraction (`pdf_text_extractor.py`) has the identical problem — synchronous, CPU-bound, called directly inside `async def import_profile` (`profile.py:26`) with no thread-pool offload, and no page-count cap, making it both a performance bottleneck and (per §4) a DoS vector on large uploads.
- A fresh `genai.Client` is instantiated per agent per request rather than reused — minor overhead, not correctness-affecting.

**What's already handled well**:
- GitHub and portfolio fetches are correctly parallelized via `asyncio.gather` (`profile.py:52-55`) before the single LLM call.
- The resume-generation pipeline (`match_keywords` → `rank_profile` → `_optimize` → `compute_ats`) is inherently serial by genuine data dependency, not a missed-parallelism opportunity — there's only one LLM call in the whole pipeline.
- `job_analysis_agent.py` deliberately caps input at 5000 chars specifically to bound LLM latency (documented inline) — a good, explicit tradeoff.
- Connection pooling is reasonably configured (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`).
- No N+1 query patterns are currently *triggered* (the one relationship that could cause one, `UserProfile.resume_versions`, is never actually accessed by any reviewed code path) — but see §14 Technical Debt, this is a landmine for whoever adds the first "show resume history" feature.

**Recommendations, in order of impact**: (1) offload PDF extraction and PDF rendering via `asyncio.to_thread` — directly fixes both a performance bottleneck and a DoS vector; (2) add explicit LLM call timeouts (§3) — currently the single largest latency risk since it's unbounded; (3) reuse LLM clients across requests rather than instantiating per-call.

---

## 11. Scalability Review

**Statelessness**: the API layer itself is stateless (no in-memory session state, no sticky-session requirements) — good foundation for horizontal scaling once other blockers are resolved.

**The actual scaling blockers**:
- **No background job infrastructure.** LLM calls and PDF rendering happen synchronously in the request/response cycle. `settings.redis_url` is already defined in config but completely unused — strong evidence this was planned and never implemented. Before real load, resume generation (the slowest, most expensive operation) needs to move to a queue (Celery/RQ/arq against the already-provisioned Redis) with the client polling or receiving a webhook/websocket update, rather than holding an HTTP connection open for the full LLM-call-plus-PDF-render duration.
- **Single-instance-only today.** No containerization exists (§12) — there's no way to horizontally scale what hasn't been packaged for deployment yet.
- **JSONB-heavy schema.** Reasonable for the current phase (no cross-record query requirements exist yet), but none of the JSONB columns have GIN indexes, and there's no normalized schema to fall back on. This becomes a real bottleneck the moment any "search across candidates" or "find similar jobs" feature is needed — budget for a normalization migration before that feature, not after.
- **Unbounded per-request LLM cost with no queue and no rate limiting** (§9.3) — at any real traffic volume this is both a cost-control and an availability problem (a traffic spike directly becomes an LLM-provider rate-limit cascade with no backpressure anywhere in the system).
- **Local disk storage for generated PDFs** (`LocalResumeStorage`) — the abstraction (`services/storage/`) already supports swapping to S3/object storage, which is the right call for horizontal scaling (local disk doesn't survive across instances); this just needs the S3 implementation to actually be written when the time comes.

**Not a current blocker**: connection pool sizing (30 total connections is adequate for the current scale and easily tunable later); the domain model itself (three independent aggregates with no problematic coupling) will scale structurally fine.

---

## 12. Production Readiness

| Area | Status | Detail |
|---|---|---|
| Environment configuration | **Gap — High** | Every setting in `core/config.py` has a default, including `jwt_secret_key = "change-me-in-production"` and `gemini_api_key = ""` — the app starts successfully with **zero** environment configuration and fails silently later (first LLM call) rather than failing fast at startup. No `.env.example` exists documenting which vars are actually required. |
| Startup validation | **Missing** | No startup/lifespan check validates required config or DB connectivity before accepting traffic. |
| Health endpoint | **Weak** | Static `{"status": "ok"}`, no DB connectivity check, no readiness/liveness distinction (§8). |
| Graceful shutdown | **Partial** | `engine.dispose()` runs on lifespan exit, but no draining of in-flight requests — relevant given LLM calls can be slow; a shutdown mid-generation has no special handling. |
| Containerization | **Missing — Critical** | No `Dockerfile` exists anywhere in the repo. `docker-compose.yml` defines only the Postgres service — the backend itself is not containerized at all and is run locally via `uvicorn.run(..., reload=True)` (`app/main.py:93`), a dev-mode invocation not appropriate for any real deployment. |
| Dependency management | **Missing — Critical** | No `requirements.txt`, no lockfile, no `[project]`/`[tool.poetry]` block anywhere — the only `pyproject.toml` in the repo contains just pytest config. There is no reproducible way to install the exact backend dependency set; the local `.venv` reflects ad hoc `pip install` history not captured in source control. |
| Schema migrations | **Missing — Critical** | No Alembic (or equivalent) anywhere. Schema is created via `Base.metadata.create_all` on every startup, which is additive-only — it cannot apply a column rename, type change, or constraint change to an existing table. Fine for a disposable local Postgres; a hard blocker for any deployment with data worth keeping. |
| Secrets management | **Adequate for current stage** | `.env`-based, properly git-ignored, no committed secrets found — will need a real secrets manager (not `.env` files) once this runs anywhere beyond a single developer's machine. |
| Backup / disaster recovery | **None** | Postgres data lives in a local Docker named volume with no backup job, no WAL archiving, no managed-DB usage evident — entirely dev-oriented today. |
| CORS | **Dev-only config** | Hardcoded to `localhost:3000`, not environment-driven despite `cors_origins` already existing in config (§2) — will need to change before any non-local deployment, and its relevance to the actual browser-extension client should be re-verified (§5). |

**Bottom line**: this backend is not production-deployable as-is — not because the logic is wrong, but because none of the deployment scaffolding (container, lockfile, migrations, fail-fast config, real health checks) exists yet. All four Critical items in this section are foundational and should be sequenced before feature work, not after.

---

## 13. Testing Strategy

**What's genuinely well-tested**:
- All three LLM agents have unit tests with the `genai` client fully mocked (`test_resume_generation_agent.py`, `test_candidate_profile_agent.py`, `test_job_analysis_agent.py`) — no real API calls, no CI flakiness/cost risk from these.
- The GitHub and portfolio fetchers have genuinely good failure-path coverage: HTTP errors, network errors, malformed JSON, non-200 responses, connection errors are all explicitly tested (`test_github_profile_fetcher.py`, `test_portfolio_scraper.py`).
- `test_pdf_text_extractor.py` explicitly tests a corrupted PDF case.
- Deterministic scoring modules (`ats_scorer`, `keyword_matcher`, `relevance_ranker`) have focused unit tests.

**Critical gaps**:
- **No test file exists for `resume.py` or `jobs.py` at all.** The single most important product flow — resume generation (DB lookups → LLM call → PDF render → file write → DB write) — has zero test coverage of any kind.
- **No repository-layer tests exist against any database, real or fake.** `backend/tests/conftest.py` only does a `sys.path` insert — there is no DB fixture, no test database, no SQLite-for-tests setup, no testcontainers. Nothing in the test suite has ever executed a real SQLAlchemy query. This means the persistence-layer findings in this review (transaction ordering, the dedup race condition, the missing eager-loading) are entirely unverified by any automated test.
- The **only** API-level test in the repo (`test_profile_import.py`) mounts an ad-hoc `FastAPI()` instance with `app.dependency_overrides[get_db] = lambda: None` and covers exactly one guard clause (the empty-content 422) — it does not exercise the real app, a real DB, or the success path.
- **No test simulates any LLM failure mode** (timeout, malformed JSON, rate limit) for any agent — every mocked test supplies a well-formed success response, so the entire unhandled-exception surface identified in §3 is genuinely untested, not just under-observed.

**Also missing**: concurrency/race-condition tests, DB-connection-loss tests, load/performance tests (acceptable to defer, but worth naming explicitly).

**Recommended sequencing**: (1) a DB test fixture (SQLite-in-memory or a disposable test-Postgres via testcontainers) — this unblocks everything else; (2) repository-layer tests against real DB semantics, specifically covering the dedup race and transaction-ordering findings above; (3) full API-level tests for `/v1/resumes/generate` and `/v1/jobs/analyze` against the real `app`, not an ad-hoc router mount; (4) explicit LLM-failure-mode tests (timeout, malformed JSON, rate-limit) for all three agents.

---

## 14. Technical Debt

| Item | Impact if left unaddressed |
|---|---|
| Config fields defined but never wired up (`rate_limit_*`, `cors_origins`, `debug`) | Actively misleading — a reader reasonably assumes these features exist. Will cause confusion/wasted debugging time for the next engineer, and is exactly the kind of "looks handled but isn't" gap that causes production incidents. |
| `settings.redis_url` defined, completely unused | Signals an abandoned or deferred plan (background jobs); either commit to building it or remove the config to stop implying it's in use. |
| Gemini model name hardcoded in 3 files | A model upgrade/rollback requires 3 coordinated edits with no compiler check they stay in sync — easy to end up with mismatched models across agents undetected. |
| Redundant secret-loading (agents bypass `Settings.gemini_api_key` via direct `os.getenv`) | Two sources of truth for the same secret; if `Settings` ever becomes the enforcement point (e.g. startup validation), these three agents silently won't benefit. |
| `services/` flat folder mixing agents/scrapers/extractors/scorers/renderers | Will get noisy as more are added; the precedent for subfolders (`repository/`, `storage/`) already exists and isn't applied consistently. |
| Router prefix inconsistency (`/jobs`, `/resumes` plural vs `/profile` singular) | Cosmetic but permanent once external consumers depend on it — cheap to fix now, essentially impossible to fix later without a breaking API change. |
| `UserProfile.resume_versions` / `Job.resume_versions` relationships with no eager-loading strategy, never exercised by any current code path | Landmine: the first feature that actually accesses `.resume_versions` on an async ORM object outside an active session context will hit a `MissingGreenlet` error, not a silent N+1 — will look like a mysterious bug to whoever adds that feature without knowing this context. |
| Orphaned PDF files possible if DB commit fails after file write | Currently harmless (local disk, low volume); becomes a real cost/cleanup problem once storage moves to S3 with per-GB billing. |
| `jwt_secret_key` hardcoded default (`"change-me-in-production"`) | Currently inert (no JWT usage), but a real vulnerability the moment auth is added if the default isn't overridden — should have a startup assertion the day auth lands, not be forgotten. |
| No dependency lockfile | Every environment (dev machines, any future CI, any future deployment) may be running subtly different dependency versions with no way to detect drift or audit for known CVEs. |

---

## 15. Prioritized Improvement Roadmap

### Critical — must be completed before any production deployment

| # | Recommendation | Reasoning | Expected impact | Effort | Business risk if unresolved |
|---|---|---|---|---|---|
| C1 | Add authentication + resource ownership checks on all endpoints | No auth exists at all today; any caller can read any candidate's generated resume (PII) via a guessed/observed UUID | Closes the single largest exposure in the system | Large (needs a User model, auth middleware, ownership checks retrofitted onto 3 tables + 4 routes) | Data breach of candidate PII; regulatory/reputational exposure |
| C2 | Add SSRF protection to `portfolio_scraper.py` (host/scheme allowlist, private-IP/metadata-address blocking, re-validated post-redirect) | Confirmed exploitable today — a crafted portfolio URL can reach cloud metadata endpoints or internal services and exfiltrate the response | Closes a live, unauthenticated exploit path | Small–Medium | Cloud credential theft if deployed with an attached IAM role; internal network reconnaissance |
| C3 | Add Alembic (or equivalent) migrations; stop relying on `create_all` | Any schema change beyond adding a new table currently requires manual DDL or data loss | Makes schema evolution safe once real data exists | Medium | Data loss or manual, error-prone schema surgery on first real schema change |
| C4 | Add structured logging across route/service/repository layers | Currently zero visibility into any failure — the request-ID correlation mechanism already built has nothing to correlate against | Every other reliability fix becomes debuggable in production, not just in theory | Small–Medium | Undiagnosable production incidents; MTTR effectively unbounded |
| C5 | Containerize the backend (Dockerfile) and add it to `docker-compose.yml` | Backend is not packaged for deployment at all today; `docker-compose.yml` only runs Postgres | Prerequisite for any real deployment or horizontal scaling | Small–Medium | Cannot deploy this service to any real environment as-is |
| C6 | Add a dependency lockfile (`requirements.txt`/`poetry.lock`/`uv.lock`) with pinned versions | No reproducible builds exist; nothing can be vulnerability-scanned without a manifest | Reproducible deployments, enables dependency security scanning | Small | Untraceable "works on my machine" drift; no way to audit for known CVEs |
| C7 | Add explicit LLM call timeouts and bounded retries | Verified unbounded wait + zero retries against the actual SDK defaults — a hung or transiently-failing LLM call currently hangs or hard-fails every time | Bounds worst-case latency, converts transient failures into automatic recoveries | Small | Hung requests exhaust worker capacity; every transient provider blip becomes a user-facing outage |
| C8 | Validate LLM output against Pydantic schemas before persistence/rendering; catch and handle JSON parse failures | Malformed/wrong-shaped LLM output currently either corrupts stored data silently or crashes deep in the PDF renderer with a generic 500 | Prevents corrupt data at the source; converts crashes into clean, typed errors | Small–Medium | Silent data corruption compounding over time; confusing crash reports with no root cause |
| C9 | Add API-level and repository-level test coverage for `resume.py`/`jobs.py` and the persistence layer, including at least one DB fixture | The core product flow (resume generation) and the entire persistence layer are completely untested today — several of this review's own findings (the dedup race, transaction ordering) are unverified by any test | Makes the Critical/High fixes above actually verifiable and prevents regression | Medium | Every future change to the core flow ships with no safety net |

### High Priority — should be completed before public launch

| # | Recommendation | Reasoning | Expected impact | Effort | Business risk if unresolved |
|---|---|---|---|---|---|
| H1 | Wire up rate limiting (the config already exists, just unused) | No auth + no rate limiting = unbounded unauthenticated LLM-cost and SSRF-fetch abuse | Direct cost/abuse control | Small | Unbounded financial exposure from scripted abuse |
| H2 | Fix upload handling to check size before/while reading, not after buffering the full body | Confirmed memory-exhaustion path — the stated 10MB cap doesn't currently bound memory usage | Closes an easy unauthenticated DoS vector | Small | Service crash/OOM from a single oversized upload |
| H3 | Broaden the PDF-parsing except clause to catch the actual common exception base (`PyPdfError`), not just `PdfReadError` | Corrupted (not just malformed) PDFs currently surface as generic 500s instead of the intended 400 | Correct status codes, better client UX, cleaner logs once logging exists | Small | Misleading error signals; corrupted uploads look like server bugs |
| H4 | Offload PDF extraction and PDF rendering to a thread pool (`asyncio.to_thread`) | Both currently block the event loop synchronously inside async routes — a performance issue and a DoS vector simultaneously | Restores concurrency under load | Small–Medium | A single large-PDF request degrades every other concurrent request |
| H5 | Make required config fail fast at startup instead of defaulting silently | Every setting (including the LLM API key and the JWT secret placeholder) has a default today — a missing `.env` fails silently until first use | Catches misconfiguration at deploy time, not first-request time | Small | Silent misconfiguration reaches production and fails unpredictably later |

### Medium Priority — improves maintainability and reliability

| # | Recommendation | Reasoning | Effort |
|---|---|---|---|
| M1 | Fix job-analysis idempotency to skip the LLM call (not just the DB write) on a hash hit | Currently burns a full LLM call on every re-analysis of an already-seen posting | Small |
| M2 | Add idempotency to resume generation (unique/lookup on `(profile_id, job_id)`) | Duplicate requests currently create duplicate rows, PDFs, and LLM spend | Small–Medium |
| M3 | Unify error response shape across `HTTPException` and the global handler | Two incompatible error shapes currently reach clients depending on failure type | Small |
| M4 | Add PDF magic-byte validation | Defense-in-depth on top of the existing (weak) content-type/extension check | Small |
| M5 | Type all URL-shaped fields as `HttpUrl` across the API | Closes the validation gap that directly enables the SSRF finding | Small |
| M6 | Centralize the LLM model name in one shared constant | Currently duplicated identically in 3 files with no compile-time consistency check | Small |
| M7 | Make CORS origins environment-driven (the config field already exists) | Currently hardcoded to `localhost:3000`; blocks any non-local deployment as-is | Small |
| M8 | Add a DB-connectivity check to `/health` | Current health check is static and would report healthy during a DB outage | Small |
| M9 | Reconsider profile-import dedup/retention once auth exists | Every import currently creates a permanent, unbounded new row | Medium (depends on auth landing first) |

### Low Priority — future enhancements

| # | Recommendation | Reasoning |
|---|---|---|
| L1 | Normalize router prefixes (`/jobs`, `/resumes`, `/profile` → consistent pluralization) | Cosmetic, but cheap now and a breaking change later |
| L2 | Reorganize `services/` into subfolders by responsibility (agents/scrapers/scoring/rendering) | Will matter more as more services accumulate |
| L3 | Remove the redundant `os.getenv` secret-loading path in `resume_generation_agent.py`; use `Settings.gemini_api_key` everywhere | Two sources of truth for the same secret today |
| L4 | Add a startup assertion that `jwt_secret_key` isn't the default placeholder, once auth is implemented | Currently inert but a landmine for later |
| L5 | Add eager-loading (or a dedicated query) for `resume_versions` before any feature actually accesses it | Will otherwise surface as a confusing `MissingGreenlet` error to whoever builds that feature first |
| L6 | Reuse LLM/`genai.Client` instances across requests instead of instantiating per call | Minor efficiency gain, not correctness-affecting at current scale |
| L7 | Add an orphaned-file cleanup job for PDFs written but never DB-committed | Currently harmless on local disk; matters once storage has a billing cost |
