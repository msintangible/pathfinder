/**
 * DOM tests for sidepanel/detection/index.js — the 3 job-page-ish redesign
 * screens (Known ATS, Unknown ATS, Keywords only) plus the legacy badge
 * fallback they layer on top of.
 *
 * Run with: npm test
 */
import { JSDOM } from "jsdom";
import { Message } from "../src/shared/constants.js";

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }
const tick = () => new Promise((r) => setTimeout(r, 0));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const DEFAULT_URL = "https://boards.greenhouse.io/acme/jobs/1";

const DEFAULT_SIGNALS = {
  urlMatch: false,
  jsonLd: false,
  applicationForm: false,
  jobKeywords: false,
  metaTags: false,
};

/** Fresh jsdom + chrome mock, imports index.js (module cache busted per call).
 *  `detection`/`jobAnalysis` are mutable via the returned `state` object, and
 *  the registered onUpdated callback is captured, so a test can change what
 *  the "page" looks like and then simulate a tab-update event exactly as
 *  Chrome would fire it, instead of only testing the initial mount. */
/** Tailoring-flow options (profileId/scrape/analyzeResponse/generateResponse)
 *  all have working defaults so a test that doesn't care about the tailoring
 *  flow can ignore them entirely; tests exercising handleTailor override
 *  just the piece they're checking. `calls` counts ANALYZE_JOB/GENERATE_RESUME
 *  invocations so a test can assert re-analysis was (or wasn't) skipped. */
async function mountController({
  hasTab = true,
  detection = null,
  jobAnalysis = null,
  profileId = "profile-1",
  scrape = { text: "some job posting text", url: DEFAULT_URL },
  analyzeResponse = { ok: true, data: { id: "job-fresh", title: "Backend Engineer", company: "Acme" } },
  generateResponse = { ok: true, data: { ats_score: 80, matched_keywords: [], missing_keywords: [], added_keywords: [], download_url: "/v1/resumes/x/download" } },
} = {}) {
  const state = { detection, jobAnalysis };
  const calls = { analyze: 0, generate: 0, savedResumeResults: [] };
  const dom = new JSDOM(
    `<!doctype html><html><body>
      <div id="idle-root" hidden></div>
      <div id="detection-screen-root" hidden></div>
      <div id="loading-screen-root" hidden></div>
      <div id="legacy-root">
        <div id="detection-root"></div>
      </div>
    </body></html>`,
    { url: "https://example.com" }
  );
  global.document = dom.window.document;
  let onUpdatedCallback = () => {};
  global.chrome = {
    tabs: {
      query: async () => (hasTab ? [{ id: 1 }] : []),
      onActivated: { addListener: () => {} },
      onUpdated: { addListener: (fn) => { onUpdatedCallback = fn; } },
      sendMessage: async (_tabId, msg) => (msg.type === "SCRAPE_PAGE" ? scrape : null),
    },
    runtime: {
      sendMessage: async (msg) => {
        if (msg.type === "GET_DETECTION") return { detection: state.detection };
        if (msg.type === "GET_JOB_ANALYSIS") return { jobAnalysis: state.jobAnalysis };
        if (msg.type === "ANALYZE_JOB") { calls.analyze++; return analyzeResponse; }
        if (msg.type === "SAVE_JOB_ANALYSIS") {
          state.jobAnalysis = { id: msg.payload.id, title: msg.payload.title, company: msg.payload.company, url: msg.payload.url };
          return { ok: true };
        }
        if (msg.type === "GENERATE_RESUME") { calls.generate++; return generateResponse; }
        if (msg.type === "SAVE_RESUME_RESULT") { calls.savedResumeResults.push(msg.payload.data); return { ok: true }; }
        return null;
      },
    },
    storage: {
      local: { get: async (key) => (key === "profileId" && profileId != null ? { profileId } : {}) },
    },
  };

  await import(`../src/sidepanel/detection/index.js?bust=${Math.random()}`);
  await tick();
  await tick();

  return {
    screenRoot: document.getElementById("detection-screen-root"),
    legacyRoot: document.getElementById("legacy-root"),
    idleRoot: document.getElementById("idle-root"),
    loadingRoot: document.getElementById("loading-screen-root"),
    state,
    calls,
    /** Simulate Chrome firing tabs.onUpdated, then wait for the async handler. */
    async fireTabUpdated(changeInfo) {
      onUpdatedCallback(1, changeInfo, { id: 1, active: true });
      await tick();
      await tick();
    },
  };
}

function knownAts(overrides = {}) {
  return {
    isJobPage: true,
    confidence: 0.9,
    atsName: "Greenhouse",
    url: DEFAULT_URL,
    signals: { ...DEFAULT_SIGNALS, urlMatch: true, jsonLd: true, applicationForm: true, jobKeywords: true, metaTags: true },
    ...overrides,
  };
}

