/**
 * MutationObserver + SPA-navigation watching.
 *
 * detect.js and scrape.js are pure/side-effect-free by design (see their own
 * header comments). This file is deliberately where the *statefulness* the
 * scraping system review (§6) calls out lives instead: content_scripts are
 * otherwise pure snapshots-at-injection-time, so re-scoring on DOM changes
 * needs a timer + an observer handle that persist across calls, which can't
 * live in a pure function.
 *
 * Two concerns, both driven by the same guard (`stopObserving` before any new
 * `startObserving`) so a caller can never end up with two live observers:
 *
 *   1. startObserving(onRescore) — debounced MutationObserver. Fires
 *      `onRescore` 400ms after the last DOM mutation settles, so async/SPA
 *      content that renders after document_idle still gets detected. Hard
 *      capped at 3s of total observation so a page with continuous
 *      background churn (chat widgets, ad refreshes, analytics beacons) can't
 *      keep it running forever.
 *
 *   2. watchRouteChanges(onRouteChange) — patches history.pushState and
 *      listens for popstate, so SPA client-side navigation (LinkedIn Jobs,
 *      embedded SPA careers sites) re-triggers detection without a full
 *      document reload.
 */

const MUTATION_DEBOUNCE_MS = 400;
const MUTATION_MAX_OBSERVE_MS = 3000;

let observer = null;
let debounceTimer = null;
let observeStartedAt = 0;

/** Disconnect any live observer and clear any pending debounce timer. Idempotent. */
function stopObserving(clearTimeoutFn = clearTimeout) {
  if (debounceTimer !== null) {
    clearTimeoutFn(debounceTimer);
    debounceTimer = null;
  }
  if (observer) {
    observer.disconnect();
    observer = null;
  }
}

/**
 * Start a fresh, debounced MutationObserver on document.body, calling
 * `onRescore` after DOM mutations settle. Always tears down any prior
 * observer first — the only guard against stacked observers when this is
 * called again after an SPA route change (see watchRouteChanges below).
 *
 * `now`/`setTimeoutFn`/`clearTimeoutFn` are injectable so tests can run the
 * debounce/cap logic on a fake clock instead of waiting on real timers.
 */
function startObserving(
  onRescore,
  { now = Date.now, setTimeoutFn = setTimeout, clearTimeoutFn = clearTimeout } = {}
) {
  stopObserving(clearTimeoutFn);
  observeStartedAt = now();

  const capExceeded = () => now() - observeStartedAt >= MUTATION_MAX_OBSERVE_MS;

  observer = new MutationObserver(() => {
    if (capExceeded()) {
      stopObserving(clearTimeoutFn);
      return;
    }
    if (debounceTimer !== null) clearTimeoutFn(debounceTimer);
    debounceTimer = setTimeoutFn(() => {
      debounceTimer = null;
      if (capExceeded()) {
        stopObserving(clearTimeoutFn);
        return;
      }
      onRescore();
    }, MUTATION_DEBOUNCE_MS);
  });

  observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Patch history.pushState and listen for popstate so SPA route changes call
 * `onRouteChange`. Only fires on an actual URL change (guards pushState
 * calls that don't change location.href, and double-firing when both the
 * patched pushState and a popstate land for the same navigation).
 *
 * Patching pushState from a content script only intercepts calls made
 * through this same wrapped reference — if the page's own router grabbed a
 * reference to the native history.pushState before this script's
 * document_idle injection ran, this patch never sees its navigations. The
 * popstate listener is the safety net, though it misses forward navigations
 * that don't emit popstate (see the scraping system review §6).
 */
function watchRouteChanges(onRouteChange) {
  let lastUrl = location.href;

  function handleUrlChange() {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    onRouteChange();
  }

  const originalPushState = history.pushState;
  history.pushState = function (...args) {
    originalPushState.apply(this, args);
    handleUrlChange();
  };

  window.addEventListener("popstate", handleUrlChange);
}

// Defensive teardown for bfcache-frozen pages: a real full-document
// navigation destroys this script's JS realm (and the observer with it)
// regardless, but a page merely frozen into the back/forward cache is not
// destroyed, so this is the backstop the review's §6 teardown requirement
// calls for. Registered once, at load, like the rest of this file's wiring.
window.addEventListener("pagehide", () => stopObserving());
