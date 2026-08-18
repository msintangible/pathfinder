/**
 * Service worker entry point (Manifest V3).
 *
 * Sole responsibility: message routing + badge + toolbar icon + tab lifecycle.
 * All storage logic → storage.js. All network logic → api.js.
 *
 * MV3 service workers are non-persistent (killed after ~30s idle). No
 * in-memory state is held here; everything durable lives in chrome.storage.
 */

import {
  saveDetection, getDetection, removeDetection,
  saveJobAnalysis, getJobAnalysis, removeJobAnalysis,
  saveResumeResult, getResumeResult, removeResumeResult,
} from "./storage.js";
import { checkHealth, analyzeJob, generateResume } from "./api.js";

// Open the side panel when the toolbar icon is clicked.
chrome.runtime.onInstalled.addListener(() => {
  chrome.sidePanel
    .setPanelBehavior({ openPanelOnActionClick: true })
    .catch((err) => console.error("[Pathfinder]", err));
  ensureOffscreenDocument();
});

// onInstalled doesn't fire on a normal browser restart — the offscreen
// document (unlike service-worker state) doesn't survive that either, so
// it needs re-creating here too.
chrome.runtime.onStartup.addListener(() => {
  ensureOffscreenDocument();
});

// ---------------------------------------------------------------------------
// Toolbar icon — light/dark tracks the OS toolbar theme, not the extension's
// own light/dark CSS (Chrome doesn't expose that split for action icons).
// The service worker has no window/matchMedia, so an offscreen document
// (offscreen.html/.js) does the detection and reports back via messaging.
// ---------------------------------------------------------------------------

const OFFSCREEN_URL = "src/background/offscreen.html";

/** Idempotent: safe to call from any listener that might run before the
 * offscreen document exists yet. */
async function ensureOffscreenDocument() {
  try {
    await chrome.offscreen.createDocument({
      url: OFFSCREEN_URL,
      reasons: ["MATCH_MEDIA"],
      justification: "Detect prefers-color-scheme to choose the toolbar icon variant.",
    });
  } catch (err) {
    // Chrome throws if a document already exists — that's the expected
    // steady-state case, not a real failure.
    if (!String(err?.message).includes("single offscreen")) {
      console.error("[Pathfinder]", err);
    }
  }
}

function setToolbarIcon(isDark) {
  const path = isDark
    ? { 16: "icons/icon16-dark.png", 32: "icons/icon32-dark.png" }
    : { 16: "icons/icon16.png", 32: "icons/icon32.png" };
  chrome.action.setIcon({ path }).catch((err) => console.error("[Pathfinder]", err));
}

// ---------------------------------------------------------------------------
// Message router — every message has { type, payload } shape.
// Return true from the listener to keep the channel open for async responses.
// ---------------------------------------------------------------------------
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  switch (message?.type) {
    case "PAGE_DETECTED":
      handlePageDetected(message.payload, sender);
      sendResponse({ ok: true });
      return false;

    case "GET_DETECTION":
      getDetection(message.payload?.tabId)
        .then((detection) => sendResponse({ detection }));
      return true;

    case "HEALTH_CHECK":
      checkHealth().then(sendResponse);
      return true;

    case "ANALYZE_JOB":
      analyzeJob(message.payload).then(sendResponse);
      return true;

    // The following four are sent from the side panel (not a content script),
    // so tabId is passed explicitly in the payload — there's no sender.tab here.
    case "SAVE_JOB_ANALYSIS":
      saveJobAnalysis(message.payload?.tabId, message.payload).then(() => sendResponse({ ok: true }));
      return true;

    case "GET_JOB_ANALYSIS":
      getJobAnalysis(message.payload?.tabId).then((jobAnalysis) => sendResponse({ jobAnalysis }));
      return true;

    case "SAVE_RESUME_RESULT":
      saveResumeResult(message.payload?.tabId, message.payload?.data).then(() => sendResponse({ ok: true }));
      return true;

    case "GET_RESUME_RESULT":
      getResumeResult(message.payload?.tabId).then((resumeResult) => sendResponse({ resumeResult }));
      return true;

    case "GENERATE_RESUME":
      generateResume(message.payload).then(sendResponse);
      return true;

    case "COLOR_SCHEME_CHANGED":
      setToolbarIcon(message.payload?.isDark);
      sendResponse({ ok: true });
      return false;

    default:
      sendResponse({ ok: false, error: `Unknown type: ${message?.type}` });
      return false;
  }
});

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

/**
 * With all_frames: true, an iframe-embedded ATS (Lever, some Workday embeds)
 * reports its own detection independently from the surrounding top-level
 * page, and either can arrive first. Keep whichever has the higher
 * confidence for the CURRENT page load.
 *
 * "Current page load" is tracked via sender.tab.url, which reflects the
 * tab's top-level URL regardless of which frame sent the message — a real
 * navigation changes it (so a stale high-confidence score from a previous
 * page can't linger and leave the "JOB" badge stuck), while sibling frames
 * on the same load share it (so they merge instead of clobbering each other).
 *
 * Best-effort, not strictly race-free: two frames' messages arriving in the
 * same microtask window could both read storage before either writes. Low
 * severity (self-corrects on the next GET_DETECTION read) and not worth a
 * lock for how rarely more than one or two frames report per tab.
 */
export async function handlePageDetected(payload, sender) {
  const tabId = sender?.tab?.id;
  if (tabId == null) return;

  const pageUrl = sender?.tab?.url ?? null;
  const existing = await getDetection(tabId);
  const isNewPage = !existing || existing._pageUrl !== pageUrl;
  const shouldReplace = isNewPage || payload?.confidence > existing.confidence;

  const winner = shouldReplace ? { ...payload, _pageUrl: pageUrl } : existing;
  if (shouldReplace) await saveDetection(tabId, winner);

  const isJobPage = Boolean(winner?.isJobPage);
  await chrome.action.setBadgeText({ tabId, text: isJobPage ? "JOB" : "" });
  if (isJobPage) {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#2563eb" });
  }
}

// Clean up per-tab state when the tab closes.
chrome.tabs.onRemoved.addListener((tabId) => {
  removeDetection(tabId);
  removeJobAnalysis(tabId);
  removeResumeResult(tabId);
});
