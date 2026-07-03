/**
 * DOM tests for src/content/observe.js using jsdom.
 *
 * observe.js is a content script (plain script, no exports) loaded via
 * manifest.json into the same content-script global scope as detect.js,
 * scrape.js, and index.js. Same load trick as the other content-script test
 * files: eval the source via `new Function` and return the functions we
 * want to call, with browser globals (document, location, history, window,
 * MutationObserver) injected as factory parameters.
 *
 * The debounce/hard-cap logic is exercised on a fake clock (injected
 * now/setTimeoutFn/clearTimeoutFn) rather than real timers, so these tests
 * run instantly instead of waiting out real 400ms/3000ms delays. A
 * FakeMutationObserver is used for the same reason — deterministic control
 * over when "a mutation was observed" fires, without depending on jsdom's
 * real (microtask-scheduled) MutationObserver timing. One smoke test at the
 * bottom uses the real jsdom MutationObserver to prove the actual
 * `observer.observe(document.body, { childList: true, subtree: true })`
 * wiring is correct end to end.
 *
 * Run with: npm test
 */

import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(__dirname, "../src/content/observe.js"), "utf8");

/** A fake clock: setTimeoutFn/clearTimeoutFn schedule against a manually-advanced virtual time. */
function makeFakeClock() {
  let time = 0;
  let nextId = 1;
  const timers = new Map(); // id -> { due, fn }
  return {
    now: () => time,
    setTimeoutFn(fn, delay) {
      const id = nextId++;
      timers.set(id, { due: time + delay, fn });
      return id;
    },
    clearTimeoutFn(id) {
      timers.delete(id);
    },
    /** Advance virtual time to `to`, firing any due timers (in due order). */
    advanceTo(to) {
      time = to;
      let firedSomething = true;
      while (firedSomething) {
        firedSomething = false;
        const due = [...timers.entries()].filter(([, t]) => t.due <= time).sort((a, b) => a[1].due - b[1].due);
        if (due.length) {
          const [id, t] = due[0];
          timers.delete(id);
          firedSomething = true;
          t.fn();
        }
      }
    },
    pendingCount: () => timers.size,
  };
}

/** A fake MutationObserver: `.trigger()` simulates a mutation batch being delivered. */
function makeFakeMutationObserverClass() {
  const instances = [];
  class FakeMutationObserver {
    constructor(cb) {
      this.cb = cb;
      this.disconnected = false;
      this.observeArgs = null;
      instances.push(this);
    }
    observe(target, options) {
      this.observeArgs = { target, options };
    }
    disconnect() {
      this.disconnected = true;
    }
    trigger() {
      // Match real MutationObserver semantics: a disconnected observer
      // delivers nothing, even if the underlying DOM keeps mutating.
      if (this.disconnected) return;
      this.cb([]);
    }
  }
  return { FakeMutationObserver, instances };
}

/** Load observe.js against a fresh jsdom window and return its exported functions. */
function makeObserve(html = "<!doctype html><html><body></body></html>", url = "https://example.com/jobs/1") {
  const dom = new JSDOM(html, { url });
  const { window } = dom;
  const { FakeMutationObserver, instances } = makeFakeMutationObserverClass();
  const factory = new Function(
    "document", "location", "history", "window", "MutationObserver",
    `${SRC}\nreturn { startObserving, stopObserving, watchRouteChanges };`
  );
  const api = factory(window.document, window.location, window.history, window, FakeMutationObserver);
  return { ...api, window, mutationInstances: instances };
}

