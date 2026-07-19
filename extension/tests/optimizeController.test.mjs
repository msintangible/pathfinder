/**
 * DOM tests for sidepanel/optimize/index.js — the Optimize CV card is
 * gated on a saved profile + a job analysis for the active tab, calls the
 * existing GENERATE_RESUME flow, and renders the ATS score, keyword match,
 * change explanation, and a PDF link.
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
async function flush(times = 5) { for (let i = 0; i < times; i++) await tick(); }

/** value or (tabId) => value, resolved against the tab id a message was sent for. */
function resolvePerTab(value, tabId) {
  return typeof value === "function" ? value(tabId) : value;
}

/** Fresh chrome mock. jobAnalysis/resumeResult may be a value or a (tabId) => value function. */
function createChromeMock({
  profileId = null,
  profile = null,
  backendUrl = "http://localhost:8003",
  jobAnalysis = null,
  resumeResult = null,
  generateResult = null,
  tabId = 1,
  authToken = "test-token",
} = {}) {
  const sent = [];
  const listeners = {};
  const tabsCreated = [];

  const chrome = {
    storage: {
      local: {
        get: async (key) => {
          if (key === "profileId") return profileId != null ? { profileId } : {};
          if (key === "profile") return profile != null ? { profile } : {};
          if (key === "backendUrl") return { backendUrl };
          if (key === "authToken") return authToken != null ? { authToken } : {};
          return {};
        },
        set: async () => {},
      },
      onChanged: {
        addListener: (fn) => { listeners.onChanged = fn; },
      },
    },
    tabs: {
      query: async () => [{ id: tabId }],
      onActivated: {
        addListener: (fn) => { listeners.onActivated = fn; },
      },
      create: (opts) => { tabsCreated.push(opts); },
    },
    runtime: {
      sendMessage: async (message) => {
        sent.push(message);
        switch (message.type) {
          case "GET_JOB_ANALYSIS":
            return { jobAnalysis: resolvePerTab(jobAnalysis, message.payload?.tabId) };
          case "GET_RESUME_RESULT":
            return { resumeResult: resolvePerTab(resumeResult, message.payload?.tabId) };
          case "SAVE_RESUME_RESULT":
            return { ok: true };
          case "GENERATE_RESUME":
            return generateResult;
          default:
            return { ok: false, error: `unhandled message: ${message.type}` };
        }
      },
    },
  };

  return { chrome, sent, listeners, tabsCreated };
}

/** Fresh jsdom + chrome mock, imports index.js (module cache busted per call). */
async function mountController(opts) {
  const dom = new JSDOM('<!doctype html><html><body><div id="optimize-root"></div></body></html>', {
    url: "https://example.com",
  });
  global.document = dom.window.document;
  const mock = createChromeMock(opts);
  global.chrome = mock.chrome;

  await import(`../src/sidepanel/optimize/index.js?bust=${Math.random()}`);
  await flush();

  return { root: document.getElementById("optimize-root"), ...mock };
}

const job = { id: "job1", title: "Backend Engineer", company: "Acme", url: "https://example.com/job" };

await test("no profile, no job: shows NO_PROFILE_HINT, button disabled", async () => {
  const { root } = await mountController({ profileId: null, jobAnalysis: null });

  assert(root.querySelector(".status").textContent === Message.NO_PROFILE_HINT, "hint text");
  assert(root.querySelector("#optimize-cv").disabled === true, "button disabled");
});

await test("profile present, no job: shows NO_JOB_HINT, button disabled", async () => {
  const { root } = await mountController({ profileId: "p1", jobAnalysis: null });

  assert(root.querySelector(".status").textContent === Message.NO_JOB_HINT, "hint text");
  assert(root.querySelector("#optimize-cv").disabled === true, "button disabled");
});

await test("profile data present but profileId missing: shows re-import hint, not NO_PROFILE_HINT", async () => {
  const { root } = await mountController({ profileId: null, profile: { name: "Michael Salami" }, jobAnalysis: job });

  assert(root.querySelector(".status").textContent === Message.PROFILE_NEEDS_REIMPORT_HINT, "re-import hint shown");
  assert(root.querySelector("#optimize-cv").disabled === true, "button disabled");
});

