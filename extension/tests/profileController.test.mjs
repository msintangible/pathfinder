/**
 * DOM tests for sidepanel/profile/index.js — the profile section is import-only:
 * no saved profile shows the import form; a saved profile shows the name, a
 * short (<=3 line) read-only summary, and a per-source verification section
 * (CV / LinkedIn / GitHub / Portfolio) — not a full editable card, and no
 * manual-entry escape hatch.
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

/** Fresh jsdom + chrome mock, imports index.js (module cache busted per call), returns #profile-root. */
async function mountController(storedProfile, storedSources) {
  const dom = new JSDOM('<!doctype html><html><body><div id="profile-root"></div></body></html>', {
    url: "https://example.com",
  });
  global.document = dom.window.document;
  global.chrome = {
    storage: {
      local: {
        get: async (key) => {
          if (key === "profile") return storedProfile ? { profile: storedProfile } : {};
          if (key === "sources") return storedSources ? { sources: storedSources } : {};
          return {};
        },
        set: async () => {},
      },
    },
    tabs: { query: async () => [], sendMessage: async () => null },
  };

  await import(`../src/sidepanel/profile/index.js?bust=${Math.random()}`);
  await tick();
  await tick();

  return document.getElementById("profile-root");
}

await test("no saved profile shows the import form", async () => {
  const root = await mountController(null);

  assert(root.querySelector('[data-role="import"]') !== null, "import button present");
  assert(root.querySelector('[data-role="manual"]') === null, "no manual-entry button");
});

await test("saved profile shows the name and a short summary", async () => {
  const root = await mountController({
    name: "Jane Doe",
    headline: "Senior Backend Engineer",
    skills: ["Python", "AWS", "Docker", "FastAPI", "PostgreSQL", "Redis"],
    experience: [{ title: "Senior Engineer", company: "Acme Corp" }],
  });

  assert(root.textContent.includes("Profile saved"), "status message shown");
  assert(root.textContent.includes("Jane Doe"), "name should be displayed");
  assert(root.textContent.includes("Senior Backend Engineer"), "headline should be displayed");
  assert(root.textContent.includes("Python"), "skills summary should be displayed");
  assert(root.textContent.includes("+1 more"), "skills summary should cap and count the rest");
  assert(root.textContent.includes("Senior Engineer at Acme Corp"), "most recent role should be displayed");
  assert(root.querySelectorAll(".pf-summary-line").length <= 3, "at most 3 summary lines");
  assert(root.querySelector('[data-role="import"]') === null, "no import form shown when already saved");
});

await test("saved profile with minimal data shows only the name, no crash", async () => {
  const root = await mountController({ name: "Jane Doe", skills: [], experience: [] });

  assert(root.textContent.includes("Jane Doe"), "name shown");
  assert(root.querySelectorAll(".pf-summary-line").length === 0, "no summary lines when there's nothing to say");
});

await test("saved profile still offers a re-import path", async () => {
  const root = await mountController({ name: "Jane Doe" });

  const reimport = Array.from(root.querySelectorAll("button")).find((b) => b.textContent.includes("Re-import"));
  assert(reimport, "re-import button present");
});

await test("shows what was found per source: CV, LinkedIn, GitHub", async () => {
  const root = await mountController(
    { name: "Jane Doe" },
    {
      resume_text: "Jane Doe. Senior Backend Engineer with 6 years of Python experience.",
      linkedin_text: "Jane Doe · Senior Engineer at Acme",
      github_profile: "Backend engineer, open source contributor",
      github_repositories: [{ name: "pathfinder" }, { name: "widget-lib" }],
      portfolio_text: null,
    }
  );

  const rows = Array.from(root.querySelectorAll(".pf-source-line")).map((el) => el.textContent);
  assert(rows.some((t) => t.startsWith("CV:") && t.includes("Senior Backend Engineer")), `CV row: ${rows}`);
  assert(rows.some((t) => t.startsWith("LinkedIn:") && t.includes("Senior Engineer at Acme")), `LinkedIn row: ${rows}`);
  assert(rows.some((t) => t.startsWith("GitHub:") && t.includes("pathfinder") && t.includes("2 repos")), `GitHub row: ${rows}`);
  assert(rows.some((t) => t.startsWith("Portfolio:") && t.includes("not provided")), `Portfolio row: ${rows}`);
});

await test("no sources data at all renders no verification section", async () => {
  const root = await mountController({ name: "Jane Doe" }, null);

  assert(root.querySelectorAll(".pf-source-line").length === 0, "no source rows without sources data");
  assert(root.querySelector(".pf-sources-heading") === null, "no heading either");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
