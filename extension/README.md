# Pathfinder Chrome Extension

Manifest V3 extension — the sensing/actuation layer for Pathfinder (TDD Section 6).
Content scripts and the side panel never call the backend directly; all network
I/O is routed through the service worker (TDD 6.1).

## Phase 2 (current) — auto-scrape page text

- **`manifest.json`** — MV3 manifest. Permissions: `storage`, `sidePanel`,
  `scripting`, `activeTab`. Host permission `http://localhost/*` (any local port).
- **`src/background.js`** — service worker. Message router, per-tab badge state,
  and the backend `/health` proxy. Backend URL is configurable via
  `chrome.storage.local` (`backendUrl`), default `http://localhost:8003`.
- **`src/content.js`** — job-page detection (Tier 1 URL + Tier 2 DOM heuristics,
  TDD 6.2) and `scrapePage()`, which collects all visible page text into a JSON
  object on request. Sensing only.
- **`src/sidepanel/`** — the UI. Shows the current page's detection result and
  **URL**, and **automatically** scrapes the page text into JSON and displays it
  (runs on open, on tab switch, and when a page finishes loading — no button).
  Also shows backend connectivity with a configurable URL field.

No build step — this is plain JS and loads directly. (Migrates to React + Vite
in a later phase when the resume diff/review UI needs it.)

### Scrape output shape

```json
{
  "url": "https://…",
  "title": "…",
  "scrapedAt": "ISO-8601",
  "length": 1234,
  "truncated": false,
  "text": "…all visible page text…"
}
```

Sending this to the backend for analysis is a later phase.

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
