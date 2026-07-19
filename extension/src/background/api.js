/**
 * Backend API helpers.
 *
 * The service worker is the only layer that calls the backend (TDD 6.1 / 15.3).
 * All fetch logic lives here so it can be found, changed, and tested in one place.
 *
 * host_permissions in manifest.json covers http://localhost/* so fetch from the
 * service worker bypasses CORS for that origin (MV3 behaviour).
 */

import { getAuthToken, clearAuthToken } from "../shared/auth.js";
import { loadProfile, saveProfileId } from "../shared/profileApi.js";

const DEFAULT_BASE_URL = "http://localhost:8003";

// A hung backend (or a bad backendUrl pointing nowhere) must not hang the
// calling UI action forever — fetch() has no built-in timeout, so every
// request is bounded by an AbortController instead of relying on the
// browser's own (much longer, sometimes absent) socket timeout.
const REQUEST_TIMEOUT_MS = 60000;

export async function getBaseUrl() {
  const { backendUrl } = await chrome.storage.local.get("backendUrl");
  return (backendUrl || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

/** fetch() with a hard timeout. Rejects with an AbortError after REQUEST_TIMEOUT_MS. */
async function fetchWithTimeout(url, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

/** Normalise a failed fetch into the { ok: false, error } shape used everywhere. */
function networkError(err) {
  if (err?.name === "AbortError") {
    return { ok: false, error: `Request timed out after ${REQUEST_TIMEOUT_MS / 1000}s` };
  }
  return { ok: false, error: err?.message ?? "Network error" };
}

/**
 * Every consumer of analyzeJob()/generateResume() (detection/index.js,
 * optimize/index.js, job-analysis/index.js) used to unpack a failed
 * response's raw "HTTP {status}: {response body}" text and display it
 * directly — three separate UI files independently had the same bug,
 * because the raw text originated here and nothing sanitized it before it
 * left this file. Fixed at the source instead: every failure path in this
 * file logs the real detail once, here, and returns plain, calm copy
 * (docs/pathfinder-uiux-requirements.md's Voice rule: "No raw error
 * strings/JSON ever shown to users") — so every current and future
 * consumer inherits safe behavior automatically, with nothing to remember
 * to do on the display side.
 */
function sanitizedFailure(context, rawDetail, plainMessage) {
  console.error(`${context} failed:`, rawDetail);
  return { ok: false, error: plainMessage };
}

export async function checkHealth() {
  try {
    const base = await getBaseUrl();
    const res = await fetchWithTimeout(`${base}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    return { ok: true, data: await res.json() };
  } catch (err) {
    return networkError(err);
  }
}

export async function analyzeJob({ raw_text, url } = {}) {
  if (!raw_text) return { ok: false, error: "No page text to analyse." };
  try {
    const base = await getBaseUrl();
    const token = await getAuthToken(base);
    const res = await fetchWithTimeout(`${base}/v1/jobs/analyze`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ raw_text, url: url ?? null }),
    });
    if (!res.ok) {
      if (res.status === 401) await clearAuthToken();
      return sanitizedFailure(
        "ANALYZE_JOB",
        `HTTP ${res.status}: ${await res.text()}`,
        "Couldn't read this job posting. Try again."
      );
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return networkError(err);
  }
}

function postGenerate(base, token, user_profile_id, job_id) {
  return fetchWithTimeout(`${base}/v1/resumes/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ user_profile_id, job_id }),
  });
}

/**
 * Re-persists the locally cached profile via /v1/profile/restore, skipping
 * LLM analysis since this data was already analyzed once. Returns the new
 * profile id, or null if there's nothing cached to restore from.
 */
async function restoreProfile(base, token) {
  const profile = await loadProfile();
  if (!profile) return null;

  const res = await fetchWithTimeout(`${base}/v1/profile/restore`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ profile }),
  });
  if (!res.ok) return null;

  const { id } = await res.json();
  if (!id) return null;
  await saveProfileId(id);
  return id;
}

export async function generateResume({ user_profile_id, job_id } = {}) {
  if (!user_profile_id || !job_id) return { ok: false, error: "Missing profile or job id." };
  try {
    const base = await getBaseUrl();
    const token = await getAuthToken(base);

    let res = await postGenerate(base, token, user_profile_id, job_id);

    // A cached profile_id can outlive the row it points to (e.g. a backend
    // database reset) — self-heal by re-persisting the locally cached
    // profile and retrying once, instead of forcing a manual re-import.
    if (res.status === 404) {
      const rawBody = await res.text();
      let body = null;
      try { body = JSON.parse(rawBody); } catch { /* not JSON */ }

      if (body?.detail === "Profile not found") {
        const restoredId = await restoreProfile(base, token);
        if (!restoredId) {
          return sanitizedFailure(
            "GENERATE_RESUME",
            "HTTP 404: Profile not found (self-heal failed, no cached profile to restore from)",
            "Couldn't find your profile — try re-importing it."
          );
        }
        res = await postGenerate(base, token, restoredId, job_id);
      } else {
        return sanitizedFailure("GENERATE_RESUME", `HTTP 404: ${rawBody}`, "Couldn't generate your resume. Try again.");
      }
    }

    if (!res.ok) {
      if (res.status === 401) await clearAuthToken();
      return sanitizedFailure(
        "GENERATE_RESUME",
        `HTTP ${res.status}: ${await res.text()}`,
        "Couldn't generate your resume. Try again."
      );
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return networkError(err);
  }
}
