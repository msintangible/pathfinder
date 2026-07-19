/**
 * DOM tests for sidepanel/detection/index.js — the 3 job-page-ish redesign
 * screens (Known ATS, Unknown ATS, Keywords only) plus the legacy badge
 * fallback they layer on top of.
 *
 * Run with: npm test
 */
import { JSDOM } from "jsdom";

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }
const tick = () => new Promise((r) => setTimeout(r, 0));

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
async function mountController({ hasTab = true, detection = null, jobAnalysis = null } = {}) {
  const state = { detection, jobAnalysis };
  const dom = new JSDOM(
    `<!doctype html><html><body>
      <div id="idle-root" hidden></div>
      <div id="detection-screen-root" hidden></div>
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
    },
    runtime: {
      sendMessage: async (msg) => {
        if (msg.type === "GET_DETECTION") return { detection: state.detection };
        if (msg.type === "GET_JOB_ANALYSIS") return { jobAnalysis: state.jobAnalysis };
        return null;
      },
    },
  };

  await import(`../src/sidepanel/detection/index.js?bust=${Math.random()}`);
  await tick();
  await tick();

  return {
    screenRoot: document.getElementById("detection-screen-root"),
    legacyRoot: document.getElementById("legacy-root"),
    idleRoot: document.getElementById("idle-root"),
    state,
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

await test("known ATS: Tailor my resume is disabled, not silently inert", async () => {
  const { screenRoot } = await mountController({ detection: knownAts() });
  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor my resume");
  assert(btn, "button present");
  assert(btn.disabled === true, "button is genuinely disabled");
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

await test("unknown ATS: Tailor with what's here is disabled", async () => {
  const { screenRoot } = await mountController({ detection: unknownAts() });
  const btn = Array.from(screenRoot.querySelectorAll("button")).find((b) => b.textContent === "Tailor with what's here");
  assert(btn, "button present");
  assert(btn.disabled === true, "button is genuinely disabled");
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
