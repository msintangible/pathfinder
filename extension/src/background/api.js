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

export async function getBaseUrl() {
  const { backendUrl } = await chrome.storage.local.get("backendUrl");
  return (backendUrl || DEFAULT_BASE_URL).replace(/\/+$/, "");
}

export async function checkHealth() {
  try {
    const base = await getBaseUrl();
    const res = await fetch(`${base}/health`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return { ok: false, error: `HTTP ${res.status}` };
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, error: err?.message ?? "Network error" };
  }
}

export async function analyzeJob({ raw_text, url } = {}) {
  if (!raw_text) return { ok: false, error: "No page text to analyse." };
  try {
    const base = await getBaseUrl();
    const res = await fetch(`${base}/v1/jobs/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ raw_text, url: url ?? null }),
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}: ${await res.text()}` };
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, error: err?.message ?? "Network error" };
  }
}

export async function generateResume({ user_profile_id, job_id } = {}) {
  if (!user_profile_id || !job_id) return { ok: false, error: "Missing profile or job id." };
  try {
    const base = await getBaseUrl();
    const res = await fetch(`${base}/v1/resumes/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ user_profile_id, job_id }),
    });
    if (!res.ok) {
      return { ok: false, error: `HTTP ${res.status}: ${await res.text()}` };
    }
    return { ok: true, data: await res.json() };
  } catch (err) {
    return { ok: false, error: err?.message ?? "Network error" };
  }
}
