/**
 * DOM tests for src/content/scrape.js using jsdom.
 *
 * scrape.js is a content script (plain script, no exports) that relies on
 * browser globals (document, location, DOMParser, getComputedStyle, Node).
 * We load it into a jsdom window per fixture and call scrapePage().
 *
 * Note on jsdom: it does not implement HTMLElement.innerText, so scrape.js
 * falls back to textContent in the scorer — these tests therefore exercise the
 * structural logic (JSON-LD parsing, shadow-DOM-aware text extraction,
 * noise/hidden removal, container selection, truncation) rather than visual
 * rendering.
 *
 * Run with: npm test
 */

import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// scrape.js calls collectJsonLdNodesByType() (jsonld.js) and
// querySelectorAllDeep() (dom.js), both loaded before it into the same
// content-script global scope by manifest.json — concatenate all three here
// to mirror that load order.
const DOM_SRC = fs.readFileSync(path.join(__dirname, "../src/content/dom.js"), "utf8");
const JSONLD_SRC = fs.readFileSync(path.join(__dirname, "../src/content/jsonld.js"), "utf8");
const SRC = DOM_SRC + "\n" + JSONLD_SRC + "\n" + fs.readFileSync(path.join(__dirname, "../src/content/scrape.js"), "utf8");

/**
 * Load scrape.js against an HTML fixture and return scrapePage(). `setup`,
 * if given, runs against the parsed document before scrapePage is built —
 * used to attach real shadow roots, which static HTML markup can't declare.
 */
