/**
 * Shared constants & enums for Pathfinder (no magic strings anywhere else).
 */

/** Finite states the profile UI can be in. The user always knows which one. */
export const ImportState = Object.freeze({
  IDLE: "idle", // no profile yet, awaiting import
  VALIDATING: "validating", // checking the chosen file
  UPLOADING: "uploading", // sending to backend, extracting
  SUCCESS: "success", // profile imported and saved
  ERROR: "error", // import failed (user can retry)
});

/** chrome.storage.local keys. */
export const StorageKey = Object.freeze({
  PROFILE: "profile",
  BACKEND_URL: "backendUrl",
});

/** Backend routes. */
export const Endpoint = Object.freeze({
  PROFILE_IMPORT: "/v1/profile/import",
});

export const DEFAULT_BACKEND_URL = "http://localhost:8003";

/** CV upload constraints. */
export const Upload = Object.freeze({
  MAX_BYTES: 10 * 1024 * 1024,
  MAX_LABEL: "10MB",
  ACCEPTED_MIME: "application/pdf",
  ACCEPTED_EXT: ".pdf",
});

/** User-facing copy, centralised so wording stays consistent. */
export const Message = Object.freeze({
  DROP_HINT: "Drag & drop your CV here, or click to browse",
  PDF_ONLY: "Only PDF files are supported.",
  TOO_LARGE: `That file is larger than ${"10MB"}.`,
  UPLOADING: "Reading your CV and building your profile…",
  IMPORT_FAILED: "We couldn't import your profile.",
  NO_BACKEND: "Backend unreachable — try again once it's running.",
  SAVED: "Profile saved.",
  REIMPORT: "Re-import from CV",
});