function unknownAts(overrides = {}) {
  return {
    isJobPage: true,
    confidence: 0.45,
    atsName: null,
    url: DEFAULT_URL,
    signals: { ...DEFAULT_SIGNALS, applicationForm: true, jobKeywords: true },
    ...overrides,
  };
}

function keywordsOnly(overrides = {}) {
  return {
    isJobPage: false,
    confidence: 0.2,
    atsName: null,
    url: DEFAULT_URL,
    signals: { ...DEFAULT_SIGNALS },
    ...overrides,
  };
}

await test("known ATS: screen shown, meter/labels correct, fallback title (no analysis yet)", async () => {
  const { screenRoot, legacyRoot, idleRoot } = await mountController({ detection: knownAts() });
  assert(screenRoot.hidden === false, "detection screen shown");
  assert(legacyRoot.hidden === true, "legacy hidden");
  assert(idleRoot.hidden === true, "idle hidden");
  assert(screenRoot.textContent.includes("Strong match"), "meter label");
  assert(screenRoot.textContent.includes("Known application system"), "system label");
  assert(screenRoot.textContent.includes("Job listing detected"), "fallback title, no fabricated job title");
  assert(screenRoot.textContent.includes("Greenhouse"), "ATS name shown even without analysis");
  assert(screenRoot.querySelectorAll(".det-meter__bar--known-ats").length === 3, "3 bars filled");
});

await test("known ATS: matching job analysis populates real title/company", async () => {
  const { screenRoot } = await mountController({
    detection: knownAts(),
    jobAnalysis: { title: "Data Analyst", company: "Reperio Human Capital", url: DEFAULT_URL },
  });
  assert(screenRoot.textContent.includes("Data Analyst"), "real title shown");
  assert(screenRoot.textContent.includes("Reperio Human Capital · Greenhouse"), "company + ATS name joined");
});

await test("known ATS: stale job analysis (different URL) is ignored, not shown", async () => {
  const { screenRoot } = await mountController({
    detection: knownAts(),
    jobAnalysis: { title: "Stale Old Job", company: "Old Co", url: "https://example.com/some-other-page" },
  });
  assert(!screenRoot.textContent.includes("Stale Old Job"), "stale title must not leak through");
  assert(screenRoot.textContent.includes("Job listing detected"), "falls back to generic heading instead");
});

await test("known ATS: Tailor my resume is enabled and wired to the tailoring flow", async () => {
  const { screenRoot } = await mountController({ detection: knownAts() });
  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  assert(btn, "button present");
  assert(btn.disabled === false, "button is enabled now that the tailoring flow exists");
});

await test("known ATS: while the request is genuinely in flight, the loading screen owns the panel", async () => {
  // GENERATE_RESUME is held open on a manually-resolved promise here (rather
  // than the mock's normal instant response) specifically so this test can
  // observe the mid-flight state deterministically — an instantly-resolving
  // mock finishes the whole analyze→generate→save chain within one microtask
  // drain, before even a single macrotask tick, which made this state
  // unobservable with the default mocks.
  let resolveGenerate;
  const pendingGenerate = new Promise((res) => { resolveGenerate = res; });
  const freshJob = { id: "job-1", title: "Backend Engineer", company: "Acme", url: DEFAULT_URL };
  const { screenRoot, legacyRoot, loadingRoot } = await mountController({
    detection: knownAts(),
    jobAnalysis: freshJob,
    generateResponse: pendingGenerate,
  });

  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  btn.click();
  await wait(10); // let handleTailor run up to the still-pending GENERATE_RESUME call

  assert(screenRoot.hidden === true, "detection screen hidden once tailoring starts");
  assert(legacyRoot.hidden === true, "legacy stack not shown yet either — loading screen owns the panel");
  assert(loadingRoot.hidden === false, "loading screen shown");
  assert(loadingRoot.textContent.includes(Message.GENERATING), "shows the real generating state, not a blank panel");

  resolveGenerate({ ok: true, data: { ats_score: 90, matched_keywords: [], missing_keywords: [], added_keywords: [] } });
  await wait(10);

  assert(loadingRoot.hidden === true, "loading screen hidden once the real result actually lands");
  assert(legacyRoot.hidden === false, "legacy stack revealed only once the real result is in, not before");
});

