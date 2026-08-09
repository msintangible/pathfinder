/**
 * DOM tests for sidepanel/review/index.js — Screen 4 (Review changes),
 * shown after a successful tailoring run. showReviewScreen() is called
 * directly (mirroring how detection/index.js's handleTailor() drives it)
 * rather than through the full tailoring flow, which detectionController
 * tests already cover up to the point Screen 3 hands off.
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

const PROFILE = {
  summary: "Analyst with experience in reporting and business dashboards.",
  skills: ["Excel", "Reporting", "SQL", "Power BI", "Data cleaning"],
  experience: [],
};

const RESULT = {
  optimized_resume: {
    summary: "Data analyst specialising in SQL reporting and Power BI dashboards for stakeholder decisions.",
    skills: ["SQL", "Power BI", "Stakeholder reporting", "Excel", "Data cleaning"],
    experience: [],
  },
  report: {
    highlights: [
      { section: "Professional Summary", summary: "Reworded to match the job's language", impact: "high" },
      { section: "Skills", summary: "Reordered to lead with top skills", impact: "medium" },
    ],
  },
  download_url: "/v1/resumes/job-1/download",
};

/** Mounts a fresh jsdom + chrome mock and returns the module + roots.
 *  tabsCreated captures chrome.tabs.create calls, for asserting Download
 *  resume opens the right URL. */
async function mount() {
  const dom = new JSDOM(
    `<!doctype html><html><body>
      <div id="review-screen-root" hidden></div>
      <div id="legacy-root"></div>
      <div id="idle-root"></div>
      <div id="detection-screen-root"></div>
      <div id="loading-screen-root"></div>
    </body></html>`,
    { url: "https://example.com" }
  );
  global.document = dom.window.document;
  const tabsCreated = [];
  global.chrome = {
    storage: {
      local: {
        get: async (key) => {
          if (key === "profile") return { profile: PROFILE };
          if (key === "backendUrl") return { backendUrl: "http://localhost:8003" };
          if (key === "authToken") return { authToken: "test-token" };
          return {};
        },
        set: async () => {},
      },
    },
    tabs: {
      create: (opts) => tabsCreated.push(opts),
    },
  };

  const mod = await import(`../src/sidepanel/review/index.js?bust=${Math.random()}`);
  return {
    root: document.getElementById("review-screen-root"),
    legacyRoot: document.getElementById("legacy-root"),
    tabsCreated,
    ...mod,
  };
}

await test("renders header, heading, job subtitle, and one row per confidently-matched highlight", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  assert(root.hidden === false, "review screen shown");
  assert(root.textContent.includes("Review changes"), "heading present");
  assert(root.textContent.includes("Data Analyst · Reperio Human Capital"), "job subtitle present");
  assert(root.querySelectorAll(".pf-diff-row").length === 2, "one row per matched highlight");
  assert(root.textContent.includes("PROFESSIONAL SUMMARY"), "summary section label (rendered uppercase)");
  assert(root.textContent.includes("SKILLS"), "skills section label (rendered uppercase)");
  assert(root.textContent.includes("2 of 2 changes kept"), "kept count starts at all changes kept");
});

await test("claims the panel: hides legacy/idle/detection/loading roots", async () => {
  const { root, legacyRoot } = await mount();
  legacyRoot.hidden = false;
  const { showReviewScreen } = await import(`../src/sidepanel/review/index.js?bust=${Math.random()}`);
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });
  assert(legacyRoot.hidden === true, "legacy hidden once review screen claims the panel");
});

await test("Revert toggles a row's kept state and updates the live count, without touching other rows", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  const revertButtons = [...root.querySelectorAll(".pf-diff-row__revert")];
  assert(revertButtons.length === 2, "one Revert button per row");

  revertButtons[0].click();
  assert(revertButtons[0].textContent === "Restore", "reverted row's button now offers Restore");
  assert(revertButtons[1].textContent === "Revert", "the other row is untouched");
  assert(root.textContent.includes("1 of 2 changes kept"), "count reflects the one reverted row");

  revertButtons[0].click();
  assert(revertButtons[0].textContent === "Revert", "clicking again restores it");
  assert(root.textContent.includes("2 of 2 changes kept"), "count back to all kept");
});

await test("Revert actually swaps the row's own displayed text, not just its label", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  const row = root.querySelector(".pf-diff-row");
  const primary = row.querySelector(".pf-diff-row__new");
  const secondary = row.querySelector(".pf-diff-row__old");
  const originalNewText = primary.textContent;

  assert(secondary.textContent.startsWith("was: "), "un-reverted: secondary line shows the original");

  row.querySelector(".pf-diff-row__revert").click();
  assert(primary.textContent !== originalNewText, "reverted: primary text switches away from the AI's version");
  assert(primary.classList.contains("pf-diff-row__new--original"), "reverted: primary box drops the AI-content styling");
  assert(secondary.textContent.startsWith("AI suggested: "), "reverted: secondary line now shows the AI's version");
  assert(secondary.textContent.includes(originalNewText), "reverted: the AI's version is still visible, just demoted");
});

await test("the download-still-includes-everything notice only appears once something is reverted", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  const notice = root.querySelector(".review-notice");
  assert(notice.hidden === true, "hidden while every change is still kept — nothing to disclose yet");

  root.querySelector(".pf-diff-row__revert").click();
  assert(notice.hidden === false, "shown once a row is reverted");
  assert(notice.textContent.includes("still download"), "explains the download is unaffected by reverts");

  root.querySelector(".pf-diff-row__revert").click();
  assert(notice.hidden === true, "hidden again once nothing is reverted");
});

await test("an unmatchable highlight produces no row, and the kept count reflects only real matches", async () => {
  const { root, showReviewScreen } = await mount();
  const result = {
    ...RESULT,
    report: { highlights: [{ section: "Certifications", summary: "Added a cert", impact: "low" }] },
  };
  await showReviewScreen({ result, title: "Data Analyst", company: "Reperio Human Capital" });
  assert(root.querySelectorAll(".pf-diff-row").length === 0, "no row for an unmatchable section");
  assert(root.textContent.includes("0 of 0 changes kept"), "count reflects zero confidently-matched changes");
});

await test("Download resume opens the real download URL with an auth token", async () => {
  const { root, tabsCreated, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  const downloadBtn = [...root.querySelectorAll("button")].find((b) => b.textContent === "Download resume");
  assert(downloadBtn, "Download resume button present");
  downloadBtn.click();
  await new Promise((r) => setTimeout(r, 0));

  assert(tabsCreated.length === 1, "opens exactly one tab");
  assert(tabsCreated[0].url.includes("/v1/resumes/job-1/download"), "real download_url used");
  assert(tabsCreated[0].url.includes("token=test-token"), "auth token attached");
});

await test("missing title/company: no subtitle line rendered, no crash", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT });
  assert(root.querySelector(".review-subtitle") === null, "no subtitle element when title/company are absent");
});

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