await test("both present, no prior result: button enabled, labeled Optimize CV", async () => {
  const { root } = await mountController({ profileId: "p1", jobAnalysis: job });

  assert(root.querySelector(".status") === null, "no hint shown");
  const btn = root.querySelector("#optimize-cv");
  assert(btn.disabled === false, "button enabled");
  assert(btn.textContent === Message.OPTIMIZE_CV, "button label");
});

await test("generate success: renders ATS score, keywords, changes, and Open Resume", async () => {
  const generateResult = {
    ok: true,
    data: {
      ats_score: 82.4,
      matched_keywords: ["Python", "AWS"],
      missing_keywords: ["Kubernetes"],
      optimized_resume: { changes_summary: ["Reworded summary to emphasize backend experience."] },
      download_url: "/v1/resumes/abc/download",
    },
  };
  const { root, sent, tabsCreated } = await mountController({ profileId: "p1", jobAnalysis: job, generateResult });

  root.querySelector("#optimize-cv").click();
  await flush();

  const generateMsg = sent.find((m) => m.type === "GENERATE_RESUME");
  assert(generateMsg, "GENERATE_RESUME was sent");
  assert(
    generateMsg.payload.user_profile_id === "p1" && generateMsg.payload.job_id === "job1",
    `GENERATE_RESUME payload: ${JSON.stringify(generateMsg.payload)}`
  );

  const saveMsg = sent.find((m) => m.type === "SAVE_RESUME_RESULT");
  assert(saveMsg?.payload?.tabId === 1 && saveMsg.payload.data === generateResult.data, "SAVE_RESUME_RESULT persisted");

  assert(root.querySelector(".opt-score").textContent.includes("82"), "ATS score rendered");
  assert(root.querySelectorAll(".badge--ok").length === 2, "2 matched keyword pills");
  assert(root.querySelectorAll(".badge--err").length === 1, "1 missing keyword pill");
  const changes = Array.from(root.querySelectorAll(".opt-changes li")).map((li) => li.textContent);
  assert(changes.includes("Reworded summary to emphasize backend experience."), `changes: ${changes}`);

  const btn = root.querySelector("#optimize-cv");
  assert(btn.disabled === false && btn.textContent === Message.REOPTIMIZE, "button relabeled Re-optimize");

  const openResumeBtn = Array.from(root.querySelectorAll("button")).find((b) => b.textContent === Message.OPEN_RESUME);
  assert(openResumeBtn, "Open Resume button present");
  openResumeBtn.click();
  await flush();
  assert(
    tabsCreated[0]?.url === "http://localhost:8003/v1/resumes/abc/download?token=test-token",
    `opened URL: ${tabsCreated[0]?.url}`
  );
});

await test("generate success with added_keywords: renders Added section, excludes them from Missing", async () => {
  const generateResult = {
    ok: true,
    data: {
      ats_score: 82.4,
      matched_keywords: ["Python"],
      missing_keywords: ["Kubernetes", "Terraform"],
      added_keywords: ["Kubernetes"],
      optimized_resume: { changes_summary: [] },
      download_url: "/v1/resumes/abc/download",
    },
  };
  const { root } = await mountController({ profileId: "p1", jobAnalysis: job, generateResult });

  root.querySelector("#optimize-cv").click();
  await flush();

  const addedPills = Array.from(root.querySelectorAll(".badge--warn")).map((b) => b.textContent);
  assert(addedPills.length === 1 && addedPills[0] === "Kubernetes", `added pills: ${addedPills}`);

  const missingPills = Array.from(root.querySelectorAll(".badge--err")).map((b) => b.textContent);
  assert(missingPills.length === 1 && missingPills[0] === "Terraform", `missing pills: ${missingPills}`);

  // Keyword sections must precede the ATS score in document order.
  const resultEl = root.querySelector("#optimize-result");
  const children = Array.from(resultEl.children);
  const addedIndex = children.findIndex(
    (el) => el.classList.contains("opt-keywords") && el.querySelector(".opt-keywords-heading")?.textContent === "Added to your CV"
  );
  const scoreIndex = children.findIndex((el) => el.classList.contains("opt-score"));
  assert(addedIndex !== -1 && scoreIndex !== -1 && addedIndex < scoreIndex, "keyword section renders before the ATS score");
});

