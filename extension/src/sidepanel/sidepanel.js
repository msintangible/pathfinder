/**
 * Pathfinder side-panel UI controller (Phase 2).
 *
 * The side panel is the user-facing surface (TDD 5.3). It:
 *   - shows the active tab's job-detection result and URL,
 *   - automatically scrapes all visible page text into JSON and displays it
 *     (no button — runs on open, on tab switch, and when a page finishes
 *     loading),
 *   - reports backend connectivity (via the service worker).
 *
 * Detection and connectivity go through the service worker (TDD 6.1). The raw
 * page scrape is a pure DOM read, so the panel asks the content script for it
 * directly via chrome.tabs.sendMessage.
 */

const detectionEl = document.getElementById("detection");
const signalsEl = document.getElementById("signals");
const pageUrlEl = document.getElementById("page-url");
const scrapeStatusEl = document.getElementById("scrape-status");
const scrapeJsonEl = document.getElementById("scrape-json");
const copyJsonBtn = document.getElementById("copy-json");
const healthEl = document.getElementById("health");
const checkHealthBtn = document.getElementById("check-health");
const backendUrlInput = document.getElementById("backend-url");
const analyseJobBtn = document.getElementById("analyse-job");
const analysisStatusEl = document.getElementById("analysis-status");
const analysisJsonEl = document.getElementById("analysis-json");

// NOTE: the "Your Profile" section is now owned by the ES module
// profile/index.js (mounted into #profile-root). Profile logic lives there.

const DEFAULT_BACKEND_URL = "http://localhost:8003";

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
// Detection
// ---------------------------------------------------------------------------

/** Ask the service worker for the active tab's detection result and render it. */
async function loadDetection() {
  const tab = await getActiveTab();
  if (!tab) {
    setBadge(detectionEl, "No active tab", "neutral");
    return;
  }

  const res = await chrome.runtime.sendMessage({
    type: "GET_DETECTION",
    payload: { tabId: tab.id },
  });
  const detection = res?.detection;

  if (!detection) {
    setBadge(detectionEl, "Not analysed", "neutral");
    signalsEl.hidden = true;
    return;
  }

  if (detection.isJobPage) {
    const pct = Math.round(detection.confidence * 100);
    setBadge(detectionEl, `Job page (${pct}%)`, "ok");
  } else {
    setBadge(detectionEl, "Not a job page", "warn");
  }

  renderSignals(detection.signals);
}

/** Render the individual Tier-1/Tier-2 detection signals. */
function renderSignals(signals) {
  if (!signals) {
    signalsEl.hidden = true;
    return;
  }
  const labels = {
    urlMatch: "Known ATS URL",
    jsonLd: "JobPosting data",
    applicationForm: "Application form",
    jobKeywords: "Job keywords",
  };
  signalsEl.innerHTML = "";
  for (const [key, label] of Object.entries(labels)) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = signals[key] ? "✓" : "—";
    signalsEl.append(dt, dd);
  }
  signalsEl.hidden = false;
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
// Job Analysis
// ---------------------------------------------------------------------------

/** Show a status line in the analysis card. */
function showAnalysisStatus(text, isError) {
  analysisStatusEl.textContent = text;
  analysisStatusEl.className = isError ? "status status--err" : "status";
  analysisStatusEl.hidden = false;
}

/**
 * Scrape the active tab, send the text to the service worker for analysis,
 * and display the structured JSON response.
 */
async function analyseJob() {
  analyseJobBtn.disabled = true;
  analysisJsonEl.hidden = true;
  showAnalysisStatus("Scraping page…", false);

  const tab = await getActiveTab();
  if (!tab) {
    showAnalysisStatus("No active tab.", true);
    analyseJobBtn.disabled = false;
    return;
  }

  let scrape;
  try {
    // frameId: 0 — see the comment in scrapeActivePage() above.
    scrape = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE_PAGE" }, { frameId: 0 });
  } catch {
    showAnalysisStatus("Can't read this page — reload the tab and try again.", true);
    analyseJobBtn.disabled = false;
    return;
  }

  if (!scrape?.text) {
    showAnalysisStatus("No text scraped from this page.", true);
    analyseJobBtn.disabled = false;
    return;
  }

  showAnalysisStatus(`Sending ${scrape.text.length} chars to backend…`, false);

  const res = await chrome.runtime.sendMessage({
    type: "ANALYZE_JOB",
    payload: { raw_text: scrape.text, url: scrape.url },
  });

  if (res?.ok) {
    showAnalysisStatus("Analysis complete.", false);
    analysisJsonEl.textContent = JSON.stringify(res.data, null, 2);
    analysisJsonEl.hidden = false;

    // Persist the job id for this tab so the Optimize CV card can find it,
    // and drop any resume already generated for a previous analysis of
    // this tab so stale results don't linger under a new job.
    await chrome.runtime.sendMessage({
      type: "SAVE_JOB_ANALYSIS",
      payload: { tabId: tab.id, id: res.data.id, title: res.data.title, company: res.data.company, url: scrape.url },
    });
    await chrome.runtime.sendMessage({
      type: "SAVE_RESUME_RESULT",
      payload: { tabId: tab.id, data: null },
    });
  } else {
    showAnalysisStatus(res?.error || "Analysis failed.", true);
  }

  analyseJobBtn.disabled = false;
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

/** Refresh everything tied to the active tab. */
function refreshForActiveTab() {
  loadDetection();
  scrapeActivePage();
}

checkHealthBtn.addEventListener("click", checkHealth);
backendUrlInput.addEventListener("change", saveBackendUrl);
copyJsonBtn.addEventListener("click", copyJson);
analyseJobBtn.addEventListener("click", analyseJob);

// Auto-refresh when the user switches tabs or a page finishes loading.
chrome.tabs.onActivated.addListener(refreshForActiveTab);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) {
    refreshForActiveTab();
  }
});

// Initial render.
loadBackendUrl();
checkHealth();
refreshForActiveTab();
