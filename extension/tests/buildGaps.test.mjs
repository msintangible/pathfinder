/**
 * Unit tests for sidepanel/review/buildGaps.js — the Fit Warning banner's
 * data prep. Core rules under test: the 40% threshold, crediting
 * added_keywords as no-longer-missing (mirrors the backend's own
 * after-tailoring view), and never inventing a group/reason the flat
 * missing_keywords list doesn't support.
 *
 * Run with: npm test
 */
import { buildGaps } from "../src/sidepanel/review/buildGaps.js";

let pass = 0;
let fail = 0;
function test(name, fn) {
  try { fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

test("exactly at the 40% threshold: not a warning (strictly greater than, not equal)", () => {
  const gaps = buildGaps(["a", "b", "c"], ["d", "e"], []); // 2 of 5 = 40%
  assert(gaps === null, "40% exactly does not trigger the banner");
});

test("just over 40%: returns gap data", () => {
  const gaps = buildGaps(["a", "b", "c"], ["d", "e", "f"], []); // 3 of 6 = 50%
  assert(gaps !== null, "50% triggers the banner");
  assert(gaps.total === 6, "total is matched + missing");
  assert(gaps.missing === 3, "missing count is the still-missing count");
});

test("added_keywords are credited as no-longer-missing, not double-counted into total", () => {
  const gaps = buildGaps(["a"], ["b", "c", "d", "e"], ["b", "c"]); // 2 still missing of 5 total = 40%
  assert(gaps === null, "b and c no longer count as missing once added_keywords covers them");
});

test("a keyword can only be credited once even if it somehow appears twice", () => {
  const gaps = buildGaps([], ["x", "y", "z"], ["x"]);
  assert(gaps.total === 3, "total unaffected — 0 matched + 1 added + 2 still-missing");
  assert(gaps.missing === 2, "only x is credited");
});

test("no keywords at all: no banner, no divide-by-zero", () => {
  assert(buildGaps([], [], []) === null, "0/0 never triggers a warning");
});

test("missing/matched/added all default to empty arrays when omitted", () => {
  assert(buildGaps(undefined, undefined, undefined) === null, "no crash, no banner, on missing fields");
});

test("returns a single ungrouped bucket, not fabricated themes", () => {
  const gaps = buildGaps([], ["Tableau", "Python", "AWS"], []);
  assert(gaps.groups.length === 1, "one bucket — the backend gives no theme grouping to split on");
  assert(gaps.groups[0].theme === "Missing requirements", "generic bucket name, not an invented category");
  assert(gaps.groups[0].items.join(",") === "Tableau,Python,AWS", "real keyword text, in the backend's own order");
  assert(gaps.groups[0].reason === null, "no reason — the backend gives none, so none is invented");
});

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
