/**
 * Unit tests for background/index.js's handlePageDetected() — the
 * cross-frame detection merge introduced by manifest.json's all_frames: true
 * (an iframe-embedded ATS, e.g. Lever/Workday, now reports its own detection
 * independently of the surrounding top-level page).
 *
 * Mocks chrome.storage.session and chrome.action; background/index.js is an
 * ES module (manifest.json declares "type": "module" for the service
 * worker), so it's imported directly rather than eval'd like the plain
 * content scripts. Cache-busted per test since importing it re-registers
 * chrome.runtime listeners against whatever `chrome` mock is current.
 *
 * Run with: npm test
 */

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

/** Fresh chrome mock with an in-memory chrome.storage.session and badge call log. */
function createChromeMock() {
  const session = new Map();
  const badgeCalls = [];
  const chrome = {
    runtime: {
      onInstalled: { addListener: () => {} },
      onMessage: { addListener: () => {} },
    },
    sidePanel: { setPanelBehavior: async () => {} },
    tabs: { onRemoved: { addListener: () => {} } },
    storage: {
      session: {
        get: async (key) => (session.has(key) ? { [key]: session.get(key) } : {}),
        set: async (obj) => { for (const [k, v] of Object.entries(obj)) session.set(k, v); },
        remove: async (key) => { session.delete(key); },
      },
    },
    action: {
      setBadgeText: async (opts) => { badgeCalls.push({ kind: "text", ...opts }); },
      setBadgeBackgroundColor: async (opts) => { badgeCalls.push({ kind: "color", ...opts }); },
    },
  };
  return { chrome, badgeCalls, session };
}

/** Import a fresh instance of background/index.js against the given chrome mock. */
async function loadHandler(chrome) {
  global.chrome = chrome;
  const mod = await import(`../src/background/index.js?bust=${Math.random()}`);
  return mod.handlePageDetected;
}

function detection({ confidence, isJobPage = confidence >= 0.4 }) {
  return { isJobPage, confidence, signals: {}, url: "https://example.com", detectedAt: "2026-07-02T00:00:00Z" };
}

function frameSender(tabId, tabUrl, frameId = 0) {
  return { tab: { id: tabId, url: tabUrl }, frameId };
}

// ---------------------------------------------------------------------------
await test("single frame: stores its detection and sets the badge", async () => {
  const { chrome, badgeCalls } = createChromeMock();
  const handlePageDetected = await loadHandler(chrome);

  await handlePageDetected(detection({ confidence: 0.7 }), frameSender(1, "https://acme.com/careers/1"));

  const stored = (await chrome.storage.session.get("detection:1"))["detection:1"];
  assert(stored.confidence === 0.7, `confidence: ${stored.confidence}`);
  assert(badgeCalls.some((c) => c.kind === "text" && c.tabId === 1 && c.text === "JOB"), "badge set to JOB");
});

await test("no tabId on sender: no-op, does not throw", async () => {
  const { chrome, badgeCalls } = createChromeMock();
  const handlePageDetected = await loadHandler(chrome);

  await handlePageDetected(detection({ confidence: 0.9 }), { tab: undefined });

  assert(badgeCalls.length === 0, "no badge calls without a tabId");
});

await test("cross-frame merge: a later higher-confidence iframe result wins", async () => {
  const { chrome, badgeCalls } = createChromeMock();
  const handlePageDetected = await loadHandler(chrome);
  const tabUrl = "https://acme.com/careers/1"; // same top-level URL for both frames

  await handlePageDetected(detection({ confidence: 0.2, isJobPage: false }), frameSender(1, tabUrl, 0));
  await handlePageDetected(detection({ confidence: 0.7, isJobPage: true }), frameSender(1, tabUrl, 5));

  const stored = (await chrome.storage.session.get("detection:1"))["detection:1"];
  assert(stored.confidence === 0.7, `expected the iframe's higher confidence, got ${stored.confidence}`);
  const lastText = badgeCalls.filter((c) => c.kind === "text").at(-1);
  assert(lastText.text === "JOB", `expected JOB badge, got ${JSON.stringify(lastText)}`);
});

await test("cross-frame merge: a later LOWER-confidence main-frame result does not clobber the winner", async () => {
  const { chrome, badgeCalls } = createChromeMock();
  const handlePageDetected = await loadHandler(chrome);
  const tabUrl = "https://acme.com/careers/1";

  // iframe (Lever embed) reports high confidence first...
  await handlePageDetected(detection({ confidence: 0.7, isJobPage: true }), frameSender(1, tabUrl, 5));
  // ...then the surrounding top-level page reports low confidence.
  await handlePageDetected(detection({ confidence: 0.2, isJobPage: false }), frameSender(1, tabUrl, 0));

  const stored = (await chrome.storage.session.get("detection:1"))["detection:1"];
  assert(stored.confidence === 0.7, `iframe's result should survive, got ${stored.confidence}`);
  const lastText = badgeCalls.filter((c) => c.kind === "text").at(-1);
  assert(lastText.text === "JOB", "badge should stay JOB, not be cleared by the weaker frame");
});

await test("real navigation (different tab URL) resets rather than merges, even to a lower score", async () => {
  const { chrome, badgeCalls } = createChromeMock();
  const handlePageDetected = await loadHandler(chrome);

  await handlePageDetected(detection({ confidence: 0.9, isJobPage: true }), frameSender(1, "https://acme.com/careers/old-role", 0));
  await handlePageDetected(detection({ confidence: 0.1, isJobPage: false }), frameSender(1, "https://acme.com/about", 0));

  const stored = (await chrome.storage.session.get("detection:1"))["detection:1"];
  assert(stored.confidence === 0.1, `expected the new page's score to win outright, got ${stored.confidence}`);
  const lastText = badgeCalls.filter((c) => c.kind === "text").at(-1);
  assert(lastText.text === "", "badge should clear after navigating to a non-job page");
});

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
