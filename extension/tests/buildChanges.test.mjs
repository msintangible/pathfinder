/**
 * Unit tests for sidepanel/review/buildChanges.js — the heuristic matching
 * between report.highlights (LLM-authored, free-text section names) and
 * real before/after text pulled from the locally-stored profile vs the
 * optimized resume. The core rule under test: a highlight that can't be
 * matched with confidence is dropped, never shown with guessed content.
 *
 * Run with: npm test
 */
import { buildChanges } from "../src/sidepanel/review/buildChanges.js";

let pass = 0;
let fail = 0;
function test(name, fn) {
  try { fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

const profile = {
  summary: "Analyst with experience in reporting and business dashboards.",
  skills: ["Excel", "Reporting", "SQL", "Power BI", "Data cleaning"],
  experience: [
    { title: "Data Analyst", company: "Acme Corp", bullets: ["Built reports.", "Maintained dashboards."] },
  ],
};

const optimizedResume = {
  summary: "Data analyst specialising in SQL reporting and Power BI dashboards for stakeholder decisions.",
  skills: ["SQL", "Power BI", "Stakeholder reporting", "Excel", "Data cleaning"],
  experience: [
    { title: "Data Analyst", company: "Acme Corp", bullets: ["Built SQL reports for stakeholders.", "Maintained dashboards."] },
  ],
};

test("matches a summary highlight to real before/after text", () => {
  const rows = buildChanges(profile, optimizedResume, [
    { section: "Professional Summary", summary: "Reworded to match the job's language", impact: "high" },
  ]);
  assert(rows.length === 1, "one row produced");
  assert(rows[0].section === "Professional summary", "normalized section label");
  assert(rows[0].oldText === profile.summary, "real old text, not fabricated");
  assert(rows[0].newText === optimizedResume.summary, "real new text");
  assert(rows[0].reason === "Reworded to match the job's language", "reason passed through");
});

test("matches a skills highlight to joined before/after skill lists", () => {
  const rows = buildChanges(profile, optimizedResume, [
    { section: "Skills", summary: "Reordered to lead with top skills", impact: "medium" },
  ]);
  assert(rows.length === 1, "one row produced");
  assert(rows[0].oldText === profile.skills.join(", "), "real old skills list");
  assert(rows[0].newText === optimizedResume.skills.join(", "), "real new skills list");
});

test("matches an experience highlight by company name in the section text", () => {
  const rows = buildChanges(profile, optimizedResume, [
    { section: "Acme Corp — Data Analyst", summary: "Added SQL keyword to first bullet", impact: "low" },
  ]);
  assert(rows.length === 1, "one row produced");
  assert(rows[0].section === "Data Analyst at Acme Corp", "section label built from matched entry");
  assert(rows[0].oldText === profile.experience[0].bullets.join(" "), "real old bullets");
  assert(rows[0].newText === optimizedResume.experience[0].bullets.join(" "), "real new bullets");
});

test("an unmatchable section is dropped, not shown with guessed content", () => {
  const rows = buildChanges(profile, optimizedResume, [
    { section: "Certifications", summary: "Added a certification", impact: "low" },
  ]);
  assert(rows.length === 0, "no row for a section we can't confidently match");
});

test("a highlight claiming a change where old and new text are identical is dropped", () => {
  const unchanged = { ...optimizedResume, summary: profile.summary };
  const rows = buildChanges(profile, unchanged, [{ section: "Summary", summary: "No real change", impact: "low" }]);
  assert(rows.length === 0, "identical before/after text produces no row");
});

test("multiple highlights across sections all resolve independently", () => {
  const rows = buildChanges(profile, optimizedResume, [
    { section: "Professional Summary", summary: "Reworded", impact: "high" },
    { section: "Skills", summary: "Reordered", impact: "medium" },
    { section: "Unrecognisable free text with no match", summary: "?", impact: "low" },
  ]);
  assert(rows.length === 2, "only the 2 confidently-matched highlights become rows");
});

test("no profile or no optimized resume: returns no rows rather than throwing", () => {
  assert(buildChanges(null, optimizedResume, [{ section: "Summary", summary: "x", impact: "low" }]).length === 0);
  assert(buildChanges(profile, null, [{ section: "Summary", summary: "x", impact: "low" }]).length === 0);
});

test("no highlights: returns no rows", () => {
  assert(buildChanges(profile, optimizedResume, []).length === 0);
  assert(buildChanges(profile, optimizedResume, undefined).length === 0);
});

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
