/**
 * Tests for src/content/index.js — specifically the extension-context-
 * invalidation guard (isExtensionContextValid / reportDetection / rescore /
 * the watchRouteChanges callback).
 *
 * Background: a stale content script (one still running in a tab after the
 * extension itself was reloaded/updated) has `chrome.runtime.id === undefined`
 * forever. Before this guard, every DOM mutation or SPA route change on a
 * page like a LinkedIn feed (which fires both constantly) re-armed the
 * MutationObserver and retried chrome.runtime.sendMessage — each attempt
 * failing the same way, forever, for the rest of that tab's life. These
 * tests reproduce that scenario against a mocked chrome/observe API and
 * assert the pipeline tears itself down permanently instead of retrying.
 *
 * Same load trick as the other content-script test files: eval the source
 * via `new Function`, with chrome/detect/scrapePage/startObserving/
 * watchRouteChanges/stopObserving injected as factory parameters (index.js
 * calls these as bare globals in the real content-script scope, since
 * detect.js/scrape.js/observe.js declare them into the same shared scope —
 * see index.js's own header comment).
 *
 * Run with: npm test
 */

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(__dirname, "../src/content/index.js"), "utf8");

/**
 * Build a fresh index.js instance against mocked dependencies. `runtimeId`
 * seeds chrome.runtime.id; use the returned `setRuntimeId` to flip it later
 * (simulating the extension being reloaded mid-session, same as reality).
 * `sendMessageImpl` lets a test override sendMessage's behaviour (throw
 * synchronously, reject, resolve) to exercise every failure mode Chrome
 * actually produces.
 */
function makeIndex(opts = {}) {
  const { sendMessageImpl } = opts;
  // Destructuring a default (`{ runtimeId = "abc123" } = {}`) treats an
  // explicitly-passed `undefined` the same as "not passed", which would
  // silently mask the exact case these tests need to simulate (chrome.
  // runtime.id genuinely reading undefined) — so check for the key instead.
  let currentId = Object.prototype.hasOwnProperty.call(opts, "runtimeId") ? opts.runtimeId : "abc123";

  const sentMessages = [];
  const chrome = {
    runtime: {
      get id() {
        return currentId;
      },
      sendMessage(msg) {
        sentMessages.push(msg);
        if (sendMessageImpl) return sendMessageImpl(msg);
        return Promise.resolve();
      },
      onMessage: {
        listeners: [],
        addListener(fn) {
          this.listeners.push(fn);
        },
      },
    },
  };

  const detectCalls = [];
  const detect = () => {
    detectCalls.push(1);
    return { isJobPage: true, confidence: 0.9 };
  };

  const scrapePageCalls = [];
  const scrapePage = () => {
    scrapePageCalls.push(1);
    return { text: "job body" };
  };

  const startObservingCalls = [];
  let capturedRescore = null;
  const startObserving = (fn) => {
    startObservingCalls.push(fn);
    capturedRescore = fn;
  };

  let capturedRouteChangeCb = null;
  const watchRouteChanges = (cb) => {
    capturedRouteChangeCb = cb;
  };

  const stopObservingCalls = [];
  const stopObserving = () => {
    stopObservingCalls.push(1);
  };

  const factory = new Function(
    "chrome", "detect", "scrapePage", "startObserving", "watchRouteChanges", "stopObserving",
    `${SRC}\nreturn { reportDetection, rescore, isExtensionContextValid };`
  );
  const api = factory(chrome, detect, scrapePage, startObserving, watchRouteChanges, stopObserving);

  return {
    ...api,
    chrome,
    setRuntimeId: (v) => {
      currentId = v;
    },
    sentMessages,
    detectCalls,
    scrapePageCalls,
    startObservingCalls,
    stopObservingCalls,
    triggerRescore: () => capturedRescore(),
    triggerRouteChange: () => capturedRouteChangeCb(),
  };
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
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

// ---------------------------------------------------------------------------
// isExtensionContextValid: the primitive everything else relies on
// ---------------------------------------------------------------------------
test("isExtensionContextValid: true while chrome.runtime.id is set", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  assert(i.isExtensionContextValid() === true);
});

