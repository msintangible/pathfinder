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
  matched_keywords: ["SQL", "Power BI", "Reporting", "Excel", "Data cleaning", "Dashboards", "Stakeholders", "Analysis"],
  missing_keywords: ["Tableau", "Python"],
  added_keywords: [],
  download_url: "/v1/resumes/job-1/download",
};

/** Mounts a fresh jsdom + chrome mock and returns the module + roots.
 *  tabsCreated captures chrome.tabs.create calls, for asserting Download
 *  resume opens the right URL. */
async function mount() {
  const dom = new JSDOM(
    `<!doctype html><html><body>
      <div id="review-screen-root" hidden></div>
      <div id="success-screen-root" hidden></div>
      <div id="legacy-root"></div>
      <div id="idle-root"></div>
      <div id="detection-screen-root"></div>
      <div id="loading-screen-root"></div>
    </body></html>`,
    { url: "https://example.com" }
  );
  global.document = dom.window.document;
  const tabsCreated = [];
  const storedLocal = {};
  global.chrome = {
    storage: {
      local: {
        get: async (key) => {
          if (key === "profile") return { profile: PROFILE };
          if (key === "backendUrl") return { backendUrl: "http://localhost:8003" };
          if (key === "authToken") return { authToken: "test-token" };
          if (key in storedLocal) return { [key]: storedLocal[key] };
          return {};
        },
        set: async (values) => Object.assign(storedLocal, values),
      },
    },
    tabs: {
      create: (opts) => tabsCreated.push(opts),
    },
  };

  const mod = await import(`../src/sidepanel/review/index.js?bust=${Math.random()}`);
  return {
    root: document.getElementById("review-screen-root"),
    successRoot: document.getElementById("success-screen-root"),
    legacyRoot: document.getElementById("legacy-root"),
    tabsCreated,
    storedLocal,
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
  assert(
    root.textContent.includes(
      "Pathfinder rewords and reorders facts already in your profile. It never adds experience you don't have."
    ),
    "reassurance copy present verbatim"
  );
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
  const reasonEl = row.querySelector(".pf-diff-row__reason");
  const originalNewText = primary.textContent;
  const originalReason = reasonEl.textContent;

  assert(secondary.textContent.startsWith("was: "), "un-reverted: secondary line shows the original");
  assert(secondary.hidden === false, "un-reverted: secondary line is visible");

  row.querySelector(".pf-diff-row__revert").click();
  assert(primary.textContent !== originalNewText, "reverted: primary text switches away from the AI's version");
  assert(primary.classList.contains("pf-diff-row__new--original"), "reverted: primary box drops the AI-content styling");
  assert(reasonEl.textContent === "Reverted to original", "reverted: reason line names the state");
  assert(secondary.hidden === false, "reverted: secondary line stays visible — the suggested-vs-chosen contrast is the trust receipt and must survive revert (intentional deviation from Pathfinder Diff.dc.html)");
  assert(secondary.textContent.startsWith("AI suggested: "), "reverted: secondary line now shows the AI's version");
  assert(secondary.textContent.includes(originalNewText), "reverted: the AI's version is still visible, just demoted");

  row.querySelector(".pf-diff-row__revert").click();
  assert(reasonEl.textContent === originalReason, "restored: reason line goes back to the real change reason");
  assert(secondary.textContent.startsWith("was: "), "restored: secondary line goes back to showing the original");
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

await test("Download resume increments the weekly count", async () => {
  const { root, storedLocal, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  const downloadBtn = [...root.querySelectorAll("button")].find((b) => b.textContent === "Download resume");
  downloadBtn.click();
  await new Promise((r) => setTimeout(r, 0));

  assert(storedLocal.weeklyCount?.count === 1, `weekly count persisted at 1, got ${JSON.stringify(storedLocal.weeklyCount)}`);

  downloadBtn.click();
  await new Promise((r) => setTimeout(r, 0));
  assert(storedLocal.weeklyCount?.count === 2, "second download increments again");
});

await test("Download resume hands off to the success screen with the real kept count", async () => {
  const { root, successRoot, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });

  // Revert one of the two changes before downloading — the success screen
  // must reflect what was actually kept, not the total.
  root.querySelector(".pf-diff-row__revert").click();

  const downloadBtn = [...root.querySelectorAll("button")].find((b) => b.textContent === "Download resume");
  downloadBtn.click();
  await new Promise((r) => setTimeout(r, 0));

  assert(successRoot.hidden === false, "success screen shown after download");
  assert(root.hidden === true, "review screen hidden once success claims the panel");
  assert(successRoot.textContent.includes("1 of 2 tailored changes kept"), "real kept count carried over, not the total");
  assert(successRoot.textContent.includes("Data Analyst · Reperio Human Capital"), "job line carried over");
});

await test("missing title/company: no subtitle line rendered, no crash", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT });
  assert(root.querySelector(".review-subtitle") === null, "no subtitle element when title/company are absent");
});

