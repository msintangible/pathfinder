/**
 * Pathfinder side-panel UI controller (Phase 2).
 *
 * The side panel is the user-facing surface (TDD 5.3). It:
 *   - shows the active tab's URL,
 *   - automatically scrapes all visible page text into JSON and displays it
 *     (no button — runs on open, on tab switch, and when a page finishes
 *     loading),
 *   - reports backend connectivity (via the service worker).
 *
 * Connectivity goes through the service worker (TDD 6.1). The raw page
 * scrape is a pure DOM read, so the panel asks the content script for it
 * directly via chrome.tabs.sendMessage.
 *
 * NOTE: the detection badge is now owned by the ES module detection/index.js
 * (mounted into #detection-root), and the Job Analysis button by
 * job-analysis/index.js (mounted into #job-analysis-root).
 */

/**
 * Debug-only UI: Backend card, Scraped text (JSON) card, and the phase
 * footer. Off by default; flip to true locally when debugging scrape or
 * backend behaviour.
 */
const DEBUG_MODE = false;

const pageUrlEl = document.getElementById("page-url");
const scrapeStatusEl = document.getElementById("scrape-status");
const scrapeJsonEl = document.getElementById("scrape-json");
const copyJsonBtn = document.getElementById("copy-json");
const healthEl = document.getElementById("health");
const checkHealthBtn = document.getElementById("check-health");
const backendUrlInput = document.getElementById("backend-url");

// NOTE: the "Your Profile" section is now owned by the ES module
// profile/index.js (mounted into #profile-root). Profile logic lives there.

const DEFAULT_BACKEND_URL = "http://localhost:8003";

// Remove debug-only elements from the DOM entirely (not just hidden) so they
// never render when DEBUG_MODE is off.
if (!DEBUG_MODE) {
  document.querySelector(".footer")?.remove();
  healthEl.closest(".card")?.remove();
  scrapeJsonEl.closest(".card")?.remove();
}

/** Most recent scrape JSON string, for the Copy button. */
let lastScrapeJson = "";

/** Return the active tab (or null). */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

/** Helper: render a coloured status badge into a container. */
function setBadge(container, text, variant) {
  container.innerHTML = "";
  const span = document.createElement("span");
  span.className = `badge badge--${variant}`;
  span.textContent = text;
  container.appendChild(span);
}

// ---------------------------------------------------------------------------
// Automatic page scrape
// ---------------------------------------------------------------------------

/** Scrape the active tab's text and render the URL + JSON. Runs automatically. */
async function scrapeActivePage() {
  const tab = await getActiveTab();
  if (!tab) {
    showScrapeStatus("No active tab.", true);
    return;
  }

  let data;
  try {
    // frameId: 0 pins this to the top-level frame. all_frames: true means
    // iframe-embedded ATS content (Lever, Workday) now also runs detect.js,
    // but broadcasting SCRAPE_PAGE to every frame with no frameId would
    // return an arbitrary single frame's response — pinning keeps today's
    // deterministic main-frame extraction. Per-frame scrape merging is a
    // separate, larger change (see the scraping system review, §9).
    data = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE_PAGE" }, { frameId: 0 });
  } catch {
    // Content script not present (e.g. chrome:// pages, or tab opened before
    // the extension loaded). Show the tab URL we do have, and guide the user.
    renderUrl(tab.url || "");
    showScrapeStatus("Can't read this page. Reload the tab and reopen.", true);
    scrapeJsonEl.hidden = true;
    copyJsonBtn.hidden = true;
    return;
  }

  if (!data) {
    showScrapeStatus("No data returned from the page.", true);
    return;
  }

  renderUrl(data.url);
  renderScrapeJson(data);
}

/** Show the current page URL as a clickable link. */
function renderUrl(url) {
  if (!url) {
    pageUrlEl.textContent = "";
    pageUrlEl.removeAttribute("href");
    return;
  }
  pageUrlEl.textContent = url;
  pageUrlEl.href = url;
}

/** Pretty-print the scrape result as JSON in the panel. */
function renderScrapeJson(data) {
  lastScrapeJson = JSON.stringify(data, null, 2);
  scrapeJsonEl.textContent = lastScrapeJson;
  scrapeJsonEl.hidden = false;
  copyJsonBtn.hidden = false;

  const note = data.truncated
    ? `Scraped ${data.length} chars (truncated for display).`
    : `Scraped ${data.length} chars.`;
  showScrapeStatus(note, false);
}

/** Show a status line in the scrape card. */
function showScrapeStatus(text, isError) {
  scrapeStatusEl.textContent = text;
  scrapeStatusEl.className = isError ? "status status--err" : "status";
  scrapeStatusEl.hidden = false;
}

/** Copy the current scrape JSON to the clipboard. */
async function copyJson() {
  if (!lastScrapeJson) return;
  try {
    await navigator.clipboard.writeText(lastScrapeJson);
    copyJsonBtn.textContent = "Copied";
    setTimeout(() => (copyJsonBtn.textContent = "Copy"), 1500);
  } catch {
    copyJsonBtn.textContent = "Copy failed";
  }
}

// ---------------------------------------------------------------------------
// Backend connectivity
// ---------------------------------------------------------------------------

/** Trigger a backend health check via the service worker. */
async function checkHealth() {
  checkHealthBtn.disabled = true;
  setBadge(healthEl, "Checking…", "neutral");

  const res = await chrome.runtime.sendMessage({ type: "HEALTH_CHECK" });

  if (res?.ok) {
    const v = res.data?.version ? ` (v${res.data.version})` : "";
    setBadge(healthEl, `Connected${v}`, "ok");
  } else {
    setBadge(healthEl, res?.error || "Unreachable", "err");
  }
  checkHealthBtn.disabled = false;
}

/** Load the saved backend URL into the input. */
async function loadBackendUrl() {
  const { backendUrl } = await chrome.storage.local.get("backendUrl");
  backendUrlInput.value = backendUrl || DEFAULT_BACKEND_URL;
}

/** Persist the backend URL when the user edits it, then re-check health. */
async function saveBackendUrl() {
  const value = backendUrlInput.value.trim();
  await chrome.storage.local.set({ backendUrl: value || DEFAULT_BACKEND_URL });
  checkHealth();
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

/** Refresh everything tied to the active tab. */
function refreshForActiveTab() {
  scrapeActivePage();
}

checkHealthBtn.addEventListener("click", checkHealth);
backendUrlInput.addEventListener("change", saveBackendUrl);
copyJsonBtn.addEventListener("click", copyJson);

// Auto-refresh when the user switches tabs, a page finishes loading, or an
// SPA route change updates the URL without a full navigation (History API
// pushState — changeInfo.status never re-enters "complete" for that case,
// only changeInfo.url is set, so both are checked).
chrome.tabs.onActivated.addListener(refreshForActiveTab);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.status === "complete" || changeInfo.url)) {
    refreshForActiveTab();
  }
});

// Initial render.
loadBackendUrl();
if (DEBUG_MODE) checkHealth();
refreshForActiveTab();
