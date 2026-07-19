/**
 * DOM tests for sidepanel/job-analysis/index.js — the legacy "Analyse this
 * page" button and status line. This module had zero test coverage before
 * now, despite being one of the three real consumers of background/api.js's
 * analyzeJob() (the other two are detection/index.js and, indirectly via
 * the same GENERATE_RESUME path, optimize/index.js) — the raw-error-leak
 * regression found in this module was only caught by a live click-through,
 * not by any automated test, which is the gap this file closes.
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
async function flush(times = 5) { for (let i = 0; i < times; i++) await tick(); }

/** Fresh jsdom + chrome mock, imports index.js (module cache busted per call).
 *  `analyzeResponse` defaults to a realistic success; tests override it to
 *  exercise the failure paths. `sent` records every chrome.runtime.sendMessage
 *  call so a test can assert exactly which follow-up messages did or didn't fire. */
async function mountController({
  hasTab = true,
  scrapeResult = { text: "We are hiring a Data Analyst...", url: "https://example.com/job" },
  scrapeThrows = false,
  analyzeResponse = { ok: true, data: { id: "job-1", title: "Data Analyst", company: "Acme" } },
} = {}) {
  const sent = [];
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="job-analysis-root"></div></body></html>',
    { url: "https://example.com" }
  );
  global.document = dom.window.document;
  global.chrome = {
    tabs: {
      query: async () => (hasTab ? [{ id: 1 }] : []),
      sendMessage: async (_tabId, msg) => {
        if (msg.type !== "SCRAPE_PAGE") return null;
        if (scrapeThrows) throw new Error("no receiving end");
        return scrapeResult;
      },
    },
    runtime: {
      sendMessage: async (msg) => {
        sent.push(msg);
        if (msg.type === "ANALYZE_JOB") return analyzeResponse;
        return { ok: true };
      },
    },
  };

  await import(`../src/sidepanel/job-analysis/index.js?bust=${Math.random()}`);
  await flush();

  return { root: document.getElementById("job-analysis-root"), sent };
}

await test("initial render: enabled button, no status", async () => {
  const { root } = await mountController();
  const btn = root.querySelector("#analyse-job");
  assert(btn.textContent === "Analyse this page", "button label");
  assert(btn.disabled === false, "enabled by default");
  assert(root.querySelector(".status") === null, "no status line yet");
});

await test("success: shows completion status, saves job analysis and clears stale resume result", async () => {
  const { root, sent } = await mountController({
    analyzeResponse: { ok: true, data: { id: "job-1", title: "Data Analyst", company: "Acme" } },
  });

  root.querySelector("#analyse-job").click();
  await flush();

  assert(root.querySelector(".status")?.textContent === "Analysis complete.", "success status shown");
  assert(root.querySelector("#analyse-job").disabled === false, "button re-enabled");
  const saveJob = sent.find((m) => m.type === "SAVE_JOB_ANALYSIS");
  assert(saveJob?.payload.id === "job-1", "job analysis saved with the real id");
  const clearResume = sent.find((m) => m.type === "SAVE_RESUME_RESULT");
  assert(clearResume?.payload.data === null, "stale resume result cleared for the new job");
});

await test("no active tab: shows a plain, specific status, no crash", async () => {
  const { root } = await mountController({ hasTab: false });
  root.querySelector("#analyse-job").click();
  await flush();
  assert(root.querySelector(".status--err")?.textContent === "No active tab.", "status shown");
});

await test("scrape throws (content script unreachable): shows plain, actionable copy", async () => {
  const { root } = await mountController({ scrapeThrows: true });
  root.querySelector("#analyse-job").click();
  await flush();
  assert(
    root.querySelector(".status--err")?.textContent === "Can't read this page — reload the tab and try again.",
    `status: ${root.querySelector(".status--err")?.textContent}`
  );
});

await test("no text scraped: shows plain, specific status", async () => {
  const { root } = await mountController({ scrapeResult: { text: "", url: "https://example.com" } });
  root.querySelector("#analyse-job").click();
  await flush();
  assert(root.querySelector(".status--err")?.textContent === "No text scraped from this page.", "status shown");
});

await test("regression: a sanitized ANALYZE_JOB failure is shown verbatim, never wrapped or altered", async () => {
  // background/api.js's analyzeJob() is the single place that turns a raw
  // "HTTP {status}: {body}" backend failure into safe, plain copy (see its
  // sanitizedFailure() helper) — this module must not need to know that,
  // it only has to display res.error as-is without adding its own leak.
  // This is the exact case that shipped broken: a real 500 (Gemini quota
  // exhaustion) rendered as literal JSON here before the centralized fix.
  const { root } = await mountController({
    analyzeResponse: { ok: false, error: "Couldn't read this job posting. Try again." },
  });

  root.querySelector("#analyse-job").click();
  await flush();

  const status = root.querySelector(".status--err");
  assert(status?.textContent === "Couldn't read this job posting. Try again.", `status: ${status?.textContent}`);
  assert(!status.textContent.includes("HTTP"), "never shows a raw HTTP status");
  assert(!status.textContent.includes("{"), "never shows raw JSON");
  assert(root.querySelector("#analyse-job").disabled === false, "button re-enabled after failure");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
