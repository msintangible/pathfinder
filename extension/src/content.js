/**
 * Pathfinder content script.
 *
 * Phase 1 responsibility (TDD Section 6.2): decide whether the current page
 * looks like a job posting / application page, and report that to the service
 * worker. Detection only — no DOM extraction or autofill yet (later phases).
 *
 * Content scripts are deliberately "dumb" (TDD 6.1): they sense the page and
 * message the service worker. They never call the backend directly.
 *
 * Detection runs in escalating tiers (TDD 6.2). Phase 1 implements Tiers 1–2:
 *   Tier 1 — URL heuristics against known ATS / job-board domains (instant).
 *   Tier 2 — DOM structure heuristics (schema.org JobPosting, form density,
 *            heading keywords).
 * Tier 3 (on-page classifier) is deferred to a later phase.
 */

// Tier 1: known ATS hosts and job-board URL patterns. Matched against hostname
// + pathname. Kept small for Phase 1; expands as ATS coverage grows (TDD 6.5).
const ATS_URL_PATTERNS = [
  /\.greenhouse\.io$/,
  /\bjobs\.lever\.co$/,
  /\.myworkdayjobs\.com$/,
  /\.icims\.com$/,
  /\.smartrecruiters\.com$/,
  /\.bamboohr\.com$/,
  /\.ashbyhq\.com$/,
  /\bboards\.greenhouse\.io$/,
];

// Tier 2: heading/keyword signals that suggest a job posting or application.
const JOB_KEYWORDS = [
  "job description",
  "responsibilities",
  "requirements",
  "qualifications",
  "apply now",
  "apply for this job",
  "submit application",
];

/** Tier 1 — does the URL match a known ATS / job board? */
function matchUrl() {
  const host = location.hostname.toLowerCase();
  return ATS_URL_PATTERNS.some((re) => re.test(host));
}

/** Tier 2a — embedded schema.org JobPosting JSON-LD is a high-quality signal. */
function hasJobPostingJsonLd() {
  const scripts = document.querySelectorAll('script[type="application/ld+json"]');
  for (const el of scripts) {
    try {
      const json = JSON.parse(el.textContent || "");
      const nodes = Array.isArray(json) ? json : [json];
      for (const node of nodes) {
        const type = node?.["@type"];
        const types = Array.isArray(type) ? type : [type];
        if (types.includes("JobPosting")) return true;
      }
    } catch {
      // Malformed JSON-LD — ignore and keep scanning.
    }
  }
  return false;
}

/** Tier 2b — a form with a meaningful density of input fields. */
function hasApplicationForm() {
  for (const form of document.querySelectorAll("form")) {
    const fields = form.querySelectorAll("input, textarea, select");
    if (fields.length >= 4) return true;
  }
  return false;
}

/** Tier 2c — job-related keywords present in visible headings / buttons. */
function hasJobKeywords() {
  const text = Array.from(document.querySelectorAll("h1, h2, h3, button, a"))
    .map((el) => (el.textContent || "").trim().toLowerCase())
    .join(" \n ");
  return JOB_KEYWORDS.some((kw) => text.includes(kw));
}

/**
 * Combine the tiers into a single result with a coarse confidence score.
 * Confidence is intentionally simple in Phase 1 — it gets refined when the
 * Job Analysis Agent and per-ATS adapters land.
 */
function detect() {
  const signals = {
    urlMatch: matchUrl(),
    jsonLd: hasJobPostingJsonLd(),
    applicationForm: hasApplicationForm(),
    jobKeywords: hasJobKeywords(),
  };

  let confidence = 0;
  if (signals.urlMatch) confidence += 0.5;
  if (signals.jsonLd) confidence += 0.4;
  if (signals.applicationForm) confidence += 0.2;
  if (signals.jobKeywords) confidence += 0.2;
  confidence = Math.min(confidence, 1);

  return {
    isJobPage: confidence >= 0.5,
    confidence,
    signals,
    url: location.href,
    detectedAt: new Date().toISOString(),
  };
}

/** Run detection and report it to the service worker. */
function run() {
  const result = detect();
  chrome.runtime
    .sendMessage({ type: "PAGE_DETECTED", payload: result })
    .catch(() => {
      // Service worker may be asleep / context invalidated on navigation.
      // The side panel re-requests detection on open, so this is non-fatal.
    });
}

run();

// ---------------------------------------------------------------------------
// Phase 2 — automatic page scrape.
//
// Scrape ALL visible text on the page into a JSON object. This runs on demand
// when the side panel asks (SCRAPE_PAGE) — no user button. The side panel
// displays the result; sending it to the backend is a later phase.
// ---------------------------------------------------------------------------

const MAX_SCRAPE_CHARS = 100000;

/** Collect all visible page text into a JSON-serialisable object. */
function scrapePage() {
  const raw = (document.body?.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
  const truncated = raw.length > MAX_SCRAPE_CHARS;
  return {
    url: location.href,
    title: document.title || null,
    scrapedAt: new Date().toISOString(),
    length: raw.length,
    truncated,
    text: truncated ? raw.slice(0, MAX_SCRAPE_CHARS) : raw,
  };
}

// The side panel requests a fresh scrape whenever it opens or the page changes.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "SCRAPE_PAGE") {
    sendResponse(scrapePage());
    return false; // synchronous response
  }
  return false;
});
