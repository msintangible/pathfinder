/**
 * Content script entry point.
 *
 * Responsibilities (TDD 6.1):
 *   - Detect whether the current page is a job posting and report to the
 *     service worker (which owns badge state and storage).
 *   - Respond to SCRAPE_PAGE requests from the side panel.
 *
 * Content scripts are deliberately thin: they sense and respond, nothing more.
 * All network I/O and storage go through the service worker.
 */

// Run detection immediately and report to the service worker.
chrome.runtime
  .sendMessage({ type: "PAGE_DETECTED", payload: detect() })
  .catch(() => {
    // Service worker may be asleep or the context invalidated on fast navigation.
    // The side panel re-requests detection when it opens, so this is non-fatal.
  });

// Respond to explicit scrape requests from the side panel.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "SCRAPE_PAGE") {
    sendResponse(scrapePage());
    return false; // synchronous response — no need to keep the channel open
  }
  return false;
});
