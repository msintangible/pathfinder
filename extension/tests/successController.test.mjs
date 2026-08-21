/**
 * DOM tests for sidepanel/success/index.js — Screen 12 (download success),
 * shown after "Download resume" on Screen 4. showDownloadSuccessScreen() is
 * called directly, mirroring how review/index.js's Download handler drives
 * it (reviewController.test.mjs covers that hand-off itself).
 *
 * Run with: npm test
 */
import { JSDOM, VirtualConsole } from "jsdom";

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

/** Mounts a fresh jsdom with every known screen root. jsdom's window.location
 *  is non-configurable (can't be swapped for a reload spy), and real
 *  navigation isn't implemented — calling reload() doesn't throw, it just
 *  reports "Not implemented: navigation" asynchronously via the virtual
 *  console, which this captures instead. */
async function mount() {
  const virtualConsole = new VirtualConsole();
  const jsdomErrors = [];
  virtualConsole.on("jsdomError", (e) => jsdomErrors.push(e.message));

  const dom = new JSDOM(
    `<!doctype html><html><body>
      <div id="success-screen-root" hidden></div>
      <div id="review-screen-root"></div>
      <div id="legacy-root"></div>
      <div id="idle-root"></div>
      <div id="detection-screen-root"></div>
      <div id="loading-screen-root"></div>
    </body></html>`,
    { url: "https://example.com", virtualConsole }
  );
  global.document = dom.window.document;
  global.window = dom.window;

  const mod = await import(`../src/sidepanel/success/index.js?bust=${Math.random()}`);
  return {
    root: document.getElementById("success-screen-root"),
    reviewRoot: document.getElementById("review-screen-root"),
    legacyRoot: document.getElementById("legacy-root"),
    reloadWasAttempted: async () => {
      await new Promise((r) => setTimeout(r, 0));
      return jsdomErrors.some((m) => m.includes("navigation"));
    },
    ...mod,
  };
}

await test("renders headline, real job/company body copy, and both sections", async () => {
  const { root, showDownloadSuccessScreen } = await mount();
  showDownloadSuccessScreen({
    title: "Data Analyst",
    company: "Reperio Human Capital",
    keptCount: 4,
    totalCount: 4,
    weeklyCount: 3,
  });

  assert(root.hidden === false, "success screen shown");
  assert(root.textContent.includes("Resume downloaded"), "headline present");
  assert(
    root.textContent.includes("Your resume for Data Analyst at Reperio Human Capital was downloaded. Your original was left untouched."),
    "body names the real job/company, no fabricated filename"
  );
  assert(root.textContent.includes("Data Analyst · Reperio Human Capital"), "job line present");
  assert(root.textContent.includes("4 of 4 tailored changes kept"), "kept-count line present");
  assert(root.querySelector(".success-activity__count")?.textContent === "3", "real weekly count rendered");
  assert(root.textContent.includes("applications tailored this week"), "activity copy present");
});

await test("reverted changes: kept count reflects what was actually downloaded, not the total", async () => {
  const { root, showDownloadSuccessScreen } = await mount();
  showDownloadSuccessScreen({ title: "Data Analyst", company: "Reperio", keptCount: 2, totalCount: 4, weeklyCount: 1 });
  assert(root.textContent.includes("2 of 4 tailored changes kept"), "partial kept count shown, not fabricated as 4 of 4");
});

await test("missing title/company: no crash, generic body copy, no job line", async () => {
  const { root, showDownloadSuccessScreen } = await mount();
  showDownloadSuccessScreen({ keptCount: 1, totalCount: 1, weeklyCount: 1 });
  assert(
    root.textContent.includes("Your resume was downloaded. Your original was left untouched."),
    "generic body copy when no job/company known"
  );
  assert(root.querySelector(".success-job-line") === null, "no job line rendered when title/company are absent");
});

await test("claims the panel: hides legacy/idle/detection/loading/review roots", async () => {
  const { root, reviewRoot, legacyRoot, showDownloadSuccessScreen } = await mount();
  reviewRoot.hidden = false;
  legacyRoot.hidden = false;
  showDownloadSuccessScreen({ keptCount: 1, totalCount: 1, weeklyCount: 1 });
  assert(reviewRoot.hidden === true, "review screen hidden once success claims the panel");
  assert(legacyRoot.hidden === true, "legacy stack hidden");
});

await test("Done reloads the panel (the side panel's closest equivalent to close/reopen)", async () => {
  const { root, reloadWasAttempted, showDownloadSuccessScreen } = await mount();
  showDownloadSuccessScreen({ keptCount: 1, totalCount: 1, weeklyCount: 1 });

  const doneBtn = root.querySelector(".success-done-btn");
  assert(doneBtn?.textContent === "Done", "Done button present");
  doneBtn.click();

  assert(await reloadWasAttempted(), "Done triggers a real page reload, not just a UI reset");
});

await test("hideDownloadSuccessScreen clears and hides the root", async () => {
  const { root, showDownloadSuccessScreen, hideDownloadSuccessScreen } = await mount();
  showDownloadSuccessScreen({ keptCount: 1, totalCount: 1, weeklyCount: 1 });
  assert(root.hidden === false, "shown before hide");

  hideDownloadSuccessScreen();
  assert(root.hidden === true, "hidden after hide");
  assert(root.innerHTML === "", "content cleared");
});

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
