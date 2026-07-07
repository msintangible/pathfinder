/**
 * Job page detection — pure functions only, no side effects.
 *
 * Runs in escalating tiers (TDD 6.2). Each tier adds weighted evidence;
 * the final confidence score determines whether this is a job page.
 *
 * Pure functions = easy to unit-test outside of a browser context.
 */

// Tier 1 — known ATS platforms and job-board URL patterns.
// Each entry carries a weight so high-confidence ATS hosts outweigh
// generic job boards that might host non-job pages too.
const ATS_URL_PATTERNS = [
  { re: /\.greenhouse\.io(\/|$)/, weight: 0.6 },
  { re: /boards\.greenhouse\.io(\/|$)/, weight: 0.6 },
  { re: /jobs\.lever\.co(\/|$)/, weight: 0.6 },
  { re: /\.myworkdayjobs\.com(\/|$)/, weight: 0.6 },
  { re: /\.icims\.com(\/|$)/, weight: 0.6 },
  { re: /\.smartrecruiters\.com(\/|$)/, weight: 0.6 },
  { re: /\.bamboohr\.com(\/|$)/, weight: 0.6 },
  { re: /\.ashbyhq\.com(\/|$)/, weight: 0.6 },
  { re: /\.jobvite\.com(\/|$)/, weight: 0.6 },
  { re: /\.taleo\.net(\/|$)/, weight: 0.6 },
  { re: /\.successfactors\.(com|eu)(\/|$)/, weight: 0.6 },
  { re: /\.workable\.com(\/|$)/, weight: 0.6 },
  // Job boards — match on path too so we don't flag the homepage
  { re: /linkedin\.com\/jobs\//, weight: 0.6 },
  { re: /indeed\.com\/(viewjob|rc\/clk)/, weight: 0.5 },
  { re: /glassdoor\.com\/(job-listing|Job\/)/, weight: 0.5 },
  { re: /seek\.com\.au\/job\//, weight: 0.5 },
];

// Field names/ids/placeholders that only appear on job application forms.
const APPLICATION_FIELD_RE =
  /resume|curriculum.?vitae|\bcv\b|cover.?letter|first.?name|last.?name|linkedin|github|portfolio|work.?auth/i;

// Heading-level keywords that strongly suggest a job description.
const JOB_HEADING_KEYWORDS = [
  "responsibilities",
  "requirements",
  "qualifications",
  "what you'll do",
  "what we're looking for",
  "about the role",
  "about this role",
  "about the position",
  "nice to have",
  "you will",
  "we are looking for",
  "apply now",
  "apply for this",
  "submit your application",
  "job description",
  "the role",
  "your day-to-day",
];

// Body-text keywords — require multiple matches to avoid false positives.
const JOB_BODY_KEYWORDS = [
  "years of experience",
  "bachelor",
  "full-time",
  "part-time",
  "remote",
  "hybrid",
  "on-site",
  "salary",
  "compensation",
  "equal opportunity",
  "we offer",
  "benefits include",
];

const JOB_BODY_THRESHOLD = 2; // need at least this many body keywords

// ---------------------------------------------------------------------------
// Tier implementations
// ---------------------------------------------------------------------------

/** Tier 1 — URL matches a known ATS or job-board path. */
function urlScore() {
  const href = location.href;
  const host = location.hostname.toLowerCase();
  for (const { re, weight } of ATS_URL_PATTERNS) {
    if (re.test(host) || re.test(href)) return weight;
  }
  return 0;
}

/** Tier 2a — page embeds a schema.org JobPosting JSON-LD block. */
function hasJobPostingJsonLd() {
  // collectJsonLdNodesByType is declared in jsonld.js, loaded before this
  // file in manifest.json — shared traversal, see that file's header comment.
  return collectJsonLdNodesByType("JobPosting").length > 0;
}

/** Tier 2b — a form contains fields typical of a job application. */
function hasApplicationForm() {
  for (const form of querySelectorAllDeep(document, "form")) {
    const fields = querySelectorAllDeep(form, "input, textarea, select");
    if (fields.length < 3) continue;
    const hasJobFields = Array.from(fields).some((f) =>
      APPLICATION_FIELD_RE.test(f.name || f.id || f.placeholder || "")
    );
    if (hasJobFields) return true;
  }
  return false;
}

/** Tier 2c — headings contain job-description language. */
function hasJobHeadings() {
  const text = Array.from(
    querySelectorAllDeep(document, "h1, h2, h3, h4, [role='heading'], button")
  )
    .map((el) => el.textContent?.trim().toLowerCase() || "")
    .join(" ");
  return JOB_HEADING_KEYWORDS.some((kw) => text.includes(kw));
}

/** Tier 2d — page body contains multiple job-posting content signals. */
function hasJobBodyContent() {
  // innerText doesn't reflect shadow-DOM text; unlike the selector-based
  // tiers above, deep-querying here would mean re-walking and re-joining
  // every open shadow root's text, which is scrape.js's job (extractText),
  // not a cheap sanity check. Tiers 1/2a/2b/2c already cover shadow-DOM
  // pages via querySelectorAllDeep, so this one tier staying light-DOM-only
  // is an acceptable gap.
  const text = (document.body?.innerText || "").slice(0, 8000).toLowerCase();
  const hits = JOB_BODY_KEYWORDS.filter((kw) => text.includes(kw)).length;
  return hits >= JOB_BODY_THRESHOLD;
}

/** Tier 2e — page title or og:type tag signals a job. */
function hasJobMetaTags() {
  const ogType =
    document.querySelector('meta[property="og:type"]')?.content?.toLowerCase() || "";
  if (ogType.includes("job")) return true;
  const title = document.title.toLowerCase();
  return JOB_HEADING_KEYWORDS.some((kw) => title.includes(kw));
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function detect() {
  const tier1 = urlScore();
  const jsonLd = hasJobPostingJsonLd();
  const applicationForm = hasApplicationForm();
  const jobHeadings = hasJobHeadings();
  const jobBody = hasJobBodyContent();
  const metaTags = hasJobMetaTags();

  let confidence = tier1;
  if (jsonLd) confidence += 0.4;
  if (applicationForm) confidence += 0.25;
  if (jobHeadings) confidence += 0.2;
  if (jobBody) confidence += 0.15;
  if (metaTags) confidence += 0.1;
  confidence = Math.min(confidence, 1);

  return {
    isJobPage: confidence >= 0.4,
    confidence,
    signals: {
      urlMatch: tier1 > 0,
      jsonLd,
      applicationForm,
      jobKeywords: jobHeadings || jobBody,
      metaTags,
    },
    url: location.href,
    detectedAt: new Date().toISOString(),
  };
}