function makeScraper(html, url = "https://example.com/job/123", setup) {
  const dom = new JSDOM(html, { url });
  const { window } = dom;
  if (setup) setup(window.document);
  const factory = new Function(
    "document", "location", "getComputedStyle", "DOMParser", "Node",
    `${SRC}\nreturn { scrapePage, CONTENT_SELECTOR_OVERRIDES };`
  );
  const { scrapePage, CONTENT_SELECTOR_OVERRIDES } = factory(
    window.document,
    window.location,
    window.getComputedStyle.bind(window),
    window.DOMParser,
    window.Node
  );
  // Test-only escape hatch: lets override-map tests push a temporary entry
  // without touching the (deliberately empty-by-default) production array.
  scrapePage.overrides = CONTENT_SELECTOR_OVERRIDES;
  return scrapePage;
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
// 8. Shadow DOM traversal
// ---------------------------------------------------------------------------
test("shadow DOM: extracts job text rendered inside an open shadow root", () => {
  const jobText = "We are looking for a backend engineer with 5+ years of experience. ".repeat(6) +
    "Responsibilities include owning the payments pipeline. Remote and hybrid welcome. Full-time with great benefits.";
  const scrape = makeScraper(
    `<!doctype html><html><head><title>Job</title></head>
      <body><job-widget></job-widget></body></html>`,
    "https://acme.com/careers/1",
    (document) => {
      const host = document.querySelector("job-widget");
      const shadow = host.attachShadow({ mode: "open" });
      shadow.innerHTML = `<div class="job-description"><p>${jobText}</p></div>`;
    }
  );
  const r = scrape();
  assert(r.source === "readable", `source: ${r.source}`);
  assert(r.text.includes("payments pipeline"), `text missing shadow content: ${r.text.slice(0, 80)}`);
  assert(r.lowConfidence === false, "shadow-DOM job text should pass the quality floor");
});

test("shadow DOM: descends into a nested shadow root inside the picked container", () => {
  const jobText = "We are looking for a backend engineer with 5+ years of experience. ".repeat(6) +
    "Responsibilities include owning the payments pipeline. Remote and hybrid welcome. Full-time with great benefits.";
  const scrape = makeScraper(
    `<!doctype html><html><head><title>Job</title></head>
      <body><main class="job-description"><p>Intro paragraph long enough to score, padded padded padded padded padded padded.</p><inner-widget></inner-widget></main></body></html>`,
    "https://acme.com/careers/1",
    (document) => {
      const host = document.querySelector("inner-widget");
      const shadow = host.attachShadow({ mode: "open" });
      shadow.innerHTML = `<p>${jobText}</p>`;
    }
  );
  const r = scrape();
  assert(r.text.includes("payments pipeline"), `nested shadow content missing: ${r.text.slice(0, 80)}`);
});

test("shadow DOM: noise selectors are still respected inside a shadow root", () => {
  const jobText = "We are looking for a backend engineer with 5+ years of experience. ".repeat(6) +
    "Responsibilities include owning the payments pipeline. Remote and hybrid welcome. Full-time with great benefits.";
  const scrape = makeScraper(
    `<!doctype html><html><head><title>Job</title></head>
      <body><job-widget></job-widget></body></html>`,
    "https://acme.com/careers/1",
    (document) => {
      const host = document.querySelector("job-widget");
      const shadow = host.attachShadow({ mode: "open" });
      shadow.innerHTML =
        `<nav>Home About Contact</nav><div class="job-description"><p>${jobText}</p></div>`;
    }
  );
  const r = scrape();
  assert(!r.text.includes("Home About Contact"), `nav content should be stripped: ${r.text.slice(0, 120)}`);
  assert(r.text.includes("payments pipeline"), "job text should still be present");
});

// ---------------------------------------------------------------------------
// 9. Content-selector override map (escape hatch, see scrape.js's
//    CONTENT_SELECTOR_OVERRIDES)
// ---------------------------------------------------------------------------
test("override map: a URL-matched override reaches a container the generic selectors can't see", () => {
  const jobText = "We are looking for a backend engineer with 5+ years of experience. ".repeat(4) +
    "Responsibilities include owning the payments pipeline.";
  // Deliberately long filler so it wins on text-length scoring if it's the
  // only candidate the generic CONTENT_SELECTORS heuristics can find.
  const decoyText = "Generic filler content that is much longer than the real job body. ".repeat(10);
  const html = `<!doctype html><html><head><title>Job</title></head>
    <body>
      <div class="content"><p>${decoyText}</p></div>
      <div id="job-body"><p>${jobText}</p></div>
    </body></html>`;
  const scrape = makeScraper(html, "https://weird-ats.example.com/postings/42");

  // Sanity check: #job-body matches none of CONTENT_SELECTORS, so without an
  // override the generic pass only ever finds the decoy.
  const withoutOverride = scrape();
  assert(withoutOverride.text.includes("Generic filler"), "expected the decoy to win without an override");

  scrape.overrides.push({ pattern: /weird-ats\.example\.com\/postings\//, selector: "#job-body" });
  const withOverride = scrape();
  assert(withOverride.text.includes("payments pipeline"), `override should pick #job-body: ${withOverride.text.slice(0, 80)}`);
  assert(!withOverride.text.includes("Generic filler"), "override should not fall back to the decoy");
});

test("override map: a non-matching pattern is ignored, generic heuristics still run", () => {
  const html = `<!doctype html><html><head><title>Job</title></head>
    <body><div class="content"><p>${"Generic filler content. ".repeat(20)}</p></div></body></html>`;
  const scrape = makeScraper(html, "https://acme.com/careers/1");
  scrape.overrides.push({ pattern: /this-domain-is-not-in-the-url\.example/, selector: "#job-body" });
  const r = scrape();
  assert(r.text.includes("Generic filler"), "non-matching override must not block the generic fallback");
});

test("override map: a matched pattern whose selector finds nothing falls back to generic heuristics", () => {
  const html = `<!doctype html><html><head><title>Job</title></head>
    <body><div class="content"><p>${"Generic filler content. ".repeat(20)}</p></div></body></html>`;
  const scrape = makeScraper(html, "https://weird-ats.example.com/postings/99");
  scrape.overrides.push({ pattern: /weird-ats\.example\.com\/postings\//, selector: "#does-not-exist" });
  const r = scrape();
  assert(r.text.includes("Generic filler"), "an override match with no DOM hits should fall back, not return empty");
});

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