await test("generate failure: shows GENERATE_FAILED, re-enables button, no result", async () => {
  const generateResult = { ok: false, error: "HTTP 500: boom" };
  const { root } = await mountController({ profileId: "p1", jobAnalysis: job, generateResult });

  root.querySelector("#optimize-cv").click();
  await flush();

  const err = root.querySelector(".status--err");
  assert(err?.textContent === `${Message.GENERATE_FAILED} Try again.`, `error text: ${err?.textContent}`);
  const btn = root.querySelector("#optimize-cv");
  assert(btn.disabled === false, "button re-enabled");
  assert(btn.textContent === Message.OPTIMIZE_CV, "still says Optimize CV, no result was saved");
  const resultEl = root.querySelector("#optimize-result");
  assert(!resultEl || resultEl.children.length === 0, "no result rendered");
});

await test("generate failure: never shows the raw HTTP/JSON detail regardless of what background/api.js returns", async () => {
  // Regression test. Sanitization now happens once, centrally, in
  // background/api.js's generateResume() (see api.test.mjs's own
  // regression test for that layer, including the "logged for debugging"
  // half of this). This panel no longer inspects res.error's content at
  // all — it always shows a fixed "Try again." — so this test mocks a
  // worst-case raw response on purpose, to prove that even if something
  // upstream regressed, this panel still can't leak it.
  const rawError = 'HTTP 500: {"error":{"code":"INTERNAL_SERVER_ERROR","message":"An unexpected error occurred."}}';
  const generateResult = { ok: false, error: rawError };

  const { root } = await mountController({ profileId: "p1", jobAnalysis: job, generateResult });
  root.querySelector("#optimize-cv").click();
  await flush();

  const err = root.querySelector(".status--err");
  assert(!err.textContent.includes("HTTP 500"), "never shows the raw HTTP status");
  assert(!err.textContent.includes("INTERNAL_SERVER_ERROR"), "never shows the raw JSON body");
  assert(err.textContent.includes(Message.GENERATE_FAILED), "still shows the plain failure copy");
});

await test("restore on reopen: renders a cached result without calling GENERATE_RESUME", async () => {
  const resumeResult = {
    ats_score: 90,
    matched_keywords: ["Go"],
    missing_keywords: [],
    optimized_resume: { changes_summary: [] },
    download_url: "/v1/resumes/xyz/download",
  };
  const { root, sent } = await mountController({ profileId: "p1", jobAnalysis: job, resumeResult });

  assert(root.querySelector(".opt-score").textContent.includes("90"), "cached ATS score rendered on load");
  assert(root.querySelector("#optimize-cv").textContent === Message.REOPTIMIZE, "button shows Re-optimize");
  assert(sent.every((m) => m.type !== "GENERATE_RESUME"), "no GENERATE_RESUME call on restore");
});

await test("profile imported while open (storage.onChanged): hint clears live", async () => {
  const { root, listeners } = await mountController({ profileId: null, jobAnalysis: job });

  assert(root.querySelector(".status").textContent === Message.NO_PROFILE_HINT, "starts blocked on profile");

  await listeners.onChanged({ profileId: { newValue: "p1", oldValue: undefined } }, "local");
  await flush();

  assert(root.querySelector(".status") === null, "hint cleared");
  assert(root.querySelector("#optimize-cv").disabled === false, "button now enabled");
});

await test("tab switch (tabs.onActivated): reverts to NO_JOB_HINT on a tab with no analysis", async () => {
  const jobByTab = (tabId) => (tabId === 1 ? job : null);
  const { root, listeners } = await mountController({ profileId: "p1", jobAnalysis: jobByTab, tabId: 1 });

  assert(root.querySelector("#optimize-cv").disabled === false, "starts enabled on tab 1");

  await listeners.onActivated({ tabId: 2 });
  await flush();

  assert(root.querySelector(".status").textContent === Message.NO_JOB_HINT, "blocked on tab 2");
  assert(root.querySelector("#optimize-cv").disabled === true, "button disabled on tab 2");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
