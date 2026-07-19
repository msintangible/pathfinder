/**
 * DOM tests for sidepanel/idle/index.js — Screen 1 (no job page, returning
 * user). Shows only when the tab isn't a job page AND a profile exists;
 * every other case falls back to the legacy stack.
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

/** Fresh jsdom + chrome mock, imports index.js (module cache busted per call).
 *  confidence defaults to a value consistent with isJobPage, matching how
 *  detect() actually pairs the two fields (isJobPage = confidence >= 0.4).
 *
 *  The mock state is mutable (`state.isJobPage`/`state.profile`) and the
 *  registered onUpdated callback is captured and returned, so a test can
 *  change what the "page" looks like and then simulate a tab-update event
 *  exactly as Chrome would fire it, instead of only testing the initial mount. */
async function mountController({ hasTab = true, isJobPage = false, confidence, profile = null } = {}) {
  const state = { isJobPage, confidence: confidence ?? (isJobPage ? 0.6 : 0), profile };
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="idle-root" hidden></div><div id="detection-screen-root" hidden></div><div id="legacy-root"></div></body></html>',
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
      sendMessage: async () => ({ detection: { isJobPage: state.isJobPage, confidence: state.confidence } }),
    },
    storage: {
      local: {
        get: async (key) => (key === "profile" && state.profile ? { profile: state.profile } : {}),
      },
    },
  };

  await import(`../src/sidepanel/idle/index.js?bust=${Math.random()}`);
  await tick();
  await tick();

  return {
    idleRoot: document.getElementById("idle-root"),
    legacyRoot: document.getElementById("legacy-root"),
    state,
    /** Simulate Chrome firing tabs.onUpdated, then wait for the async handler. */
    async fireTabUpdated(changeInfo) {
      onUpdatedCallback(1, changeInfo, { id: 1, active: true });
      await tick();
      await tick();
    },
  };
}

await test("no profile, no job: legacy shown, idle hidden", async () => {
  const { idleRoot, legacyRoot } = await mountController({ profile: null, isJobPage: false });
  assert(idleRoot.hidden === true, "idle screen stays hidden");
  assert(legacyRoot.hidden === false, "legacy stack shown");
});

await test("profile present, no job: idle screen shown with expected content", async () => {
  const { idleRoot, legacyRoot } = await mountController({ profile: { name: "Jane" }, isJobPage: false });
  assert(idleRoot.hidden === false, "idle screen shown");
  assert(legacyRoot.hidden === true, "legacy stack hidden");
  assert(idleRoot.textContent.includes("No job posting on this page"), "heading present");
  assert(idleRoot.textContent.includes("0"), "activity count shown as 0, not fabricated");
  assert(idleRoot.textContent.includes("applications tailored this week"), "activity copy present");
  assert(idleRoot.textContent.includes("Ready"), "profile status shown");
  assert(idleRoot.querySelector(".idle-btn-secondary")?.textContent === "View profile", "view profile button present");
});

await test("profile present, job page detected: falls back to legacy (not built yet)", async () => {
  const { idleRoot, legacyRoot } = await mountController({ profile: { name: "Jane" }, isJobPage: true });
  assert(idleRoot.hidden === true, "idle screen stays hidden for job-page states");
  assert(legacyRoot.hidden === false, "legacy stack shown");
});

await test("profile present, keywords-only confidence (isJobPage false, confidence > 0): idle no-ops, doesn't claim the screen", async () => {
  // Regression case: keywords-only also has isJobPage === false, so a naive
  // "!isJobPage && profile" check would wrongly show the idle screen too,
  // racing detection/index.js for the same tab. Idle must stay out of it.
  const { idleRoot, legacyRoot } = await mountController({
    profile: { name: "Jane" },
    isJobPage: false,
    confidence: 0.2,
  });
  assert(idleRoot.hidden === true, "idle screen must not claim the keywords-only state");
  assert(legacyRoot.hidden === false, "legacy stack left in its default state, untouched");
});

await test("no active tab: falls back to legacy", async () => {
  const { idleRoot, legacyRoot } = await mountController({ hasTab: false, profile: { name: "Jane" } });
  assert(idleRoot.hidden === true, "idle screen stays hidden with no active tab");
  assert(legacyRoot.hidden === false, "legacy stack shown");
});

await test("View profile reveals the legacy stack and hides the idle screen", async () => {
  const { idleRoot, legacyRoot } = await mountController({ profile: { name: "Jane" }, isJobPage: false });
  assert(idleRoot.hidden === false, "idle screen shown before click");

  idleRoot.querySelector(".idle-btn-secondary").click();

  assert(idleRoot.hidden === true, "idle screen hidden after View profile");
  assert(legacyRoot.hidden === false, "legacy stack shown after View profile");
});

await test("SPA route change (url set, no status) re-evaluates, not just full page loads", async () => {
  // Regression: Chrome doesn't re-enter status "complete" for a client-side
  // History API navigation — only changeInfo.url is set. The old listener
  // condition (status === "complete") silently ignored this, so the idle
  // screen went stale until the extension was manually reloaded.
  //
  // Starts on a job page (idle/index.js correctly no-ops, not its domain —
  // same as the "job page detected" test above), then simulates an SPA nav
  // to a true zero-confidence page. Only a working listener produces any
  // change here, since idle/index.js's own evaluate() is what has to re-run.
  const { idleRoot, legacyRoot, state, fireTabUpdated } = await mountController({
    profile: { name: "Jane" },
    isJobPage: true,
  });
  assert(idleRoot.hidden === true, "idle screen not shown initially (job page, not idle's domain)");

  state.isJobPage = false;
  state.confidence = 0;
  await fireTabUpdated({ url: "https://example.com/some-other-page" }); // no status field — SPA nav shape

  assert(idleRoot.hidden === false, "idle screen claims the panel once re-evaluated against the new page");
  assert(legacyRoot.hidden === true, "legacy stack hidden once idle takes over");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
