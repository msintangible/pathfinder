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
  SOURCES: "sources",
  PROFILE_ID: "profileId",
  BACKEND_URL: "backendUrl",
  AUTH_TOKEN: "authToken",
});

/** Backend routes. */
export const Endpoint = Object.freeze({
  AUTH_ANONYMOUS: "/v1/auth/anonymous",
  PROFILE_IMPORT: "/v1/profile/import",
  RESUME_GENERATE: "/v1/resumes/generate",
});

export const DEFAULT_BACKEND_URL = "http://localhost:8003";

/** CV upload constraints. DOCX (not just PDF) is accepted so resume generation
 *  can edit the candidate's original file in place instead of rendering a
 *  generic template — see backend/services/docx_resume_renderer.py. */
export const Upload = Object.freeze({
  MAX_BYTES: 10 * 1024 * 1024,
  MAX_LABEL: "10MB",
  ACCEPTED_MIME: Object.freeze([
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ]),
  ACCEPTED_EXT: ".pdf,.docx",
});

/** User-facing copy, centralised so wording stays consistent. */
export const Message = Object.freeze({
  DROP_HINT: "Drag & drop your CV here, or click to browse",
  UNSUPPORTED_FILE_TYPE: "Only PDF or DOCX files are supported.",
  TOO_LARGE: `That file is larger than ${"10MB"}.`,
  UPLOADING: "Reading your CV and building your profile…",
  IMPORT_FAILED: "We couldn't import your profile.",
  NO_BACKEND: "Backend unreachable — try again once it's running.",
  SAVED: "Profile saved.",
  REIMPORT: "Re-import from CV",

  // Optimize CV
  NO_PROFILE_HINT: "Import your profile above before optimizing a resume.",
  PROFILE_NEEDS_REIMPORT_HINT: "Your saved profile is missing an id — click \"Re-import from CV\" above to refresh it.",
  NO_JOB_HINT: "Analyse this job posting above before optimizing a resume.",
  OPTIMIZE_CV: "Optimize CV",
  REOPTIMIZE: "Re-optimize",
  GENERATING: "Tailoring your resume…",
  GENERATE_FAILED: "We couldn't generate a resume.",
  OPEN_RESUME: "Open Resume",
});
