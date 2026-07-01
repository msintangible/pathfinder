/**
 * Unit tests for profileApi.importProfile()'s request construction.
 * Mocks chrome.storage + XMLHttpRequest (Node's global FormData is used as-is).
 *
 * Run via: npm test
 */

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }

// --- Mock chrome.storage.local (no stored backend URL -> default is used) ---
global.chrome = {
  storage: { local: { get: async () => ({}) } },
};

// --- Mock XMLHttpRequest: captures the sent FormData, resolves with a canned response ---
let nextResponse = { status: 200, body: {} };
class FakeXHR {
  constructor() {
    this.upload = {};
    this.responseType = "";
  }
  open(method, url) {
    this.method = method;
    this.url = url;
  }
  send(body) {
    this.sentBody = body;
    FakeXHR.lastInstance = this;
    queueMicrotask(() => {
      this.status = nextResponse.status;
      this.response = nextResponse.body;
      this.onload?.();
    });
  }
}
global.XMLHttpRequest = FakeXHR;

const { importProfile } = await import("../src/shared/profileApi.js");

await test("appends linkedin_text when provided", async () => {
  nextResponse = { status: 200, body: {} };
  await importProfile({ linkedin: "https://linkedin.com/in/jane", linkedinText: "Jane Doe, Engineer" });

  const form = FakeXHR.lastInstance.sentBody;
  assert(form.get("linkedin_url") === "https://linkedin.com/in/jane", "linkedin_url present");
  assert(form.get("linkedin_text") === "Jane Doe, Engineer", "linkedin_text present");
});

await test("omits linkedin_text when not provided", async () => {
  nextResponse = { status: 200, body: {} };
  await importProfile({ linkedin: "https://linkedin.com/in/jane" });

  const form = FakeXHR.lastInstance.sentBody;
  assert(form.has("linkedin_text") === false, "linkedin_text omitted");
});

await test("omits linkedin_text when empty string", async () => {
  nextResponse = { status: 200, body: {} };
  await importProfile({ linkedin: "https://linkedin.com/in/jane", linkedinText: "" });

  const form = FakeXHR.lastInstance.sentBody;
  assert(form.has("linkedin_text") === false, "empty linkedin_text omitted");
});

await test("still sends github_url and portfolio_url alongside linkedin_text", async () => {
  nextResponse = { status: 200, body: {} };
  await importProfile({
    linkedin: "https://linkedin.com/in/jane",
    linkedinText: "scraped text",
    github: "https://github.com/jane",
    portfolio: "https://jane.dev",
  });

  const form = FakeXHR.lastInstance.sentBody;
  assert(form.get("github_url") === "https://github.com/jane", "github_url present");
  assert(form.get("portfolio_url") === "https://jane.dev", "portfolio_url present");
});

await test("passes the backend's sources through to the result", async () => {
  const sources = { resume_text: "Jane Doe, Engineer", linkedin_text: null, github_profile: null, github_repositories: [], portfolio_text: null };
  nextResponse = { status: 200, body: { profile: { name: "Jane Doe" }, sources } };

  const result = await importProfile({});

  assert(result.ok === true, "ok");
  assert(result.sources?.resume_text === "Jane Doe, Engineer", "sources passed through");
});

await test("passes the backend's id through as profileId", async () => {
  nextResponse = { status: 200, body: { id: "11111111-1111-1111-1111-111111111111", profile: { name: "Jane Doe" }, sources: {} } };

  const result = await importProfile({});

  assert(result.ok === true, "ok");
  assert(result.profileId === "11111111-1111-1111-1111-111111111111", `profileId passed through: ${result.profileId}`);
});

await test("profileId is null when the backend response has no id", async () => {
  nextResponse = { status: 200, body: { profile: { name: "Jane Doe" }, sources: {} } };

  const result = await importProfile({});

  assert(result.profileId === null, "profileId defaults to null");
});

await test("resolves with ok:false on HTTP error", async () => {
  nextResponse = { status: 500, body: { detail: "boom" } };
  const result = await importProfile({ linkedin: "https://linkedin.com/in/jane" });

  assert(result.ok === false, "not ok");
  assert(result.error === "boom", `error message: ${result.error}`);
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
