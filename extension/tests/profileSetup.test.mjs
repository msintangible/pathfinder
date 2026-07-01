/**
 * DOM tests for ProfileSetup.js's "Import profile" enable/disable logic and
 * the removal of the manual-entry escape hatch.
 *
 * Run with: npm test
 */
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://example.com" });
global.document = dom.window.document;
global.chrome = {
  tabs: {
    query: async () => [{ id: 1, url: "https://linkedin.com/in/jane" }],
    sendMessage: async () => ({ text: "Jane Doe, Senior Engineer" }),
  },
};

const { createProfileSetup } = await import("../src/sidepanel/profile/ProfileSetup.js");

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

function setup() {
  return createProfileSetup({ onImported: () => {} }).element;
}

await test("import button starts disabled", () => {
  const el = setup();
  const importBtn = el.querySelector('[data-role="import"]');
  assert(importBtn.disabled === true, "should start disabled");
});

await test("entering a GitHub URL enables import without a CV", () => {
  const el = setup();
  const importBtn = el.querySelector('[data-role="import"]');
  const githubInput = el.querySelector('[data-url="github"]');

  githubInput.value = "https://github.com/jane";
  githubInput.dispatchEvent(new dom.window.Event("input"));

  assert(importBtn.disabled === false, "should enable once a URL is entered");
});

await test("clearing all URLs re-disables import", () => {
  const el = setup();
  const importBtn = el.querySelector('[data-role="import"]');
  const githubInput = el.querySelector('[data-url="github"]');

  githubInput.value = "https://github.com/jane";
  githubInput.dispatchEvent(new dom.window.Event("input"));
  assert(importBtn.disabled === false, "enabled after entering");

  githubInput.value = "";
  githubInput.dispatchEvent(new dom.window.Event("input"));
  assert(importBtn.disabled === true, "disabled again after clearing");
});

await test("scraping the open LinkedIn tab enables import", async () => {
  const el = setup();
  const importBtn = el.querySelector('[data-role="import"]');
  const scrapeBtn = el.querySelector('[data-role="scrape-linkedin"]');

  scrapeBtn.dispatchEvent(new dom.window.Event("click"));
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert(importBtn.disabled === false, "should enable after a successful scrape");
});

await test("no manual-entry escape hatch remains", () => {
  const el = setup();
  assert(el.querySelector('[data-role="manual"]') === null, "manual button should not exist");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
