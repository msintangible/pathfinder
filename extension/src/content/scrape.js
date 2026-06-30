/**
 * Page scraping — pure functions, no side effects, no page mutation.
 *
 * Goal: hand the backend's Job Analysis Agent the cleanest, most structured
 * representation of a job posting we can extract client-side.
 *
 * Strategy, in priority order:
 *   1. Structured data — parse schema.org/JobPosting JSON-LD. This is the
 *      authoritative, noise-free source (title, company, location, salary,
 *      employment type, dates, and the full description). Most ATS / job
 *      boards embed it for SEO.
 *   2. Readable content — when structured data is missing or thin, pick the
 *      best content container using a readability-style score (text density vs
 *      link density + class/id hints) and extract its visible text.
 *   3. Body fallback — last resort for unrecognised pages.
 *
 * Text extraction walks the LIVE DOM with a TreeWalker, skipping hidden and
 * noise nodes and preserving block-level line breaks. It never clones or
 * mutates the page (an earlier version read innerText off a detached clone,
 * which is unreliable — innerText needs a rendered layout).
 */

// Upper bound on returned text. A job description is rarely over ~10k chars;
// 30k is generous headroom while keeping the backend AI payload lean.
const MAX_CHARS = 30000;

// Minimum length (chars) for a JSON-LD description to be trusted as the body
// text rather than falling back to readable extraction.
const MIN_JSONLD_DESCRIPTION = 200;

// Elements that are almost always noise, removed during text extraction.
const NOISE_SELECTORS = [
  "nav",
  "header",
  "footer",
  "aside",
  "form",
  "button",
  "[role='navigation']",
  "[role='banner']",
  "[role='contentinfo']",
  "[role='complementary']",
  "[aria-hidden='true']",
  "[class*='cookie']",
  "[id*='cookie']",
  "[class*='consent']",
  "[class*='breadcrumb']",
  "[class*='newsletter']",
  "[class*='social']",
  "script",
  "style",
  "noscript",
  "svg",
  "iframe",
  "template",
];

// Block-level tags used to insert line breaks during text extraction.
const BLOCK_TAGS = new Set([
  "ADDRESS", "ARTICLE", "ASIDE", "BLOCKQUOTE", "DD", "DETAILS", "DIV", "DL",
  "DT", "FIELDSET", "FIGCAPTION", "FIGURE", "FOOTER", "FORM", "H1", "H2", "H3",
  "H4", "H5", "H6", "HEADER", "HR", "LI", "MAIN", "NAV", "OL", "P", "PRE",
  "SECTION", "TABLE", "TR", "UL",
]);

// Candidate containers, in rough priority, for readable extraction.
const CONTENT_SELECTORS = [
  "main",
  "[role='main']",
  "article",
  "[class*='job-description']",
  "[class*='jobDescription']",
  "[class*='job-details']",
  "[class*='jobDetails']",
  "[id*='job-description']",
  "[id*='jobDescription']",
  "[class*='description']",
  "[class*='posting']",
  "[class*='content']",
  "[id*='content']",
  "section",
];

// ---------------------------------------------------------------------------
// Visibility & text helpers
// ---------------------------------------------------------------------------

/** Is an element hidden by CSS? (display:none / visibility:hidden / opacity:0) */
function isHidden(el) {
  const style = getComputedStyle(el);
  return (
    style.display === "none" ||
    style.visibility === "hidden" ||
    style.opacity === "0"
  );
}

/** Nearest block-level ancestor of a node, bounded by `root`. */
function closestBlock(el, root) {
  let cur = el;
  while (cur && cur !== root) {
    if (BLOCK_TAGS.has(cur.tagName)) return cur;
    cur = cur.parentElement;
  }
  return root;
}