await test("fit warning: under the 40% gap threshold, no banner renders", async () => {
  const { root, showReviewScreen } = await mount();
  await showReviewScreen({ result: RESULT, title: "Data Analyst", company: "Reperio Human Capital" });
  assert(root.querySelector(".pf-fitwarn") === null, "2 of 10 missing (20%) stays below threshold");
});

await test("fit warning: over the 40% gap threshold, banner renders collapsed with real counts", async () => {
  const { root, showReviewScreen } = await mount();
  const result = {
    ...RESULT,
    matched_keywords: ["SQL", "Excel"],
    missing_keywords: ["Tableau", "Python", "AWS", "Kubernetes", "Terraform"],
    added_keywords: [],
  };
  await showReviewScreen({ result, title: "Data Analyst", company: "Reperio Human Capital" });

  const banner = root.querySelector(".pf-fitwarn");
  assert(banner, "5 of 7 missing (71%) clears threshold — banner renders");
  assert(banner.textContent.includes("This role is a significant stretch"), "headline present verbatim");
  assert(banner.textContent.includes("5 of 7 core requirements aren't in your background yet."), "real counts, not placeholder numbers");
  assert(banner.querySelector(".pf-fitwarn__body").hidden === true, "collapsed by default");
  assert(banner.querySelector(".pf-fitwarn__toggle").getAttribute("aria-expanded") === "false", "aria-expanded reflects collapsed state");
});

await test("fit warning: added_keywords count as no-longer-missing, same as the backend's own after-tailoring view", async () => {
  const { root, showReviewScreen } = await mount();
  const result = {
    ...RESULT,
    matched_keywords: ["SQL", "Excel"],
    // 5 originally missing, but 3 got woven into the resume from real profile content —
    // only 2 should still count as a gap.
    missing_keywords: ["Tableau", "Python", "AWS", "Kubernetes", "Terraform"],
    added_keywords: ["AWS", "Kubernetes", "Terraform"],
  };
  await showReviewScreen({ result, title: "Data Analyst", company: "Reperio Human Capital" });

  const banner = root.querySelector(".pf-fitwarn");
  assert(banner === null, "2 of 7 missing (29%) after crediting added_keywords stays below threshold");
});

await test("fit warning: toggle expands to grouped chips, no invented reasons for the flat backend list", async () => {
  const { root, showReviewScreen } = await mount();
  const result = {
    ...RESULT,
    matched_keywords: ["SQL", "Excel"],
    missing_keywords: ["Tableau", "Python", "AWS", "Kubernetes", "Terraform"],
    added_keywords: [],
  };
  await showReviewScreen({ result, title: "Data Analyst", company: "Reperio Human Capital" });

  const banner = root.querySelector(".pf-fitwarn");
  const toggle = banner.querySelector(".pf-fitwarn__toggle");
  const body = banner.querySelector(".pf-fitwarn__body");

  toggle.click();
  assert(body.hidden === false, "expands on click");
  assert(toggle.getAttribute("aria-expanded") === "true", "aria-expanded flips");
  assert(toggle.textContent.includes("Hide what's missing"), "toggle label flips");

  const chips = [...body.querySelectorAll(".pf-fitwarn__chip")].map((c) => c.textContent);
  assert(chips.length === 5, "one chip per still-missing keyword");
  assert(chips.includes("Tableau") && chips.includes("Terraform"), "real keyword text, not fabricated categories");
  assert(body.querySelectorAll(".pf-fitwarn__reason").length === 0, "no reason line — the backend gives no reason to show, so none is invented");
  assert(body.textContent.includes("Pathfinder won't invent experience you don't have."), "closing line present verbatim");

  toggle.click();
  assert(body.hidden === true, "collapses again on second click");
});

await test("fit warning: dismiss hides the banner without touching the diff below it", async () => {
  const { root, showReviewScreen } = await mount();
  const result = {
    ...RESULT,
    matched_keywords: ["SQL", "Excel"],
    missing_keywords: ["Tableau", "Python", "AWS", "Kubernetes", "Terraform"],
    added_keywords: [],
  };
  await showReviewScreen({ result, title: "Data Analyst", company: "Reperio Human Capital" });

  const banner = root.querySelector(".pf-fitwarn");
  banner.querySelector(".pf-fitwarn__dismiss").click();
  assert(banner.hidden === true, "banner hides on dismiss");
  assert(root.querySelectorAll(".pf-diff-row").length === 2, "diff rows untouched by dismissing the banner");
});

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
