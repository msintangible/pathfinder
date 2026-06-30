/**
 * Page scraping — pure functions, no side effects.
 *
 * Strategy:
 *   1. Find the main content area using semantic HTML landmarks.
 *   2. Clone it and strip obvious noise (nav, footer, cookie banners, etc.).
 *   3. Extract innerText and normalise whitespace.
 *
 * This gives the Job Analysis Agent a clean, focused block of text instead
 * of the full page dump (which includes nav menus, cookie notices, footers,
 * and other irrelevant content that wastes tokens and degrades extraction).
 */

// Elements that are nearly always noise on any page.
const NOISE_SELECTORS = [
  "nav",
  "header",
  "footer",
  "aside",
  "[role='navigation']",
  "[role='banner']",
  "[role='contentinfo']",
  "[role='complementary']",
  // Common cookie / consent banner patterns.
  "#cookie-banner",
  "#cookie-notice",
  ".cookie-banner",
  ".cookie-notice",
  "[class*='cookie']",
  "[id*='cookie']",
  // Misc noise.
  "script",
  "style",
  "noscript",
  "svg",
  "iframe",
];

// 20 000 chars is more than enough for any job description and keeps the
// payload lean for the backend AI call.
const MAX_CHARS = 500;

/**
 * Find the most relevant content container in the page.
 *
 * Tries semantic landmarks in priority order. If none exist, falls back to
 * the element with the most text content among common content wrappers,
 * then finally to document.body.
 */
function findMainContent() {
  // Priority 1 — explicit semantic landmarks.
  const semantic = [
    document.querySelector("main"),
    document.querySelector("[role='main']"),
    document.querySelector("article"),
  ].filter(Boolean);

  if (semantic.length > 0) return semantic[0];

  // Priority 2 — common job-posting container patterns.
  const jobContainers = [
    document.querySelector(".job-description"),
    document.querySelector("[data-testid='job-description']"),
    document.querySelector("[class*='job-details']"),
    document.querySelector("[class*='jobDetails']"),
    document.querySelector("#job-description"),
    document.querySelector("#jobDescription"),
  ].filter(Boolean);

  if (jobContainers.length > 0) {
    return jobContainers.reduce((a, b) =>
      (a.innerText?.length || 0) >= (b.innerText?.length || 0) ? a : b
    );
  }

  // Fallback — whole body.
  return document.body;
}

/** Clone a node and remove all noise elements from the clone. */
function withoutNoise(node) {
  const clone = node.cloneNode(true);
  for (const sel of NOISE_SELECTORS) {
    for (const el of clone.querySelectorAll(sel)) {
      el.remove();
    }
  }
  return clone;
}

/** Collapse excess whitespace without destroying line breaks that aid parsing. */
function normalise(text) {
  return text
    .replace(/\t/g, " ")
    .replace(/[ \t]{2,}/g, " ")   // collapse horizontal whitespace
    .replace(/\n{3,}/g, "\n\n")   // at most one blank line between blocks
    .trim();
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function scrapePage() {
  const root = withoutNoise(findMainContent());
  // Use a detached element so innerText reflects actual rendered whitespace
  // without the browser needing to lay it out.
  const raw = normalise(root.innerText || "");
  const truncated = raw.length > MAX_CHARS;

  return {
    url: location.href,
    title: document.title || null,
    scrapedAt: new Date().toISOString(),
    length: raw.length,
    truncated,
    text: truncated ? raw.slice(0, MAX_CHARS) : raw,
  };
}