/** Collapse excess whitespace while preserving paragraph breaks. */
function normalise(text) {
  return text
    .replace(/\r/g, "")
    .replace(/[ \t\f\v]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/**
 * Extract visible text from a live element, skipping hidden and noise nodes
 * and inserting newlines at block boundaries. Does not mutate the page.
 */
function extractText(root) {
  if (!root) return "";

  const noise = new Set();
  for (const sel of NOISE_SELECTORS) {
    for (const node of root.querySelectorAll(sel)) noise.add(node);
  }

  const walker = document.createTreeWalker(
    root,
    NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT,
    {
      acceptNode(node) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.tagName === "BR") return NodeFilter.FILTER_ACCEPT;
          // REJECT prunes the whole subtree — drop noise and hidden branches.
          if (noise.has(node) || isHidden(node)) return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_SKIP; // visit children, ignore the tag itself
        }
        return node.textContent.trim()
          ? NodeFilter.FILTER_ACCEPT
          : NodeFilter.FILTER_REJECT;
      },
    }
  );

  const parts = [];
  let prevBlock = null;

  while (walker.nextNode()) {
    const node = walker.currentNode;

    if (node.nodeType === Node.ELEMENT_NODE) {
      // Only BR reaches here — treat as a hard line break.
      parts.push("\n");
      prevBlock = null;
      continue;
    }

    const chunk = node.textContent.replace(/\s+/g, " ").trim();
    if (!chunk) continue;

    const block = closestBlock(node.parentElement, root);
    if (parts.length) parts.push(block !== prevBlock ? "\n" : " ");
    parts.push(chunk);
    prevBlock = block;
  }

  return parts.join("");
}

/** Convert an HTML fragment (e.g. a JSON-LD description) to clean text. */
function htmlToText(html) {
  if (!html || typeof html !== "string") return "";
  // If it contains no tags it's already plain text — skip the parse.
  if (!/[<>&]/.test(html)) return normalise(html);

  const doc = new DOMParser().parseFromString(html, "text/html");
  // Preserve structure: turn block boundaries into newlines before reading
  // textContent (reliable, unlike innerText on a non-rendered document).
  for (const br of doc.body.querySelectorAll("br")) br.replaceWith("\n");
  for (const el of doc.body.querySelectorAll("p, div, li, h1, h2, h3, h4, h5, h6, tr, section")) {
    el.append("\n");
  }
  return normalise(doc.body.textContent || "");
}

// ---------------------------------------------------------------------------
// Structured data (JSON-LD) extraction
// ---------------------------------------------------------------------------

/** Collect every JobPosting node from the page's JSON-LD blocks. */
function collectJobPostings() {
  const postings = [];
  for (const el of document.querySelectorAll('script[type="application/ld+json"]')) {
    let json;
    try {
      json = JSON.parse(el.textContent || "");
    } catch {
      continue; // malformed JSON-LD — skip
    }
    const stack = Array.isArray(json) ? [...json] : [json];
    while (stack.length) {
      const node = stack.pop();
      if (!node || typeof node !== "object") continue;
      if (Array.isArray(node["@graph"])) stack.push(...node["@graph"]);
      const types = Array.isArray(node["@type"]) ? node["@type"] : [node["@type"]];
      if (types.includes("JobPosting")) postings.push(node);
    }
  }
  return postings;
}

function orgName(org) {
  if (!org) return null;
  if (typeof org === "string") return org.trim();
  if (Array.isArray(org)) return orgName(org[0]);
  return typeof org.name === "string" ? org.name.trim() : null;
}

function jobLocation(loc) {
  if (!loc) return null;
  if (Array.isArray(loc)) {
    return loc.map(jobLocation).filter(Boolean).join("; ") || null;
  }
  const addr = loc.address || loc;
  if (typeof addr === "string") return addr.trim();
  const parts = [addr.addressLocality, addr.addressRegion, addr.addressCountry]
    .filter((p) => typeof p === "string" && p.trim());
  return parts.join(", ") || null;
}

function salary(baseSalary) {
  if (!baseSalary) return null;
  if (typeof baseSalary === "string" || typeof baseSalary === "number") {
    return String(baseSalary);
  }
  const currency = baseSalary.currency || baseSalary.value?.currency || "";
  const v = baseSalary.value || baseSalary;
  let amount = null;
  if (v.value != null) {
    amount = `${v.value}`;
  } else if (v.minValue != null || v.maxValue != null) {
    amount = `${v.minValue ?? "?"}–${v.maxValue ?? "?"}`;
  }
  if (!amount) return null;
  const unit = typeof v.unitText === "string" ? `per ${v.unitText.toLowerCase()}` : "";
  return [currency, amount, unit].filter(Boolean).join(" ").trim();
}

function employmentType(et) {
  if (!et) return null;
  return Array.isArray(et) ? et.join(", ") : String(et);
}

/** Parse a JobPosting node into our structured shape (+ description text). */
function parseJobPosting(node) {
  const remote = node.jobLocationType === "TELECOMMUTE";
  return {
    title: typeof node.title === "string" ? node.title.trim() : null,
    company: orgName(node.hiringOrganization),
    location: jobLocation(node.jobLocation) || (remote ? "Remote" : null),
    remote: remote || undefined,
    employmentType: employmentType(node.employmentType),
    salary: salary(node.baseSalary),
    datePosted: typeof node.datePosted === "string" ? node.datePosted : null,
    validThrough: typeof node.validThrough === "string" ? node.validThrough : null,
    description: htmlToText(node.description || ""),
  };
}

