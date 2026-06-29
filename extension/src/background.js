/**
 * Pathfinder service worker (Manifest V3).
 *
 * Phase 1 responsibilities (TDD Section 6.1):
 *   - The single coordination point between content scripts, the side panel,
 *     and the backend. Content scripts and the side panel NEVER call the
 *     backend directly (TDD 6.1 / 15.3) — they message the service worker,
 *     which owns all network I/O.
 *   - Owns the toolbar badge state that signals "job page detected".
 *   - Opens the side panel when the toolbar icon is clicked.
 *
 * MV3 service workers are non-persistent: they are killed after ~30s idle and
 * woken on the next event. We therefore hold NO long-lived in-memory state
 * here that we can't rebuild; per-tab detection results live in chrome.storage
 * (see DETECTION_PREFIX) rather than a module-level variable.
 */

// Backend base URL. Configurable via chrome.storage.local ("backendUrl") so we
// never hard-assume a port — the backend is owned separately and may run on a
// different port. Default matches the backend's committed run config (8003).
// The chosen URL must be covered by host_permissions in manifest.json so the
// service worker's fetch bypasses CORS for that origin (MV3 behaviour).
const DEFAULT_API_BASE_URL = "http://localhost:8003";

/** Resolve the configured backend base URL (no trailing slash). */
async function getBaseUrl() {
  const { backendUrl } = await chrome.storage.local.get("backendUrl");
  return (backendUrl || DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

// chrome.storage key prefix for per-tab job-page detection results.
const DETECTION_PREFIX = "detection:";

// ---------------------------------------------------------------------------
// Side panel: open on toolbar icon click.
// ---------------------------------------------------------------------------
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error("[Pathfinder] setPanelBehavior failed:", err));
});

// ---------------------------------------------------------------------------
// Message router. Every message has a { type, payload } shape.
// Returning `true` keeps the message channel open for the async sendResponse.
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case "PAGE_DETECTED":
      handlePageDetected(message.payload, sender);
      sendResponse({ ok: true });
      return false;

    case "GET_DETECTION":
      getDetection(message.payload?.tabId).then(sendResponse);
      return true;

    case "HEALTH_CHECK":
      checkBackendHealth().then(sendResponse);
      return true;

    default:
      sendResponse({ ok: false, error: `Unknown message type: ${message?.type}` });
      return false;
  }
});

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

/**
 * A content script reported its page-type detection result. Persist it per-tab
 * and reflect it in the toolbar badge.
 */
async function handlePageDetected(payload, sender) {
  const tabId = sender?.tab?.id;
  if (tabId == null) return;

  await chrome.storage.session.set({ [DETECTION_PREFIX + tabId]: payload });

  const isJobPage = Boolean(payload?.isJobPage);
  await chrome.action.setBadgeText({ tabId, text: isJobPage ? "JOB" : "" });
  if (isJobPage) {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#2563eb" });
  }
}

/** Return the last detection result the active tab reported (or null). */
async function getDetection(tabId) {
  if (tabId == null) return { detection: null };
  const key = DETECTION_PREFIX + tabId;
  const stored = await chrome.storage.session.get(key);
  return { detection: stored[key] ?? null };
}

/**
 * Proxy a backend health check. This is the Phase 1 proof that the
 * extension -> service worker -> backend loop works end to end.
 */
async function checkBackendHealth() {
  try {
    const base = await getBaseUrl();
    const res = await fetch(`${base}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) {
      return { ok: false, error: `Backend returned HTTP ${res.status}` };
    }
    const data = await res.json();
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err?.message ?? "Network error" };
  }
}

// Clean up per-tab detection state when a tab closes.
chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(DETECTION_PREFIX + tabId).catch(() => {});
});
