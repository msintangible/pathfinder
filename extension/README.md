# Pathfinder Chrome Extension

Manifest V3 extension — the sensing/actuation layer for Pathfinder (TDD Section 6).
Content scripts and the side panel never call the backend directly; all network
I/O is routed through the service worker (TDD 6.1).

## Structure

- **`manifest.json`** — MV3 manifest. Permissions: `storage`, `sidePanel`,
  `scripting`, `activeTab`. Host permission `http://localhost/*` (any local port).
- **`src/background/`** — service worker (ES module). `index.js` routes
  messages + owns badge state; `api.js` is the only layer that calls the backend
  (`/health`, `/v1/jobs/analyze`); `storage.js` wraps per-tab detection state.
  Backend URL is configurable via `chrome.storage.local` (`backendUrl`),
  default `http://localhost:8003`.
- **`src/content/`** — content scripts (plain scripts sharing global scope,
  loaded in order: `detect.js`, `scrape.js`, `index.js`). `detect.js` does
  job-page detection (Tier 1 URL + Tier 2 DOM heuristics, TDD 6.2); `scrape.js`
  extracts the posting (see below); `index.js` reports detection and answers
  `SCRAPE_PAGE`.
- **`src/sidepanel/`** — the UI. Shows the detection result + **URL**,
  **automatically** scrapes the page into JSON on open / tab switch / page load,
  and has an **Analyse job** action and a profile section. Backend connectivity
  with a configurable URL field.

No build step — this is plain JS and loads directly. (Migrates to React + Vite
in a later phase when the resume diff/review UI needs it.)

### Scraper (`src/content/scrape.js`)

Structured-first extraction, in priority order:

1. **JSON-LD `schema.org/JobPosting`** — authoritative, noise-free. Yields the
   `structured` fields (title, company, location, salary, employment type,
   dates) and a clean description used as the body `text`.
2. **Readable content** — when JSON-LD is missing/thin, the best content
   container is chosen by a readability-style score (text density vs link
   density + class/id hints), then its visible text is extracted via a live-DOM
   `TreeWalker` that skips hidden + noise nodes and preserves block line breaks.
   It never clones or mutates the page.
3. **Body fallback** — for unrecognised pages.

Output shape:

```json
{
  "url": "https://…",
  "title": "…",
  "scrapedAt": "ISO-8601",
  "source": "json-ld | readable | body",
  "structured": {
    "title": "…", "company": "…", "location": "…",
    "employmentType": "…", "salary": "…", "datePosted": "…", "validThrough": "…"
  },
  "length": 1234,
  "truncated": false,
  "text": "…clean job description…"
}
```

`structured` is `null` when no structured data is found. `source` signals
extraction quality. Text is capped at 30,000 chars (word-boundary truncation).

### Tests

The scraper is covered by a jsdom test suite (test-only; does not affect how the
extension loads — it ships as plain JS):

```bash
cd extension
npm install   # one-time, installs jsdom (dev only; node_modules is gitignored)
npm test
```

Covers JSON-LD structured extraction, multi-posting selection, readable-content
noise/hidden removal, truncation, and the output contract.

## Load it in Chrome

1. Start the backend so the health check has something to hit:
   ```bash
   cd backend && uvicorn app.main:app --reload   # serves http://localhost:8000
   ```
2. Open `chrome://extensions`, enable **Developer mode** (top right).
3. Click **Load unpacked** and select this `extension/` directory.
4. Pin the Pathfinder icon, then click it to open the side panel.
5. Visit a job posting (e.g. a `*.greenhouse.io` or `jobs.lever.co` page) — the
   toolbar badge should read `JOB` and the side panel should show the detection
   signals and a green **Connected** backend status.

## Notes / deferred

- `content_scripts` currently matches `<all_urls>` so detection runs everywhere.
  TDD 6.9 calls for least-privilege optional host permissions per ATS domain;
  that refinement is deferred to a later phase.
- The backend URL is set in the side panel (stored in `chrome.storage.local`),
  default `http://localhost:8003`. `manifest.json` `host_permissions` covers any
  `http://localhost` / `http://127.0.0.1` port. For a remote/HTTPS backend later,
  add that origin to `host_permissions`.