await test("known ATS with fresh job analysis: Tailor skips re-analyzing, generates, and reveals the legacy result bridge", async () => {
  const freshJob = { id: "job-1", title: "Backend Engineer", company: "Acme", url: DEFAULT_URL };
  const { screenRoot, legacyRoot, loadingRoot, calls } = await mountController({
    detection: knownAts(),
    jobAnalysis: freshJob,
  });

  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  btn.click();
  await wait(20); // let the mocked GENERATE_RESUME promise chain settle

  assert(calls.analyze === 0, "job analysis already fresh — not re-run");
  assert(calls.generate === 1, "generate called exactly once");
  assert(calls.savedResumeResults.length === 1 && calls.savedResumeResults[0]?.ats_score === 80,
    "real result persisted via SAVE_RESUME_RESULT, same as optimize/index.js's own flow");
  assert(loadingRoot.hidden === true, "loading screen hidden after success");
  assert(legacyRoot.hidden === false, "legacy stack (bridge to the existing result panel) revealed on success");
});

await test("known ATS with stale job analysis (different URL): Tailor re-analyzes before generating", async () => {
  const staleJob = { id: "job-old", title: "Old Job", company: "OldCo", url: "https://example.com/different-page" };
  const { screenRoot, calls } = await mountController({ detection: knownAts(), jobAnalysis: staleJob });

  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  btn.click();
  await wait(20);

  assert(calls.analyze === 1, "stale analysis (wrong URL) triggers a fresh ANALYZE_JOB, not reuse of the stale id");
  assert(calls.generate === 1, "generate still runs once, against the freshly analyzed job");
});

await test("known ATS: a real generation failure shows plain-language copy, never the raw HTTP/JSON detail", async () => {
  // Regression test: background/api.js's generateResume() surfaces backend
  // failures as `res.error = "HTTP {status}: {raw response body}"` — a real
  // 500 looked like `HTTP 500: {"error":{"code":"INTERNAL_SERVER_ERROR",...}}`.
  // That must never reach the screen — docs/pathfinder-uiux-requirements.md's
  // Voice rule is explicit: "No raw error strings/JSON ever shown to users."
  const freshJob = { id: "job-1", title: "Backend Engineer", company: "Acme", url: DEFAULT_URL };
  const originalConsoleError = console.error;
  const loggedErrors = [];
  console.error = (...args) => loggedErrors.push(args.join(" "));

  const { screenRoot, legacyRoot, loadingRoot } = await mountController({
    detection: knownAts(),
    jobAnalysis: freshJob,
    generateResponse: { ok: false, error: 'HTTP 500: {"error":{"code":"INTERNAL_SERVER_ERROR","message":"An unexpected error occurred."}}' },
  });

  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  btn.click();
  await wait(20);
  console.error = originalConsoleError;

  assert(loadingRoot.hidden === false, "loading screen stays up to show the failure");
  assert(loadingRoot.textContent.includes(Message.GENERATE_FAILED), "reuses the existing failure copy");
  assert(loadingRoot.textContent.includes("Couldn't generate your resume. Try again."), "shows plain-language copy");
  assert(!loadingRoot.textContent.includes("HTTP 500"), "never shows the raw HTTP status");
  assert(!loadingRoot.textContent.includes("INTERNAL_SERVER_ERROR"), "never shows the raw JSON body");
  assert(loadingRoot.querySelector(".load-retry-btn") !== null, "a working retry is offered, not a dead end");
  assert(legacyRoot.hidden === true, "legacy stack not revealed on failure — nothing to bridge to yet");
  assert(loggedErrors.some((line) => line.includes("INTERNAL_SERVER_ERROR")), "real detail still logged for debugging, just never shown to the user");
});

await test("known ATS with stale job analysis: a real analyze failure also shows plain-language copy only", async () => {
  const staleJob = { id: "job-old", title: "Old Job", company: "OldCo", url: "https://example.com/different-page" };
  const originalConsoleError = console.error;
  console.error = () => {};

  const { screenRoot, legacyRoot, loadingRoot } = await mountController({
    detection: knownAts(),
    jobAnalysis: staleJob, // stale (different URL) -> forces analyzeCurrentTab to run
    analyzeResponse: { ok: false, error: "HTTP 502: <html>Bad Gateway</html>" },
  });

  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  btn.click();
  await wait(20);
  console.error = originalConsoleError;

  assert(loadingRoot.textContent.includes("Couldn't read this job posting. Try again."), "shows plain-language copy");
  assert(!loadingRoot.textContent.includes("HTTP 502"), "never shows the raw HTTP status");
  assert(!loadingRoot.textContent.includes("<html>"), "never shows raw response markup");
  assert(legacyRoot.hidden === true, "legacy stack not revealed on failure");
});

