/**
 * Shared constants & enums for Pathfinder (no magic strings anywhere else).
 */

/** Finite states the profile UI can be in. The user always knows which one. */
export const ImportState = Object.freeze({
  IDLE: "idle", // no profile yet, awaiting upload or manual entry
  VALIDATING: "validating", // checking the chosen file
  UPLOADING: "uploading", // sending to backend, extracting
  NEEDS_REVIEW: "needs_review", // imported, but low-confidence fields to check
  SUCCESS: "success", // profile present and confirmed
  ERROR: "error", // import failed (user can retry or go manual)
  MANUAL: "manual", // user is entering/editing by hand
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

/** Confidence below this is flagged for human review (never silently accepted). */
export const CONFIDENCE_LOW = 0.6;

/** Top-level profile field keys (used for confidence lookups & rendering). */
export const ProfileField = Object.freeze({
  NAME: "name",
  EMAIL: "email",
  SKILLS: "skills",
  EXPERIENCE: "experience",
  EDUCATION: "education",
  PROJECTS: "projects",
  CERTIFICATIONS: "certifications",
  LINKS: "links",
});

/** User-facing copy, centralised so wording stays consistent. */
export const Message = Object.freeze({
  DROP_HINT: "Drag & drop your CV here, or click to browse",
  PDF_ONLY: "Only PDF files are supported.",
  TOO_LARGE: `That file is larger than ${"10MB"}.`,
  UPLOADING: "Reading your CV and building your profile…",
  IMPORT_FAILED: "We couldn't import your CV.",
  NO_BACKEND: "Backend unreachable — you can still enter your details by hand.",
  NEEDS_REVIEW: "Imported. Please check the highlighted fields — we weren't fully sure.",
  SAVED: "Profile saved.",
  MANUAL_HINT: "No CV? Enter your details manually.",
  ENTER_MANUALLY: "Enter manually instead",
  REIMPORT: "Re-import from CV",
});
