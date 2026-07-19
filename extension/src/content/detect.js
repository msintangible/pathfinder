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
// generic job boards that might host non-job pages too. `name` is the
// platform label shown on the Known ATS screen (e.g. "Data Analyst ·
// Reperio Human Capital · Greenhouse") — display-only, doesn't affect scoring.
const ATS_URL_PATTERNS = [
  { re: /\.greenhouse\.io(\/|$)/, weight: 0.6, name: "Greenhouse" },
  { re: /boards\.greenhouse\.io(\/|$)/, weight: 0.6, name: "Greenhouse" },
  { re: /jobs\.lever\.co(\/|$)/, weight: 0.6, name: "Lever" },
  { re: /\.myworkdayjobs\.com(\/|$)/, weight: 0.6, name: "Workday" },
  { re: /\.icims\.com(\/|$)/, weight: 0.6, name: "iCIMS" },
  { re: /\.smartrecruiters\.com(\/|$)/, weight: 0.6, name: "SmartRecruiters" },
  { re: /\.bamboohr\.com(\/|$)/, weight: 0.6, name: "BambooHR" },
  { re: /\.ashbyhq\.com(\/|$)/, weight: 0.6, name: "Ashby" },
  { re: /\.jobvite\.com(\/|$)/, weight: 0.6, name: "Jobvite" },
  { re: /\.taleo\.net(\/|$)/, weight: 0.6, name: "Taleo" },
  { re: /\.successfactors\.(com|eu)(\/|$)/, weight: 0.6, name: "SuccessFactors" },
  { re: /\.workable\.com(\/|$)/, weight: 0.6, name: "Workable" },
  // Job boards — match on path too so we don't flag the homepage
  { re: /linkedin\.com\/jobs\//, weight: 0.6, name: "LinkedIn" },
  { re: /indeed\.com\/(viewjob|rc\/clk)/, weight: 0.5, name: "Indeed" },
  { re: /glassdoor\.com\/(job-listing|Job\/)/, weight: 0.5, name: "Glassdoor" },
  { re: /seek\.com\.au\/job\//, weight: 0.5, name: "Seek" },
];

// Hosts that can never be a job posting, regardless of what Tier 2's
// keyword-based signals find on the page — confirmed false-positive
// generators, not a hypothetical list.
//
// Root cause: hasJobHeadings()/hasJobBodyContent()/hasJobMetaTags() match
// job-posting *vocabulary* anywhere on the page, not page structure. On an
// AI chat tool, asking the assistant to review a job posting or resume
// makes the assistant's own rendered markdown response produce real
// <h2>/<h3> headings ("About the role", "Requirements") and prose full of
// job-posting terms — the chat transcript reads exactly like a job posting
// to a keyword scanner, even though the page itself is a conversation.
// Verified with a synthetic claude.ai fixture: Tier 2 alone summed to 0.45
// confidence (isJobPage: true) on a page with zero actual job content.
//
// A more general fix (require at least one structural/"hard" signal —
// urlMatch, jsonLd, or applicationForm — before Tier 2's keyword signals
// alone can cross the isJobPage threshold) was tried and reverted: it also
// demoted tests/fixtures/generic-no-ats.html, a real single-company careers
// page with no ATS platform, no JobPosting schema, and no captured
// application form, which relies entirely on Tier 2 signals and is a
// legitimate case Pathfinder should still detect. Distinguishing "a page
// that IS a job posting relying only on keywords" from "a page that just
// TALKS ABOUT one" needs real fixtures for the other vocabulary-false-
// positive shapes (career-advice articles, job-hunting forum threads) to
// validate against before it can be safely generalized — tracked as
// follow-up work, not solved by this denylist.
const NON_JOB_HOSTS = [
  /(^|\.)claude\.ai$/,
  /(^|\.)chatgpt\.com$/,
  /(^|\.)chat\.openai\.com$/,
  /(^|\.)gemini\.google\.com$/,
  /(^|\.)perplexity\.ai$/,
];

/** True if the current page's host can never be a job posting — see
 *  NON_JOB_HOSTS above for why this exists. */
function isKnownNonJobHost() {
  const host = location.hostname.toLowerCase();
  return NON_JOB_HOSTS.some((re) => re.test(host));
}

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
// "remote" and "we offer" were dropped: both are common in general prose
// about jobs/careers (news articles, chat conversations, forum threads)
// that isn't an actual job posting, not just in real ones.
const JOB_BODY_KEYWORDS = [
  "years of experience",
  "bachelor",
  "full-time",
  "part-time",
  "hybrid",
  "on-site",
  "salary",
  "compensation",
  "equal opportunity",
  "benefits include",
];

const JOB_BODY_THRESHOLD = 2; // need at least this many body keywords

// ---------------------------------------------------------------------------
// Tier implementations
// ---------------------------------------------------------------------------

/** The first matching ATS_URL_PATTERNS entry, or null. Shared by urlScore()
 *  and matchedAtsName() so both agree on which pattern matched. */
function matchedAtsPattern() {
  const href = location.href;
  const host = location.hostname.toLowerCase();
  for (const pattern of ATS_URL_PATTERNS) {
    if (pattern.re.test(host) || pattern.re.test(href)) return pattern;
  }
  return null;
}

/** Tier 1 — URL matches a known ATS or job-board path. */
function urlScore() {
  return matchedAtsPattern()?.weight ?? 0;
}

/** Display name of the matched ATS platform, or null (e.g. "Greenhouse"). */
function matchedAtsName() {
  return matchedAtsPattern()?.name ?? null;
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

/** Tier 2c — headings contain job-description language. `button` is
 *  deliberately excluded: buttons are UI chrome, not content headings, and
 *  scanning them widens false-positive exposure to any unrelated page with
 *  an "Apply"/"Submit"-labeled button (filters, coupons, forms). */
function hasJobHeadings() {
  const text = Array.from(
    querySelectorAllDeep(document, "h1, h2, h3, h4, [role='heading']")
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
  if (isKnownNonJobHost()) {
    return {
      isJobPage: false,
      confidence: 0,
      atsName: null,
      signals: { urlMatch: false, jsonLd: false, applicationForm: false, jobKeywords: false, metaTags: false },
      url: location.href,
      detectedAt: new Date().toISOString(),
    };
  }

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
    atsName: matchedAtsName(),
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
