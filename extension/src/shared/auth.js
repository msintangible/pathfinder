/**
 * Anonymous auth token — every /v1/profile, /v1/jobs, /v1/resumes call
 * requires a bearer token now that the backend enforces get_current_user.
 * There's no login flow yet, only POST /v1/auth/anonymous (self-issued
 * identity), so this just mints one on first use and caches it.
 */
import { StorageKey, Endpoint } from "./constants.js";

/** Returns the cached anonymous token, minting + persisting one via `base` if none is cached yet. */
export async function getAuthToken(base) {
  const stored = await chrome.storage.local.get(StorageKey.AUTH_TOKEN);
  if (stored[StorageKey.AUTH_TOKEN]) return stored[StorageKey.AUTH_TOKEN];

  const res = await fetch(`${base}${Endpoint.AUTH_ANONYMOUS}`, {
    method: "POST",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) throw new Error(`Could not authenticate: HTTP ${res.status}`);

  const { access_token } = await res.json();
  await chrome.storage.local.set({ [StorageKey.AUTH_TOKEN]: access_token });
  return access_token;
}

/**
 * Drops the cached token so the next getAuthToken() call mints a fresh one.
 * Called after a 401 — e.g. the backend's users table was reset locally, so
 * a previously-valid token no longer resolves to a real user.
 */
export async function clearAuthToken() {
  await chrome.storage.local.remove(StorageKey.AUTH_TOKEN);
}
