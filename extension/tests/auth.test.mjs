/**
 * Unit tests for shared/auth.js's getAuthToken()/clearAuthToken() —
 * the anonymous-identity token cache shared by api.js and profileApi.js.
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

let fetchCalls = 0;
global.fetch = async (url) => {
  fetchCalls++;
  assert(url === "http://localhost:8003/v1/auth/anonymous", `mints via the right endpoint: ${url}`);
  return { ok: true, json: async () => ({ access_token: `token-${fetchCalls}` }) };
};

const { getAuthToken, clearAuthToken } = await import("../src/shared/auth.js");

await test("mints and caches a token on first use", async () => {
  storedLocal = {};
  fetchCalls = 0;

  const token = await getAuthToken("http://localhost:8003");

  assert(token === "token-1", "returns the minted token");
  assert(fetchCalls === 1, "called the anonymous endpoint once");
  assert(storedLocal.authToken === "token-1", "cached the token");
});

await test("returns the cached token without calling fetch again", async () => {
  storedLocal = { authToken: "already-cached" };
  fetchCalls = 0;

  const token = await getAuthToken("http://localhost:8003");

  assert(token === "already-cached", "returns the cached token");
  assert(fetchCalls === 0, "did not call fetch");
});

await test("clearAuthToken removes the cached token so the next call mints a fresh one", async () => {
  storedLocal = { authToken: "stale-token" };
  fetchCalls = 0;

  await clearAuthToken();
  assert(storedLocal.authToken === undefined, "cache cleared");

  const token = await getAuthToken("http://localhost:8003");
  assert(token === "token-1", "mints a fresh token");
  assert(fetchCalls === 1, "called the anonymous endpoint once");
});

await test("throws when the backend rejects the anonymous-token request", async () => {
  storedLocal = {};
  global.fetch = async () => ({ ok: false, status: 500 });

  let threw = false;
  try {
    await getAuthToken("http://localhost:8003");
  } catch {
    threw = true;
  }
  assert(threw, "propagates the failure instead of caching an empty token");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