test("isExtensionContextValid: false once chrome.runtime.id goes undefined", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  i.setRuntimeId(undefined);
  assert(i.isExtensionContextValid() === false);
});

// ---------------------------------------------------------------------------
// reportDetection: on-load call + invalidation guard
// ---------------------------------------------------------------------------
test("on load: reportDetection sends exactly one message when context starts valid", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  assert(i.sentMessages.length === 1, `expected 1 message on load, got ${i.sentMessages.length}`);
  assert(i.sentMessages[0].type === "PAGE_DETECTED");
});

test("on load: reportDetection sends nothing, and never calls detect(), when context starts invalid", () => {
  const i = makeIndex({ runtimeId: undefined });
  assert(i.sentMessages.length === 0, "no message should be sent with an invalid context");
  assert(i.detectCalls.length === 0, "detect() should not run if we already know we can't report it");
});

test("reportDetection: stops sending once the context is invalidated mid-session", () => {
  const i = makeIndex({ runtimeId: "abc123" }); // 1 message from the on-load call
  i.setRuntimeId(undefined);
  i.reportDetection();
  i.reportDetection();
  i.reportDetection();
  assert(i.sentMessages.length === 1, `expected no new messages after invalidation, got ${i.sentMessages.length} total`);
});

test("reportDetection: swallows a synchronous throw from sendMessage (invalidated-context race)", () => {
  const i = makeIndex({
    runtimeId: "abc123",
    sendMessageImpl: () => {
      throw new Error("Extension context invalidated.");
    },
  });
  // The on-load call already exercised the throwing path; calling again must
  // still not propagate.
  assert(() => i.reportDetection()); // no throw = pass; a throw fails the test() wrapper
});

test("reportDetection: swallows a rejected sendMessage promise", () => {
  const i = makeIndex({
    runtimeId: "abc123",
    sendMessageImpl: () => Promise.reject(new Error("Receiving end does not exist.")),
  });
  i.reportDetection(); // must not throw synchronously; rejection is caught internally
});

// ---------------------------------------------------------------------------
// rescore: the debounced MutationObserver callback
// ---------------------------------------------------------------------------
test("rescore: runs the normal pipeline while the context is valid", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  const before = i.sentMessages.length;
  i.triggerRescore();
  assert(i.sentMessages.length === before + 1, "rescore should report detection again");
  assert(i.scrapePageCalls.length === 1, "rescore should re-run the scrape pipeline");
  assert(i.stopObservingCalls.length === 0, "a valid context must never tear down the observer");
});

test("rescore: tears down the observer and skips extraction once the context is invalid", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  i.setRuntimeId(undefined);
  i.triggerRescore();
  assert(i.stopObservingCalls.length === 1, "rescore must disconnect the observer on first sign of invalidation");
  assert(i.scrapePageCalls.length === 0, "scrapePage() is wasted work once we can't report the result — must be skipped");
  assert(i.sentMessages.length === 1, "no additional sendMessage attempt beyond the on-load call");
});

test("rescore: repeated firings after invalidation never re-arm observing and never resend", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  i.setRuntimeId(undefined);
  for (let n = 0; n < 25; n++) i.triggerRescore();
  assert(i.sentMessages.length === 1, `expected only the on-load message, got ${i.sentMessages.length}`);
  assert(i.scrapePageCalls.length === 0, "scrapePage must never run once invalidated");
  assert(i.startObservingCalls.length === 1, "startObserving must never be called again after invalidation");
  assert(i.stopObservingCalls.length === 25, "each firing should still defensively call stopObserving");
});

