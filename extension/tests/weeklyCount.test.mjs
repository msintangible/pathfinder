/**
 * Unit tests for shared/weeklyCount.js — the "applications tailored this
 * week" retention counter (chrome.storage.local, resets Monday 00:00 local).
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
    },
  },
};

const ONE_WEEK_MS = 7 * 24 * 60 * 60 * 1000;

const { loadWeeklyCount, incrementWeeklyCount } = await import("../src/shared/weeklyCount.js");

await test("loadWeeklyCount is 0 when nothing has ever been recorded", async () => {
  storedLocal = {};
  assert((await loadWeeklyCount()) === 0, "starts at 0");
});

await test("incrementWeeklyCount starts a fresh week at 1 and persists it", async () => {
  storedLocal = {};
  const result = await incrementWeeklyCount();
  assert(result === 1, `first increment returns 1, got ${result}`);
  assert((await loadWeeklyCount()) === 1, "persisted count reads back as 1");
});

await test("incrementWeeklyCount accumulates within the same week", async () => {
  storedLocal = {};
  await incrementWeeklyCount();
  await incrementWeeklyCount();
  const third = await incrementWeeklyCount();
  assert(third === 3, `third increment returns 3, got ${third}`);
  assert((await loadWeeklyCount()) === 3, "persisted count reads back as 3");
});

await test("loadWeeklyCount reads back 0 once the stored record is from a past week", async () => {
  storedLocal = { weeklyCount: { count: 5, weekStart: Date.now() - ONE_WEEK_MS * 2 } };
  assert((await loadWeeklyCount()) === 0, "stale week reads as 0, not the leftover count");
});

await test("incrementWeeklyCount starts over at 1 once the stored record is from a past week", async () => {
  storedLocal = { weeklyCount: { count: 5, weekStart: Date.now() - ONE_WEEK_MS * 2 } };
  const result = await incrementWeeklyCount();
  assert(result === 1, `resets to 1 on a new week, got ${result}`);
});

console.log(`\n${pass} passed, ${fail} failed`);
if (fail > 0) process.exit(1);
