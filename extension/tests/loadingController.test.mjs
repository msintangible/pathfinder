/**
 * DOM tests for sidepanel/loading/index.js — Screen 3 (tailoring in
 * progress). The backend has no per-step signal, so driveLoading() paces
 * checkmarks against a schedule; these tests exist mainly to pin down the
 * honesty boundary: pacing may never claim more progress than a real
 * settlement has actually made, and a real settlement always wins over
 * pacing, in both directions (early success, or failure that cuts pacing
 * off immediately).
 *
 * Run with: npm test
 */
import { JSDOM } from "jsdom";
import { Message } from "../src/shared/constants.js";

let pass = 0;
let fail = 0;
async function test(name, fn) {
  try { await fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }
const tick = () => new Promise((r) => setTimeout(r, 0));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

function deferred() {
  let resolve, reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

/** Millisecond-scale stand-in for the real STEPS schedule (600ms/2400ms),
 *  so tests don't spend real wall-clock time waiting on it. Same shape:
 *  2 paced checkmarks, 1 step held for real completion (checkAtMs: null). */
const FAST_STEPS = [
  { label: "Step A", checkAtMs: 10 },
  { label: "Step B", checkAtMs: 25 },
  { label: "Step C", checkAtMs: null },
];

async function mount() {
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="loading-screen-root" hidden></div></body></html>',
    { url: "https://example.com" }
  );
  global.document = dom.window.document;
  const mod = await import(`../src/sidepanel/loading/index.js?bust=${Math.random()}`);
  return { root: document.getElementById("loading-screen-root"), ...mod };
}

function stepEls(root) {
  return [...root.querySelectorAll(".load-step")];
}

await test("shows the loading screen immediately: first step active, rest pending, marked as an estimate", async () => {
  const { root, driveLoading } = await mount();
  const { promise, resolve } = deferred();
  const drive = driveLoading(() => promise, { steps: FAST_STEPS });
  await tick();

  assert(root.hidden === false, "loading screen shown as soon as driveLoading starts");
  const steps = stepEls(root);
  assert(steps.length === 3, "renders all 3 steps");
  assert(steps[0].className.includes("load-step--active"), "first step active immediately");
  assert(steps[1].className.includes("load-step--pending"), "second step still pending");
  assert(steps[2].className.includes("load-step--pending"), "third step still pending");
  assert(root.textContent.includes("Estimated steps"), "caption discloses these are paced, not live status");
  assert(root.textContent.includes(Message.GENERATING), "reuses the existing generating copy");

  resolve("done");
  await drive;
});

await test("paces checkmarks on schedule while the real task is still pending", async () => {
  const { root, driveLoading } = await mount();
  const { promise, resolve } = deferred();
  const drive = driveLoading(() => promise, { steps: FAST_STEPS });

  await wait(15);
  let steps = stepEls(root);
  assert(steps[0].className.includes("load-step--done"), "first step checked off on schedule");
  assert(steps[1].className.includes("load-step--active"), "second step becomes active on schedule");
  assert(steps[2].className.includes("load-step--pending"), "third step untouched so far");

  await wait(20); // past step B's 25ms mark
  steps = stepEls(root);
  assert(steps[1].className.includes("load-step--done"), "second step checked off on schedule");
  assert(steps[2].className.includes("load-step--active"), "third step becomes active once reached");

  resolve("done");
  await drive;
});

await test("the final step is never auto-checked by pacing alone", async () => {
  const { root, driveLoading } = await mount();
  const { promise, resolve } = deferred();
  const drive = driveLoading(() => promise, { steps: FAST_STEPS });

  // Wait well past both paced checkpoints — only a real settlement may
  // check off the last step; the schedule itself must never do it.
  await wait(60);
  const steps = stepEls(root);
  assert(steps[2].className.includes("load-step--active"), "last step still just active (spinner), not done");
  assert(!steps[2].className.includes("load-step--done"), "last step not falsely marked done by pacing");

  resolve("done");
  await drive;
});

await test("a real success jumps straight to done, even ahead of the pacing schedule", async () => {
  const { root, driveLoading } = await mount();
  const { promise, resolve } = deferred();
  const drivePromise = driveLoading(() => promise, { steps: FAST_STEPS });
  await tick();

  resolve({ ats_score: 80 }); // resolves immediately, well before either checkAtMs
  const outcome = await drivePromise;

  assert(outcome.ok === true, "driveLoading reports success");
  assert(outcome.result.ats_score === 80, "resolves with the task's real result");
  const steps = stepEls(root);
  assert(steps.every((el) => el.className.includes("load-step--done")), "all steps shown done once the real result is in, without waiting for pacing");
});

await test("a real failure stops pacing and shows the actual error immediately", async () => {
  const { root, driveLoading } = await mount();
  const { promise, reject } = deferred();
  const drivePromise = driveLoading(() => promise, { steps: FAST_STEPS });
  await tick();

  reject(new Error("HTTP 502: backend down"));
  const outcome = await drivePromise;

  assert(outcome.ok === false, "driveLoading reports failure");
  assert(outcome.error.message === "HTTP 502: backend down", "carries the real error");
  assert(root.textContent.includes(Message.GENERATE_FAILED), "reuses the existing failure copy");
  assert(root.textContent.includes("HTTP 502: backend down"), "shows the real error text, not a generic message");
  assert(root.querySelector(".load-steps") === null, "step list replaced by the error screen, not left half-checked");
});

await test("onRetry renders a Try again button and is called on click, not auto-retried by driveLoading itself", async () => {
  const { root, driveLoading } = await mount();
  const { promise, reject } = deferred();
  let retryCount = 0;
  const drivePromise = driveLoading(() => promise, {
    steps: FAST_STEPS,
    onRetry: () => { retryCount++; },
  });
  await tick();

  reject(new Error("boom"));
  await drivePromise;

  const retryBtn = root.querySelector(".load-retry-btn");
  assert(retryBtn !== null, "retry button rendered on the error screen");
  assert(retryBtn.textContent === "Try again", "retry button labeled clearly");
  assert(retryCount === 0, "driveLoading doesn't call onRetry on its own");

  retryBtn.click();
  assert(retryCount === 1, "onRetry called once on click");
});

await test("without onRetry, the error screen renders no retry button", async () => {
  const { root, driveLoading } = await mount();
  const { promise, reject } = deferred();
  const drivePromise = driveLoading(() => promise, { steps: FAST_STEPS });
  await tick();

  reject(new Error("boom"));
  await drivePromise;

  assert(root.querySelector(".load-retry-btn") === null, "no retry button without an onRetry callback");
});

await test("hideLoadingScreen clears and hides the root", async () => {
  const { root, driveLoading, hideLoadingScreen } = await mount();
  const { promise, resolve } = deferred();
  const drive = driveLoading(() => promise, { steps: FAST_STEPS });
  await tick();
  resolve("done");
  await drive;

  hideLoadingScreen();

  assert(root.hidden === true, "root hidden");
  assert(root.innerHTML === "", "root cleared");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
