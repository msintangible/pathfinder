/**
 * Profile persistence + backend import.
 *
 * The side panel is trusted extension UI, so it may call the backend directly;
 * host_permissions (http://localhost/*) lets the request bypass CORS. We use
 * XMLHttpRequest (not fetch) specifically to expose real upload progress.
 */

import { StorageKey, DEFAULT_BACKEND_URL, Endpoint } from "./constants.js";
import { normalizeProfile, extractConfidence } from "./profileMapper.js";

/** Resolve the configured backend base URL (no trailing slash). */
export async function getBaseUrl() {
  const stored = await chrome.storage.local.get(StorageKey.BACKEND_URL);
  return (stored[StorageKey.BACKEND_URL] || DEFAULT_BACKEND_URL).replace(/\/+$/, "");
}

/** Load the locally-saved profile, or null if none. */
export async function loadProfile() {
  const stored = await chrome.storage.local.get(StorageKey.PROFILE);
  return stored[StorageKey.PROFILE] ?? null;
}

/** Persist the profile locally. User edits are the source of truth. */
export async function saveProfile(profile) {
  await chrome.storage.local.set({ [StorageKey.PROFILE]: profile });
}

function errorFromXhr(xhr) {
  const body = xhr.response;
  if (body && typeof body === "object") {
    return body.error?.message || body.detail || `HTTP ${xhr.status}`;
  }
  return `HTTP ${xhr.status}`;
}

/**
 * POST a CV (+ optional URLs) to /v1/profile/import as multipart form data.
 *
 * @param {{ file?: File, linkedin?: string, linkedinText?: string, github?: string,
 *           portfolio?: string, onProgress?: (fraction: number) => void }} opts
 * @returns {Promise<import("./types.js").ImportResult>}
 */
export async function importProfile(opts) {
  const { file, linkedin, linkedinText, github, portfolio, onProgress } = opts;
  const base = await getBaseUrl();

  const form = new FormData();
  if (file) form.append("file", file, file.name);
  if (linkedin) form.append("linkedin_url", linkedin);
  if (linkedinText) form.append("linkedin_text", linkedinText);
  if (github) form.append("github_url", github);
  if (portfolio) form.append("portfolio_url", portfolio);

  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${base}${Endpoint.PROFILE_IMPORT}`);
    xhr.responseType = "json";

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve({
          ok: true,
          profile: normalizeProfile(xhr.response),
          confidence: extractConfidence(xhr.response),
        });
      } else {
        resolve({ ok: false, error: errorFromXhr(xhr) });
      }
    };
    xhr.onerror = () => resolve({ ok: false, error: "Network error — is the backend running?" });
    xhr.send(form);
  });
}