// --- tiny test runner (matches the other content-script test files) --------
let pass = 0;
let fail = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`✓ ${name}`);
    pass++;
  } catch (err) {
    console.log(`✗ ${name}\n    ${err.message}`);
    fail++;
  }
}
async function testAsync(name, fn) {
  try {
    await fn();
    console.log(`✓ ${name}`);
    pass++;
  } catch (err) {
    console.log(`✗ ${name}\n    ${err.message}`);
    fail++;
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

// ---------------------------------------------------------------------------
// Debounce: rescore fires only after mutations settle for 400ms
// ---------------------------------------------------------------------------
test("debounce: rescore does not fire before 400ms of quiet", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let rescoreCount = 0;
  o.startObserving(() => rescoreCount++, clock);

  o.mutationInstances[0].trigger();
  clock.advanceTo(399);
  assert(rescoreCount === 0, `expected 0 rescores before debounce elapses, got ${rescoreCount}`);
});

test("debounce: rescore fires once 400ms after the last mutation", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let rescoreCount = 0;
  o.startObserving(() => rescoreCount++, clock);

  o.mutationInstances[0].trigger();
  clock.advanceTo(400);
  assert(rescoreCount === 1, `expected 1 rescore at the debounce boundary, got ${rescoreCount}`);
});

test("debounce: each new mutation resets the 400ms timer", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let rescoreCount = 0;
  o.startObserving(() => rescoreCount++, clock);

  o.mutationInstances[0].trigger();
  clock.advanceTo(300);
  o.mutationInstances[0].trigger(); // resets the debounce before it would have fired at 400
  clock.advanceTo(600); // 300 (original) + 300 more only reaches 300ms since the reset, not 400
  assert(rescoreCount === 0, `reset debounce should not have fired yet, got ${rescoreCount}`);
  clock.advanceTo(700); // 400ms after the reset at t=300
  assert(rescoreCount === 1, `expected exactly 1 rescore after settling, got ${rescoreCount}`);
});

// ---------------------------------------------------------------------------
// Hard cap: continuous churn (simulated chat widget) cannot run past 3s
// ---------------------------------------------------------------------------
test("hard cap: continuous mutation every 200ms never triggers a rescore and disconnects at the cap", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let rescoreCount = 0;
  o.startObserving(() => rescoreCount++, clock);

  // A "chat widget" that appends a node every 200ms — always resetting the
  // 400ms debounce before it can fire, for well past the 3000ms cap.
  for (let t = 0; t <= 4000; t += 200) {
    clock.advanceTo(t);
    o.mutationInstances[0].trigger();
  }

  assert(rescoreCount === 0, `continuous churn should never let the debounce settle, got ${rescoreCount} rescores`);
  assert(o.mutationInstances[0].disconnected === true, "observer should have disconnected once the 3s cap was exceeded");

  // Further mutations after disconnect must not resurrect scheduling.
  const pendingBefore = clock.pendingCount();
  o.mutationInstances[0].trigger();
  clock.advanceTo(4500);
  assert(rescoreCount === 0, "no rescore should fire after the observer has disconnected");
  assert(clock.pendingCount() <= pendingBefore, "no new timer should be armed after disconnect");
});

test("hard cap: a rescore already in flight past 3s is dropped, not fired", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let rescoreCount = 0;
  o.startObserving(() => rescoreCount++, clock);

  clock.advanceTo(2900);
  o.mutationInstances[0].trigger(); // arms a debounce due at 3300, past the 3000ms cap
  clock.advanceTo(3300); // debounce fires, but capExceeded() is now true
  assert(rescoreCount === 0, "a debounce that resolves past the cap must not call onRescore");
  assert(o.mutationInstances[0].disconnected === true, "observer should self-disconnect once the cap is hit");
});

// ---------------------------------------------------------------------------
// No leak on re-injection: startObserving() called again never stacks observers
// ---------------------------------------------------------------------------
test("re-injection: a second startObserving() call disconnects the first observer", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let firstCount = 0;
  let secondCount = 0;

  o.startObserving(() => firstCount++, clock);
  const first = o.mutationInstances[0];
  assert(first.disconnected === false, "first observer should be live");

  o.startObserving(() => secondCount++, clock);
  assert(o.mutationInstances.length === 2, `expected exactly 2 observers ever constructed, got ${o.mutationInstances.length}`);
  assert(first.disconnected === true, "first observer must be disconnected before the second is created");

  const second = o.mutationInstances[1];
  second.trigger();
  clock.advanceTo(400);
  assert(secondCount === 1, "the new observer's callback should drive rescoring");
  assert(firstCount === 0, "the disconnected observer's callback must never fire");
});

test("stopObserving() is idempotent and safe to call with no active observer", () => {
  const o = makeObserve();
  o.stopObserving(); // no startObserving() call yet — must not throw
});

