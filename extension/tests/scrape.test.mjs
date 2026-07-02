/**
 * DOM tests for src/content/scrape.js using jsdom.
 *
 * scrape.js is a content script (plain script, no exports) that relies on
 * browser globals (document, location, DOMParser, TreeWalker, getComputedStyle,
 * NodeFilter, Node). We load it into a jsdom window per fixture and call
 * scrapePage().
 *
 * Note on jsdom: it does not implement HTMLElement.innerText, so scrape.js
 * falls back to textContent in the scorer — these tests therefore exercise the
 * structural logic (JSON-LD parsing, TreeWalker text extraction, noise/hidden
 * removal, container selection, truncation) rather than visual rendering.
 *
 * Run with: npm test
 */

import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// scrape.js calls collectJsonLdNodesByType(), declared in jsonld.js, which
// manifest.json loads first into the same content-script global scope —
// concatenate the two here to mirror that load order.
const JSONLD_SRC = fs.readFileSync(path.join(__dirname, "../src/content/jsonld.js"), "utf8");
const SRC = JSONLD_SRC + "\n" + fs.readFileSync(path.join(__dirname, "../src/content/scrape.js"), "utf8");

/** Load scrape.js against an HTML fixture and return scrapePage(). */
function makeScraper(html, url = "https://example.com/job/123") {
  const dom = new JSDOM(html, { url });
  const { window } = dom;
  const factory = new Function(
    "document", "location", "getComputedStyle", "DOMParser", "NodeFilter", "Node",
    `${SRC}\nreturn scrapePage;`
  );
  return factory(
    window.document,
    window.location,
    window.getComputedStyle.bind(window),
    window.DOMParser,
    window.NodeFilter,
    window.Node
  );
}