// ---------------------------------------------------------------------------
// watchRouteChanges callback: this is the exact path that spammed the
// Network tab on LinkedIn — a route change while invalidated must not
// restart the observer.
// ---------------------------------------------------------------------------
test("route change: valid context reports detection again and restarts observing", () => {
  const i = makeIndex({ runtimeId: "abc123" }); // startObserving called once on load
  const before = i.sentMessages.length;
  i.triggerRouteChange();
  assert(i.sentMessages.length === before + 1, "a valid route change should report detection");
  assert(i.startObservingCalls.length === 2, "a valid route change should start a fresh observing window");
});

test("route change: invalid context tears down and does NOT restart observing", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  i.setRuntimeId(undefined);
  i.triggerRouteChange();
  assert(i.sentMessages.length === 1, "no sendMessage attempt on an invalidated route change");
  assert(i.startObservingCalls.length === 1, "startObserving must NOT be called again — this is the fix for the LinkedIn bug");
  assert(i.stopObservingCalls.length === 1, "the observer should be torn down on the invalidated route change");
});

test("adversarial: simulated LinkedIn feed — 50 route changes after invalidation, zero re-arms", () => {
  // Reproduces the exact bug from the screenshot: LinkedIn's feed fires many
  // pushState route changes (opening/closing posts, highlighted updates,
  // comment-box modals) while a stale content script sits in the tab after
  // the extension was reloaded. None of these 50 attempts may ever resend
  // or re-arm the observer.
  const i = makeIndex({ runtimeId: "abc123" });
  i.setRuntimeId(undefined);
  for (let n = 0; n < 50; n++) i.triggerRouteChange();
  assert(i.sentMessages.length === 1, `expected exactly the 1 on-load message, got ${i.sentMessages.length}`);
  assert(i.startObservingCalls.length === 1, `startObserving should never be re-called, got ${i.startObservingCalls.length} calls`);
  assert(i.stopObservingCalls.length === 50, "every invalidated route change should still call stopObserving defensively");
});

test("adversarial: context flips valid -> invalid -> valid mid-session (extension reloaded, then reloaded again) never resends stale-window messages", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  i.setRuntimeId(undefined);
  i.triggerRescore();
  i.triggerRouteChange();
  assert(i.sentMessages.length === 1, "still just the on-load message while invalid");
  assert(i.startObservingCalls.length === 1, "no re-arm while invalid");

  // A brand-new context id (the page's own re-injection scenario doesn't
  // happen without a real reload, but this proves the guard is a live check,
  // not a one-time latch that permanently disables reporting even if
  // chrome.runtime.id were to become valid again).
  i.setRuntimeId("def456");
  i.triggerRouteChange();
  assert(i.sentMessages.length === 2, "a route change with a valid id should report again");
  assert(i.startObservingCalls.length === 2, "a route change with a valid id should restart observing");
});

// ---------------------------------------------------------------------------
// The SCRAPE_PAGE message listener is unrelated to the invalidation guard
// (it only ever runs if this context is alive enough to receive a message
// in the first place) — a quick regression check that it's untouched.
// ---------------------------------------------------------------------------
test("SCRAPE_PAGE listener still responds synchronously with the scrape result", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  let response;
  const returnValue = i.chrome.runtime.onMessage.listeners[0](
    { type: "SCRAPE_PAGE" },
    {},
    (r) => (response = r)
  );
  assert(returnValue === false, "SCRAPE_PAGE is synchronous — must not keep the message channel open");
  assert(response && response.text === "job body", "should respond with scrapePage()'s result");
});

test("unrelated message types: listener responds false and does not scrape", () => {
  const i = makeIndex({ runtimeId: "abc123" });
  const scrapeCallsBefore = i.scrapePageCalls.length;
  const returnValue = i.chrome.runtime.onMessage.listeners[0]({ type: "SOMETHING_ELSE" }, {}, () => {});
  assert(returnValue === false);
  assert(i.scrapePageCalls.length === scrapeCallsBefore, "an unrelated message must not trigger a scrape");
});

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
