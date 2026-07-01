/**
 * chrome.storage helpers for per-tab state (detection, job analysis, resume results).
 *
 * All of it lives in chrome.storage.session (cleared when the browser closes)
 * keyed by tab ID. The service worker must never hold this state in
 * module-level variables because MV3 service workers are non-persistent.
 */

const DETECTION_PREFIX = "detection:";
const JOB_ANALYSIS_PREFIX = "jobAnalysis:";
const RESUME_RESULT_PREFIX = "resumeResult:";

export async function saveDetection(tabId, payload) {
  await chrome.storage.session.set({ [DETECTION_PREFIX + tabId]: payload });
}

export async function getDetection(tabId) {
  if (tabId == null) return null;
  const stored = await chrome.storage.session.get(DETECTION_PREFIX + tabId);
  return stored[DETECTION_PREFIX + tabId] ?? null;
}

export async function removeDetection(tabId) {
  await chrome.storage.session.remove(DETECTION_PREFIX + tabId).catch(() => {});
}

/** payload: { id, title, company, url } — the analyzed Job's backend id + the tab's URL at analysis time. */
export async function saveJobAnalysis(tabId, payload) {
  await chrome.storage.session.set({ [JOB_ANALYSIS_PREFIX + tabId]: payload });
}

export async function getJobAnalysis(tabId) {
  if (tabId == null) return null;
  const stored = await chrome.storage.session.get(JOB_ANALYSIS_PREFIX + tabId);
  return stored[JOB_ANALYSIS_PREFIX + tabId] ?? null;
}

export async function removeJobAnalysis(tabId) {
  await chrome.storage.session.remove(JOB_ANALYSIS_PREFIX + tabId).catch(() => {});
}

/** payload: the last ResumeGenerationResponse for this tab, so switching away and back doesn't lose it. */
export async function saveResumeResult(tabId, payload) {
  await chrome.storage.session.set({ [RESUME_RESULT_PREFIX + tabId]: payload });
}

export async function getResumeResult(tabId) {
  if (tabId == null) return null;
  const stored = await chrome.storage.session.get(RESUME_RESULT_PREFIX + tabId);
  return stored[RESUME_RESULT_PREFIX + tabId] ?? null;
}

export async function removeResumeResult(tabId) {
  await chrome.storage.session.remove(RESUME_RESULT_PREFIX + tabId).catch(() => {});
}