// --- tiny test runner -------------------------------------------------------
let pass = 0;
let fail = 0;
function test(name, fn) {
  try {
    fn();
    console.log(`✓ ${name}`);
    pass++;
  } catch (err) {
    console.log(`✗ ${name}\n    ${err.message}`);
    fail++;
  }
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

// ---------------------------------------------------------------------------
// 1. JSON-LD structured-first extraction
// ---------------------------------------------------------------------------
test("JSON-LD: extracts structured fields + clean description", () => {
  const ld = {
    "@context": "https://schema.org/",
    "@type": "JobPosting",
    title: "Lead Software Engineer",
    hiringOrganization: { "@type": "Organization", name: "Mastercard" },
    jobLocation: { address: { addressLocality: "Dublin", addressCountry: "Ireland" } },
    employmentType: "FULL_TIME",
    datePosted: "2026-06-01",
    baseSalary: { currency: "EUR", value: { value: 90000, unitText: "YEAR" } },
    // Realistic length: real JobPosting descriptions are hundreds+ chars, so
    // they clear the MIN_JSONLD_DESCRIPTION (200) guard that ignores teasers.
    description:
      "<p>" + "Build and scale payment systems used worldwide. ".repeat(8) +
      "</p><ul><li>Python</li><li>Go</li></ul>",
  };
  const scrape = makeScraper(`<!doctype html><html><head><title>MC</title>
    <script type="application/ld+json">${JSON.stringify(ld)}</script></head>
    <body><nav>Home About</nav><main>fallback text that should be ignored</main></body></html>`);
  const r = scrape();

  assert(r.source === "json-ld", `source should be json-ld, got ${r.source}`);
  assert(r.structured.title === "Lead Software Engineer", "title");
  assert(r.structured.company === "Mastercard", "company");
  assert(r.structured.location === "Dublin, Ireland", `location: ${r.structured.location}`);
  assert(r.structured.employmentType === "FULL_TIME", "employmentType");
  assert(r.structured.salary === "EUR 90000 per year", `salary: ${r.structured.salary}`);
  assert(!("description" in r.structured), "description must not be in structured");
  assert(r.text.includes("Build and scale payment systems") && r.text.includes("Python") && r.text.includes("Go"),
    `text from description: ${JSON.stringify(r.text)}`);
});

// ---------------------------------------------------------------------------
// 2. Multiple JobPostings — pick the richest description
// ---------------------------------------------------------------------------
test("JSON-LD: picks the posting with the longest description", () => {
  const thin = { "@type": "JobPosting", title: "Thin", description: "short one here ok" };
  const rich = { "@type": "JobPosting", title: "Rich",
    description: "A".repeat(300) };
  const scrape = makeScraper(`<!doctype html><html><head><title>x</title>
    <script type="application/ld+json">${JSON.stringify([thin, rich])}</script>
    </head><body></body></html>`);
  const r = scrape();
  assert(r.structured.title === "Rich", `expected Rich, got ${r.structured.title}`);
});

// ---------------------------------------------------------------------------
// 3. Readable extraction — strips noise, keeps job text
// ---------------------------------------------------------------------------
test("Readable: removes nav/footer noise, keeps description text", () => {
  const body = "We are hiring a backend engineer. ".repeat(20); // > 200 chars
  const scrape = makeScraper(`<!doctype html><html><head><title>Job</title></head>
    <body>
      <nav>Home Jobs Login NoiseNavWord</nav>
      <main class="job-description">
        <nav>InnerNavNoise</nav>
        <p>${body}</p>
        <p>Requirements: Python, SQL.</p>
      </main>
      <footer>FooterNoiseWord 2026</footer>
    </body></html>`);
  const r = scrape();
  assert(r.source === "readable", `source: ${r.source}`);
  assert(r.text.includes("backend engineer"), "keeps job text");
  assert(r.text.includes("Requirements: Python, SQL"), "keeps requirements");
  assert(!r.text.includes("NoiseNavWord"), "drops outer nav");
  assert(!r.text.includes("InnerNavNoise"), "drops nav nested inside main");
  assert(!r.text.includes("FooterNoiseWord"), "drops footer");
});

// ---------------------------------------------------------------------------
// 4. Hidden elements are skipped
// ---------------------------------------------------------------------------
test("Readable: skips display:none content", () => {
  const visible = "Visible job content about distributed systems. ".repeat(10);
  const scrape = makeScraper(`<!doctype html><html><head><title>Job</title></head>
    <body><article>
      <p>${visible}</p>
      <p style="display:none">HiddenSecretWord</p>
    </article></body></html>`);
  const r = scrape();
  assert(r.text.includes("distributed systems"), "keeps visible");
  assert(!r.text.includes("HiddenSecretWord"), "skips display:none");
});

// ---------------------------------------------------------------------------
// 5. Truncation at the cap
// ---------------------------------------------------------------------------
test("Truncation: caps text and reports full length", () => {
  const huge = "word ".repeat(10000); // ~50k chars
  const scrape = makeScraper(`<!doctype html><html><head><title>x</title></head>
    <body><article><p>${huge}</p></article></body></html>`);
  const r = scrape();
  assert(r.truncated === true, "truncated flag");
  assert(r.text.length <= 30000, `text length ${r.text.length} should be <= 30000`);
  assert(r.length > 30000, `length should be full (${r.length})`);
});

// ---------------------------------------------------------------------------
// 6. Always returns the stable contract
// ---------------------------------------------------------------------------
test("Contract: returns url/title/scrapedAt/source/length/truncated/lowConfidence/text", () => {
  const scrape = makeScraper(`<!doctype html><html><head><title>T</title></head>
    <body><p>tiny</p></body></html>`, "https://acme.com/careers/1");
  const r = scrape();
  for (const key of ["url", "title", "scrapedAt", "source", "length", "truncated", "lowConfidence", "text"]) {
    assert(key in r, `missing key: ${key}`);
  }
  assert(r.url === "https://acme.com/careers/1", `url: ${r.url}`);
  assert(typeof r.text === "string", "text is string");
});

// ---------------------------------------------------------------------------
// 7. Quality floor — lowConfidence flag
// ---------------------------------------------------------------------------
test("lowConfidence: true for short body-fallback text (nav junk shape)", () => {
  const scrape = makeScraper(`<!doctype html><html><head><title>x</title></head>
    <body><p>Hi there.</p></body></html>`);
  const r = scrape();
  assert(r.source === "body", `source: ${r.source}`);
  assert(r.lowConfidence === true, "short text should be flagged low confidence");
});

test("lowConfidence: true for long text with no job-shaped keyword overlap", () => {
  const filler = "The quick brown fox jumps over the lazy dog in the meadow. ".repeat(10);
  const scrape = makeScraper(`<!doctype html><html><head><title>x</title></head>
    <body><article><p>${filler}</p></article></body></html>`);
  const r = scrape();
  assert(r.length >= 150, `expected length over the floor, got ${r.length}`);
  assert(r.lowConfidence === true, "keyword-free long text should still be flagged");
});

test("lowConfidence: false for a real job-shaped extraction", () => {
  const body = "We are looking for a backend engineer with 5+ years of experience. ".repeat(10) +
    "Responsibilities include owning the payments pipeline. Remote and hybrid welcome. Full-time role with great benefits.";
  const scrape = makeScraper(`<!doctype html><html><head><title>Job</title></head>
    <body><main class="job-description"><p>${body}</p></main></body></html>`);
  const r = scrape();
  assert(r.lowConfidence === false, `expected false, length=${r.length}`);
});

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