/**
 * Build the tidy structured object surfaced in the result: drop the big
 * description (it lives in `text`), backfill title from OpenGraph if missing,
 * and remove empty fields. Returns null if nothing useful remains.
 */
function buildStructured(parsed) {
  const s = parsed ? { ...parsed } : {};
  delete s.description;

  if (!s.title) {
    const og = document.querySelector("meta[property='og:title']")?.content;
    if (og) s.title = og.trim();
  }
  if (!s.company) {
    const site = document.querySelector("meta[property='og:site_name']")?.content;
    if (site) s.company = site.trim();
  }

  const out = {};
  for (const [key, value] of Object.entries(s)) {
    if (value !== null && value !== undefined && value !== "") out[key] = value;
  }
  return Object.keys(out).length ? out : null;
}

// ---------------------------------------------------------------------------
// Readable content selection
// ---------------------------------------------------------------------------

const POSITIVE_HINT = /(job|descript|posting|detail|requirement|responsib|qualif|content|main)/;
const NEGATIVE_HINT = /(nav|menu|footer|header|sidebar|comment|cookie|consent|banner|promo|advert|related|share|social|breadcrumb|subscribe|newsletter)/;

/** Readability-style score for a candidate content container. */
function scoreElement(el) {
  if (isHidden(el)) return 0;

  // Cheap prefilter before the (layout-forcing) innerText read.
  if ((el.textContent || "").length < 200) return 0;

  // innerText reflects only visible text (best at runtime); fall back to
  // textContent where innerText is unavailable.
  const text = el.innerText || el.textContent || "";
  const len = text.length;
  if (len < 200) return 0;

  let linkLen = 0;
  for (const a of el.querySelectorAll("a")) linkLen += (a.textContent || "").length;
  const linkDensity = Math.min(linkLen / len, 1);

  let score = len * (1 - linkDensity);
  const hint = `${el.className || ""} ${el.id || ""}`.toLowerCase();
  if (POSITIVE_HINT.test(hint)) score *= 1.5;
  if (NEGATIVE_HINT.test(hint)) score *= 0.25;
  return score;
}

/** Choose the highest-scoring content container, or fall back to <body>. */
function pickMainContent() {
  const seen = new Set();
  let best = null;
  let bestScore = 0;
  let scored = 0;

  for (const sel of CONTENT_SELECTORS) {
    for (const el of document.querySelectorAll(sel)) {
      if (seen.has(el)) continue;
      seen.add(el);
      if (++scored > 500) break; // safety bound on very large pages
      const score = scoreElement(el);
      if (score > bestScore) {
        bestScore = score;
        best = el;
      }
    }
  }
  return best || document.body;
}

// ---------------------------------------------------------------------------
// Truncation
// ---------------------------------------------------------------------------

/** Truncate to `max` chars on a word boundary where possible. */
function truncate(text, max) {
  if (text.length <= max) return { text, truncated: false };
  let cut = text.slice(0, max);
  const lastSpace = cut.lastIndexOf(" ");
  if (lastSpace > max * 0.8) cut = cut.slice(0, lastSpace);
  return { text: cut.trimEnd(), truncated: true };
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

function scrapePage() {
  // 1. Structured-first: pick the JobPosting with the richest description.
  const parsed = collectJobPostings()
    .map(parseJobPosting)
    .sort((a, b) => (b.description?.length || 0) - (a.description?.length || 0));
  const best = parsed[0] || null;

  let text = "";
  let source = "body";

  if (best && best.description && best.description.length >= MIN_JSONLD_DESCRIPTION) {
    text = best.description;
    source = "json-ld";
  }

  // 2. Readable extraction when structured text is missing/thin.
  if (!text) {
    const root = pickMainContent();
    text = extractText(root);
    source = root === document.body ? "body" : "readable";
  }

  text = normalise(text);

  const fullLength = text.length;
  const { text: finalText, truncated } = truncate(text, MAX_CHARS);
  const structured = buildStructured(best);

  return {
    url: location.href,
    title: structured?.title || document.title || null,
    scrapedAt: new Date().toISOString(),
    source, // "json-ld" | "readable" | "body" — provenance / quality signal
    structured, // { title, company, location, salary, employmentType, ... } | null
    length: fullLength,
    truncated,
    text: finalText,
  };
}
