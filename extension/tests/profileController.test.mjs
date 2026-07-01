/**
 * DOM tests for sidepanel/profile/index.js — the profile section is import-only:
 * no saved profile shows the import form, a saved profile shows only a status
 * message (never the profile data itself), and there's no manual-entry escape hatch.
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
async function mountController(storedProfile) {
  const dom = new JSDOM('<!doctype html><html><body><div id="profile-root"></div></body></html>', {
    url: "https://example.com",
  });
  global.document = dom.window.document;
  global.chrome = {
    storage: {
      local: {
        get: async () => (storedProfile ? { profile: storedProfile } : {}),
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

await test("saved profile shows only a status message, never the profile data", async () => {
  const root = await mountController({ name: "Jane Doe", skills: ["Python"], email: "jane@example.com" });

  assert(root.textContent.includes("Profile saved"), "status message shown");
  assert(!root.textContent.includes("Jane Doe"), "name must not be displayed");
  assert(!root.textContent.includes("Python"), "skills must not be displayed");
  assert(root.querySelector('[data-role="import"]') === null, "no import form shown when already saved");
});

await test("saved profile still offers a re-import path", async () => {
  const root = await mountController({ name: "Jane Doe" });

  const reimport = Array.from(root.querySelectorAll("button")).find((b) => b.textContent.includes("Re-import"));
  assert(reimport, "re-import button present");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