// ---------------------------------------------------------------------------
// Teardown on tab navigation/close (pagehide backstop for bfcache)
// ---------------------------------------------------------------------------
test("pagehide: disconnects the observer and stops further rescoring", () => {
  const o = makeObserve();
  const clock = makeFakeClock();
  let rescoreCount = 0;
  o.startObserving(() => rescoreCount++, clock);

  o.window.dispatchEvent(new o.window.Event("pagehide"));
  assert(o.mutationInstances[0].disconnected === true, "pagehide should disconnect the live observer");

  // A mutation delivered after teardown must not resurrect rescoring.
  o.mutationInstances[0].trigger();
  clock.advanceTo(400);
  assert(rescoreCount === 0, "no rescore should fire after pagehide teardown");
});

// ---------------------------------------------------------------------------
// SPA navigation: pushState / popstate hook
// ---------------------------------------------------------------------------
test("watchRouteChanges: pushState to a new URL fires onRouteChange once", () => {
  const o = makeObserve("<!doctype html><html><body></body></html>", "https://example.com/jobs/1");
  let count = 0;
  o.watchRouteChanges(() => count++);

  o.window.history.pushState({}, "", "/jobs/2");
  assert(count === 1, `expected 1 route change, got ${count}`);
});

test("watchRouteChanges: pushState to the same URL does not fire", () => {
  const o = makeObserve("<!doctype html><html><body></body></html>", "https://example.com/jobs/1");
  let count = 0;
  o.watchRouteChanges(() => count++);

  o.window.history.pushState({}, "", "/jobs/1");
  assert(count === 0, `expected no route change for an identical URL, got ${count}`);
});

test("watchRouteChanges: popstate to a changed URL fires onRouteChange", () => {
  const o = makeObserve("<!doctype html><html><body></body></html>", "https://example.com/jobs/1");
  let count = 0;
  o.watchRouteChanges(() => count++);

  // Simulate the browser having already updated location for a back/forward
  // navigation before dispatching popstate (real behaviour: history.state
  // changes and location updates synchronously, then popstate fires).
  o.window.history.pushState({}, "", "/jobs/3"); // pushState fires once here
  count = 0; // reset — isolate the popstate assertion
  o.window.history.replaceState({}, "", "/jobs/4"); // replaceState isn't patched, so no fire yet
  o.window.dispatchEvent(new o.window.PopStateEvent("popstate"));
  assert(count === 1, `expected popstate to fire onRouteChange once for the changed URL, got ${count}`);
});

test("watchRouteChanges: original pushState behaviour (URL actually changes) is preserved", () => {
  const o = makeObserve("<!doctype html><html><body></body></html>", "https://example.com/jobs/1");
  o.watchRouteChanges(() => {});
  o.window.history.pushState({}, "", "/jobs/9");
  assert(o.window.location.pathname === "/jobs/9", "pushState should still update location as normal");
});

// ---------------------------------------------------------------------------
// Smoke test: real jsdom MutationObserver wiring (not the fake)
// ---------------------------------------------------------------------------
async function realObserverSmokeTest() {
  const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://example.com/jobs/1" });
  const { window } = dom;
  const factory = new Function(
    "document", "location", "history", "window", "MutationObserver",
    `${SRC}\nreturn { startObserving, stopObserving };`
  );
  const api = factory(window.document, window.location, window.history, window, window.MutationObserver);

  const clock = makeFakeClock();
  let rescoreCount = 0;
  api.startObserving(() => rescoreCount++, clock);

  window.document.body.appendChild(window.document.createElement("div"));
  // Real MutationObserver delivers via the microtask queue — flush past it.
  await new Promise((resolve) => setTimeout(resolve, 0));

  assert(clock.pendingCount() === 1, "a real DOM mutation should have armed the debounce timer");
  clock.advanceTo(400);
  assert(rescoreCount === 1, `expected the real observer to drive a rescore, got ${rescoreCount}`);
  api.stopObserving();
}

await testAsync("real MutationObserver: a live DOM mutation triggers the debounced rescore", realObserverSmokeTest);

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
