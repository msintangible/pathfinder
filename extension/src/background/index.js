/**
 * Service worker entry point (Manifest V3).
 *
 * Sole responsibility: message routing + badge + tab lifecycle.
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
});

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

    default:
      sendResponse({ ok: false, error: `Unknown type: ${message?.type}` });
      return false;
  }
});

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

async function handlePageDetected(payload, sender) {
  const tabId = sender?.tab?.id;
  if (tabId == null) return;
  await saveDetection(tabId, payload);
  const isJobPage = Boolean(payload?.isJobPage);
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