await test("unknown ATS: screen shown, 2 bars filled, missing-signals copy names what's absent", async () => {
  const { screenRoot, legacyRoot } = await mountController({ detection: unknownAts() });
  assert(screenRoot.hidden === false, "detection screen shown");
  assert(legacyRoot.hidden === true, "legacy hidden");
  assert(screenRoot.textContent.includes("Partial match"), "meter label");
  assert(screenRoot.textContent.includes("Unrecognised system"), "system label");
  assert(screenRoot.querySelectorAll(".det-meter__bar--unknown-ats").length === 2, "2 bars filled");
  assert(screenRoot.textContent.includes("Some details are missing"), "notice title");
  // signals: applicationForm true, jobKeywords true, jsonLd false, metaTags false
  assert(screenRoot.textContent.includes("structured job data"), "names missing jsonLd signal");
  assert(screenRoot.textContent.includes("job metadata"), "names missing metaTags signal");
  assert(!screenRoot.textContent.includes("an application form"), "present signals aren't listed as missing");
});

await test("unknown ATS: Tailor with what's here is enabled and wired to the tailoring flow", async () => {
  const { screenRoot } = await mountController({ detection: unknownAts() });
  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor with what's here");
  assert(btn, "button present");
  assert(btn.disabled === false, "button is enabled now that the tailoring flow exists");
});

await test("keywords only: screen shown, 1 bar filled, no keyword pills fabricated", async () => {
  const { screenRoot, legacyRoot } = await mountController({ detection: keywordsOnly() });
  assert(screenRoot.hidden === false, "detection screen shown");
  assert(legacyRoot.hidden === true, "legacy hidden");
  assert(screenRoot.textContent.includes("Low match"), "meter label");
  assert(screenRoot.textContent.includes("Not enough to tailor from"), "heading");
  assert(screenRoot.querySelectorAll(".det-meter__bar--keywords-only").length === 1, "1 bar filled");
  assert(!screenRoot.textContent.includes("KEYWORDS FOUND"), "no fabricated keyword pills section");
  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Copy keywords instead");
  assert(btn && btn.disabled === true, "Copy keywords instead present and disabled");
});

await test("zero confidence: detection screen stays hidden, idle/index.js's turn", async () => {
  const { screenRoot } = await mountController({
    detection: { isJobPage: false, confidence: 0, atsName: null, url: DEFAULT_URL, signals: { ...DEFAULT_SIGNALS } },
  });
  assert(screenRoot.hidden === true, "detection screen must not claim the zero-confidence state");
});

await test("no active tab: legacy shown, detection screen hidden", async () => {
  const { screenRoot, legacyRoot } = await mountController({ hasTab: false });
  assert(screenRoot.hidden === true, "detection screen hidden");
  assert(legacyRoot.hidden === false, "legacy shown");
});

await test("no detection data yet: legacy shown, detection screen hidden", async () => {
  const { screenRoot, legacyRoot } = await mountController({ detection: null });
  assert(screenRoot.hidden === true, "detection screen hidden");
  assert(legacyRoot.hidden === false, "legacy shown");
});

await test("View profile reveals the legacy stack and hides the detection screen", async () => {
  const { screenRoot, legacyRoot } = await mountController({ detection: knownAts() });
  assert(screenRoot.hidden === false, "detection screen shown before click");

  screenRoot.querySelector(".det-link").click();

  assert(screenRoot.hidden === true, "detection screen hidden after View profile");
  assert(legacyRoot.hidden === false, "legacy stack shown after View profile");
});

await test("SPA route change (url set, no status) re-evaluates, not just full page loads", async () => {
  // Regression: Chrome doesn't re-enter status "complete" for a client-side
  // History API navigation — only changeInfo.url is set. The old listener
  // condition (status === "complete") silently ignored this, so the panel
  // stayed on the previous page's state until the extension was manually
  // reloaded — the bug reported against this exact module.
  const { screenRoot, legacyRoot, state, fireTabUpdated } = await mountController({ detection: keywordsOnly() });
  assert(screenRoot.hidden === false, "keywords-only screen shown initially");

  // Simulate an SPA navigation to a known-ATS job page, the way detect.js's
  // watchRouteChanges would report it to the background script.
  state.detection = knownAts({ url: "https://boards.greenhouse.io/acme/jobs/2" });
  await fireTabUpdated({ url: "https://boards.greenhouse.io/acme/jobs/2" }); // no status field — SPA nav shape

  assert(screenRoot.hidden === false, "detection screen still shown, now for the new page");
  assert(screenRoot.textContent.includes("Strong match"), "re-rendered with the new page's state, not stale");
  assert(!screenRoot.textContent.includes("Not enough to tailor from"), "old keywords-only content is gone");
  assert(legacyRoot.hidden === true, "legacy still hidden");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
