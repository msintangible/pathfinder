/**
 * Content script entry point.
 *
 * Responsibilities (TDD 6.1):
 *   - Detect whether the current page is a job posting and report to the
 *     service worker (which owns badge state and storage).
 *   - Respond to SCRAPE_PAGE requests from the side panel.
 *   - Re-detect on DOM growth and SPA route changes (observe.js) so the
 *     badge doesn't go stale on async-rendered or client-side-navigated
 *     job pages — see the scraping system review §3/§6.
 *
 * Content scripts are deliberately thin: they sense and respond, nothing more.
 * All network I/O and storage go through the service worker.
 */

// `chrome.runtime.id` reads undefined the instant this content script's
// extension context is invalidated (e.g. the extension reloaded/updated
// while this tab stayed open). Once that happens the script is a
// permanent zombie for the rest of this page's life — every future
// sendMessage attempt is guaranteed to fail the same way — so callers
// check this and tear the observer pipeline down for good instead of
// retrying forever on every DOM mutation or SPA route change.
function isExtensionContextValid() {
  return !!chrome.runtime?.id;
}

function reportDetection() {
  if (!isExtensionContextValid()) return;
  try {
    chrome.runtime
      .sendMessage({ type: "PAGE_DETECTED", payload: detect() })
      .catch(() => {
        // Service worker may be asleep or the context invalidated on fast navigation.
        // The side panel re-requests detection when it opens, so this is non-fatal.
      });
  } catch {
    // Synchronous throw: the context was invalidated between the check
    // above and this call. Non-fatal for the same reason as the .catch().
  }
}

function rescore() {
  if (!isExtensionContextValid()) {
    stopObserving();
    return;
  }
  reportDetection();
  // Re-run the extraction pipeline too, discarding the result: scrapePage()
  // already recomputes fresh from the live DOM on every on-demand SCRAPE_PAGE
  // call, so there's nothing to cache here. This keeps the debounced trigger
  // exercising both pipelines uniformly (an extraction-path error surfaces
  // immediately rather than only on the next side-panel request).
  scrapePage();
}

// Run detection immediately on injection.
reportDetection();

// Re-score on DOM growth (async/SPA-rendered content) and on SPA route
// changes (a fresh URL gets its own debounced observation window).
startObserving(rescore);
watchRouteChanges(() => {
  if (!isExtensionContextValid()) {
    stopObserving();
    return;
  }
  reportDetection();
  startObserving(rescore);
});

// Respond to explicit scrape requests from the side panel.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "SCRAPE_PAGE") {
    sendResponse(scrapePage());
    return false; // synchronous response — no need to keep the channel open
  }
  return false;
});
