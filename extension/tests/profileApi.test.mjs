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

// --- Mock chrome.storage.local: no stored backend URL -> default is used;
// a cached auth token means getAuthToken() never needs to call fetch(). ---
let storedLocal = {};
global.chrome = {
  storage: {
    local: {
      get: async (key) => (key in storedLocal ? { [key]: storedLocal[key] } : {}),
      set: async (values) => Object.assign(storedLocal, values),
      remove: async (key) => { delete storedLocal[key]; },
    },
  },
};

// --- Mock fetch: only used by getAuthToken() to mint an anonymous token ---
global.fetch = async () => ({
  ok: true,
  json: async () => ({ access_token: "test-token" }),
});

// --- Mock XMLHttpRequest: captures the sent FormData/headers, resolves with a canned response ---
let nextResponse = { status: 200, body: {} };
class FakeXHR {
  constructor() {
    this.upload = {};
    this.responseType = "";
    this.headers = {};
  }
  open(method, url) {
    this.method = method;
    this.url = url;
  }
  setRequestHeader(name, value) {
    this.headers[name] = value;
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

await test("attaches the cached auth token as a Bearer header", async () => {
  nextResponse = { status: 200, body: {} };
  await importProfile({ linkedin: "https://linkedin.com/in/jane" });

  assert(FakeXHR.lastInstance.headers.Authorization === "Bearer test-token", "Authorization header present");
});

await test("clears the cached token on a 401 so the next call mints a fresh one", async () => {
  nextResponse = { status: 401, body: { detail: "Invalid or expired token" } };
  await importProfile({ linkedin: "https://linkedin.com/in/jane" });

  assert(storedLocal.authToken === undefined, "cached token cleared after 401");
});

// Regression (Mechanism B): a deliberate FastAPI validation message
// (`detail`) is real, safe, product-written copy and must still show
// as-is — this is the "already accidentally okay" half of the fix.
await test("a deliberate validation message (body.detail) is shown verbatim", async () => {
  nextResponse = { status: 400, body: { detail: "Only PDF or DOCX files are supported." } };
  const result = await importProfile({});

  assert(result.ok === false, "not ok");
  assert(result.error === "Only PDF or DOCX files are supported.", `error: ${result.error}`);
});

// The other half: the generic catch-all envelope (backend/app/main.py's
// unhandled_exception_handler) has no useful `detail` — only ever the same
// unhelpful "An unexpected error occurred." — so this path is now logged
// and replaced with plain copy, same as Mechanism A, instead of parroting
// the backend's own generic boilerplate.
await test("a generic 500 envelope (no detail) is replaced with plain copy and logged", async () => {
  nextResponse = {
    status: 500,
    body: { error: { code: "INTERNAL_SERVER_ERROR", message: "An unexpected error occurred.", requestId: "abc-123" } },
  };
  const originalConsoleError = console.error;
  const logged = [];
  console.error = (...args) => logged.push(args.join(" "));

  const result = await importProfile({});
  console.error = originalConsoleError;

  assert(result.ok === false, "not ok");
  assert(result.error === "Try again.", `error: ${result.error}`);
  assert(!result.error.includes("unexpected error"), "never parrots the backend's own generic message");
  assert(logged.some((l) => l.includes("INTERNAL_SERVER_ERROR")), "real detail still logged for debugging");
});

await test("a response with no usable body falls back to plain copy, not a bare HTTP status", async () => {
  nextResponse = { status: 500, body: null };
  const result = await importProfile({});

  assert(result.ok === false, "not ok");
  assert(result.error === "Try again.", `error: ${result.error}`);
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
