# Pathfinder Chrome Extension

Manifest V3 extension — the sensing/actuation layer for Pathfinder (TDD Section 6).
Content scripts and the side panel never call the backend directly; all network
I/O is routed through the service worker (TDD 6.1).

## Phase 1 (current)

Skeleton + connectivity only:

- **`manifest.json`** — MV3 manifest. Permissions: `storage`, `sidePanel`,
  `scripting`, `activeTab`. Host permission scoped to the local backend.
- **`src/background.js`** — service worker. Message router, per-tab badge state,
  and the backend `/health` proxy.
- **`src/content.js`** — job-page detection (Tier 1 URL + Tier 2 DOM heuristics,
  TDD 6.2). Detection only; no extraction or autofill yet.
- **`src/sidepanel/`** — the review UI. Shows the current page's detection result
  and backend connectivity.

No build step — this is plain JS and loads directly. (Migrates to React + Vite
in a later phase when the resume diff/review UI needs it.)

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
- The backend base URL is hard-coded to `http://localhost:8000` in
  `src/background.js` and mirrored in `manifest.json` `host_permissions`. Both
  must change together when pointing at a deployed backend.
