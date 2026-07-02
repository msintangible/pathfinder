/**
 * Backend API helpers.
 *
 * The service worker is the only layer that calls the backend (TDD 6.1 / 15.3).
 * All fetch logic lives here so it can be found, changed, and tested in one place.
 *
 * host_permissions in manifest.json covers http://localhost/* so fetch from the
 * service worker bypasses CORS for that origin (MV3 behaviour).
 */

const DEFAULT_BASE_URL = "http://localhost:8003";

// A hung backend (or a bad backendUrl pointing nowhere) must not hang the
// calling UI action forever — fetch() has no built-in timeout, so every
// request is bounded by an AbortController instead of relying on the
// browser's own (much longer, sometimes absent) socket timeout.
const REQUEST_TIMEOUT_MS = 15000;

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
    const res = await fetchWithTimeout(`${base}/v1/jobs/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ raw_text, url: url ?? null }),
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}: ${await res.text()}` };
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return networkError(err);
  }
}

export async function generateResume({ user_profile_id, job_id } = {}) {
  if (!user_profile_id || !job_id) return { ok: false, error: "Missing profile or job id." };
  try {
    const base = await getBaseUrl();
    const res = await fetchWithTimeout(`${base}/v1/resumes/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ user_profile_id, job_id }),
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}: ${await res.text()}` };
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return networkError(err);
  }
}
