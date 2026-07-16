/**
 * Detection controller — owns the "Current page" job-detection badge and,
 * in debug builds, the Tier-1/Tier-2 signal breakdown underneath it.
 *
 * Detection goes through the service worker (TDD 6.1) via GET_DETECTION,
 * re-run whenever the active tab changes or finishes loading.
 */

/** Debug-only: the signals <dl>. Off by default, same as sidepanel.js. */
const DEBUG_MODE = false;

const root = document.getElementById("detection-root");

/** Return the active tab (or null). */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

function badge(text, variant) {
  const span = document.createElement("span");
  span.className = `badge badge--${variant}`;
  span.textContent = text;
  return span;
}

/** The individual Tier-1/Tier-2 detection signals. */
function signalsList(signals) {
  const labels = {
    urlMatch: "Known ATS URL",
    jsonLd: "JobPosting data",
    applicationForm: "Application form",
    jobKeywords: "Job keywords",
  };
  const dl = document.createElement("dl");
  dl.className = "signals";
  for (const [key, label] of Object.entries(labels)) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = signals[key] ? "✓" : "—";
    dl.append(dt, dd);
  }
  return dl;
}

/** Re-render #detection-root from a badge element and (debug-only) signals. */
function render(badgeEl, signals) {
  if (!root) return;
  root.innerHTML = "";
  root.appendChild(badgeEl);
  if (DEBUG_MODE && signals) root.appendChild(signalsList(signals));
}

/** Ask the service worker for the active tab's detection result and render it. */
async function loadDetection() {
  const tab = await getActiveTab();
  if (!tab) {
    render(badge("No active tab", "neutral"), null);
    return;
  }

  const res = await chrome.runtime.sendMessage({
    type: "GET_DETECTION",
    payload: { tabId: tab.id },
  });
  const detection = res?.detection;

  if (!detection) {
    render(badge("Not analysed", "neutral"), null);
    return;
  }

  const b = detection.isJobPage
    ? badge(`Job page (${Math.round(detection.confidence * 100)}%)`, "ok")
    : badge("Not a job page", "warn");

  render(b, detection.signals);
}

// Auto-refresh when the user switches tabs or a page finishes loading.
chrome.tabs.onActivated.addListener(loadDetection);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (changeInfo.status === "complete" && tab.active) {
    loadDetection();
  }
});

loadDetection();
