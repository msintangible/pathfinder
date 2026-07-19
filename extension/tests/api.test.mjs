/**
 * Unit tests for background/api.js's analyzeJob() and generateResume() —
 * specifically that they attach the anonymous auth token as a Bearer header
 * (backend now requires get_current_user on both routes) and clear the
 * cached token on a 401.
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

// --- Mock chrome.storage.local: backs both the backend-url lookup and the cached auth token ---
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

// --- Mock fetch: routes to either the auth-token mint or a canned response.
// `queue` lets a test script a specific sequence of responses (e.g. 404 then
// restore then retry); when empty, every call falls back to `nextResponse`. ---
let nextResponse = { status: 200, body: {} };
let queue = [];
const requests = [];
global.fetch = async (url, init) => {
  requests.push({ url, init });
  if (url.endsWith("/v1/auth/anonymous")) {
    return { ok: true, json: async () => ({ access_token: "test-token" }) };
  }
  const canned = queue.length ? queue.shift() : nextResponse;
  return {
    ok: canned.status >= 200 && canned.status < 300,
    status: canned.status,
    json: async () => canned.body,
    text: async () => JSON.stringify(canned.body),
  };
};

const { analyzeJob, generateResume } = await import("../src/background/api.js");

await test("analyzeJob attaches the cached auth token as a Bearer header", async () => {
  nextResponse = { status: 200, body: { id: "job-1" } };
  requests.length = 0;

  const result = await analyzeJob({ raw_text: "We are hiring." });

  assert(result.ok === true, "ok");
  const call = requests.find((r) => r.url.endsWith("/v1/jobs/analyze"));
  assert(call.init.headers.Authorization === "Bearer test-token", "Authorization header present");
});

await test("analyzeJob clears the cached token on a 401", async () => {
  nextResponse = { status: 401, body: { detail: "Invalid or expired token" } };

  const result = await analyzeJob({ raw_text: "We are hiring." });

  assert(result.ok === false, "not ok");
  assert(storedLocal.authToken === undefined, "cached token cleared after 401");
});

await test("generateResume attaches the cached auth token as a Bearer header", async () => {
  nextResponse = { status: 200, body: { download_url: "/v1/resumes/r-1/download" } };
  requests.length = 0;

  const result = await generateResume({ user_profile_id: "p-1", job_id: "j-1" });

  assert(result.ok === true, "ok");
  const call = requests.find((r) => r.url.endsWith("/v1/resumes/generate"));
  assert(call.init.headers.Authorization === "Bearer test-token", "Authorization header present");
});

await test("generateResume clears the cached token on a 401", async () => {
  nextResponse = { status: 401, body: { detail: "Invalid or expired token" } };

  const result = await generateResume({ user_profile_id: "p-1", job_id: "j-1" });

  assert(result.ok === false, "not ok");
  assert(storedLocal.authToken === undefined, "cached token cleared after 401");
});

await test("generateResume self-heals a stale profile_id via /v1/profile/restore", async () => {
  storedLocal.profile = { name: "Jane Doe", technical_skills: ["Python"] };
  queue = [
    { status: 404, body: { detail: "Profile not found" } },
    { status: 200, body: { id: "p2", profile: { name: "Jane Doe" } } },
    { status: 200, body: { download_url: "/v1/resumes/r-1/download" } },
  ];
  requests.length = 0;

  const result = await generateResume({ user_profile_id: "stale-id", job_id: "j-1" });

  assert(result.ok === true, "ok after self-heal");
  assert(requests.some((r) => r.url.endsWith("/v1/profile/restore")), "restore endpoint called");
  const retryCall = requests[requests.length - 1];
  assert(retryCall.url.endsWith("/v1/resumes/generate"), "final call is generate");
  assert(JSON.parse(retryCall.init.body).user_profile_id === "p2", "retried with the restored profile id");
  assert(storedLocal.profileId === "p2", "restored profile id persisted to storage");
});

await test("generateResume gives up cleanly when there's no cached profile to restore, shows plain copy", async () => {
  delete storedLocal.profile;
  queue = [{ status: 404, body: { detail: "Profile not found" } }];
  requests.length = 0;

  const result = await generateResume({ user_profile_id: "stale-id", job_id: "j-1" });

  assert(result.ok === false, "not ok");
  assert(result.error === "Couldn't find your profile — try re-importing it.", `error message: ${result.error}`);
  assert(!requests.some((r) => r.url.endsWith("/v1/profile/restore")), "restore not attempted without a cached profile");
});

await test("generateResume: a non-profile 404 doesn't trigger self-heal, and shows plain copy not the raw detail", async () => {
  storedLocal.profile = { name: "Jane Doe" };
  queue = [{ status: 404, body: { detail: "Job not found" } }];
  requests.length = 0;

  const result = await generateResume({ user_profile_id: "p-1", job_id: "bad-job" });

  assert(result.ok === false, "not ok");
  assert(result.error === "Couldn't generate your resume. Try again.", `error message: ${result.error}`);
  assert(!requests.some((r) => r.url.endsWith("/v1/profile/restore")), "restore not attempted for a non-profile 404");
});

// Regression: a real 500 from backend/app/main.py's generic exception
// handler — this exact shape (Gemini quota exhaustion, wrapped in the
// generic INTERNAL_SERVER_ERROR envelope since FastAPI's catch-all always
// returns 500 regardless of the real underlying status) is what leaked
// verbatim into three separate UI files before the fix moved here.
const REAL_BACKEND_500_BODY = JSON.stringify({
  error: { code: "INTERNAL_SERVER_ERROR", message: "An unexpected error occurred.", details: [], requestId: "abc-123" },
});

await test("analyzeJob: a real raw 500 never reaches the caller, and is logged for debugging", async () => {
  nextResponse = { status: 500, body: JSON.parse(REAL_BACKEND_500_BODY) };
  const originalConsoleError = console.error;
  const logged = [];
  console.error = (...args) => logged.push(args.join(" "));

  const result = await analyzeJob({ raw_text: "We are hiring." });
  console.error = originalConsoleError;

  assert(result.ok === false, "not ok");
  assert(result.error === "Couldn't read this job posting. Try again.", `error: ${result.error}`);
  assert(!result.error.includes("HTTP"), "never the raw HTTP status");
  assert(!result.error.includes("{"), "never the raw JSON body");
  assert(logged.some((l) => l.includes("INTERNAL_SERVER_ERROR")), "real detail still logged for debugging");
});

await test("generateResume: a real raw 500 never reaches the caller, and is logged for debugging", async () => {
  nextResponse = { status: 500, body: JSON.parse(REAL_BACKEND_500_BODY) };
  const originalConsoleError = console.error;
  const logged = [];
  console.error = (...args) => logged.push(args.join(" "));

  const result = await generateResume({ user_profile_id: "p-1", job_id: "j-1" });
  console.error = originalConsoleError;

  assert(result.ok === false, "not ok");
  assert(result.error === "Couldn't generate your resume. Try again.", `error: ${result.error}`);
  assert(!result.error.includes("HTTP"), "never the raw HTTP status");
  assert(!result.error.includes("{"), "never the raw JSON body");
  assert(logged.some((l) => l.includes("INTERNAL_SERVER_ERROR")), "real detail still logged for debugging");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
