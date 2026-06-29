/**
 * Pathfinder side-panel UI controller (Phase 1).
 *
 * The side panel is the user-facing review surface (TDD 5.3). In Phase 1 it
 * only shows: (a) the current page's job-detection result, and (b) backend
 * connectivity. Like the content script, it talks only to the service worker
 * (TDD 6.1) — never directly to the backend.
 */

const detectionEl = document.getElementById("detection");
const signalsEl = document.getElementById("signals");
const healthEl = document.getElementById("health");
const checkHealthBtn = document.getElementById("check-health");

/** Helper: render a coloured status badge into a container. */
function setBadge(container, text, variant) {
  container.innerHTML = "";
  const span = document.createElement("span");
  span.className = `badge badge--${variant}`;
  span.textContent = text;
  container.appendChild(span);
}

/** Ask the service worker for the active tab's detection result and render it. */
async function loadDetection() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
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

checkHealthBtn.addEventListener("click", checkHealth);

// Initial render.
loadDetection();
checkHealth();
