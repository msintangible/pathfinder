/**
 * chrome.storage helpers for per-tab detection state.
 *
 * Detection results live in chrome.storage.session (cleared when the browser
 * closes) keyed by tab ID. The service worker must never hold detection state
 * in module-level variables because MV3 service workers are non-persistent.
 */

const PREFIX = "detection:";

export async function saveDetection(tabId, payload) {
  await chrome.storage.session.set({ [PREFIX + tabId]: payload });
}

export async function getDetection(tabId) {
  if (tabId == null) return null;
  const stored = await chrome.storage.session.get(PREFIX + tabId);
  return stored[PREFIX + tabId] ?? null;
}

export async function removeDetection(tabId) {
  await chrome.storage.session.remove(PREFIX + tabId).catch(() => {});
}
