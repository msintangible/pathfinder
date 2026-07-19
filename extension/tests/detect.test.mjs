/**
 * DOM tests for src/content/detect.js using jsdom.
 *
 * detect.js is a content script (plain script, no exports) that relies on
 * browser globals (document, location). We load it into a jsdom window per
 * fixture, same trick as scrape.test.mjs: eval the source via `new Function`
 * and return the functions we want to call. Tier functions aren't otherwise
 * exposed outside the file's closure — this lets us unit-test each tier in
 * isolation without changing production code.
 *
 * Fixtures are built from the real patterns hardcoded in detect.js
 * (ATS_URL_PATTERNS, JOB_HEADING_KEYWORDS, JOB_BODY_KEYWORDS,
 * APPLICATION_FIELD_RE) rather than invented HTML, so a test failure means
 * the actual production pattern broke.
 *
 * Run with: npm test
 */

import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// detect.js calls collectJsonLdNodesByType() (jsonld.js) and
// querySelectorAllDeep() (dom.js), both loaded before it into the same
// content-script global scope by manifest.json — concatenate all three here
// to mirror that load order.
const DOM_SRC = fs.readFileSync(path.join(__dirname, "../src/content/dom.js"), "utf8");
const JSONLD_SRC = fs.readFileSync(path.join(__dirname, "../src/content/jsonld.js"), "utf8");
const SRC = DOM_SRC + "\n" + JSONLD_SRC + "\n" + fs.readFileSync(path.join(__dirname, "../src/content/detect.js"), "utf8");

/**
 * Load detect.js against an HTML fixture and return its tier functions +
 * detect(). `setup`, if given, runs against the parsed document before the
 * tier functions are built — used to attach real shadow roots, which static
 * HTML markup can't declare.
 */
function makeDetector(html, url = "https://example.com/careers/some-role", setup) {
  const dom = new JSDOM(html, { url });
  const { window } = dom;
  // jsdom doesn't implement innerText (see scrape.test.mjs's note). detect.js's
  // hasJobBodyContent() reads document.body.innerText with no textContent
  // fallback (unlike scrape.js) — polyfill it here so that tier is actually
  // exercised in tests, matching its real-Chrome behaviour.
  Object.defineProperty(window.HTMLElement.prototype, "innerText", {
    configurable: true,
    get() {
      return this.textContent;
    },
  });
  if (setup) setup(window.document);
  const factory = new Function(
    "document", "location",
    `${SRC}\nreturn { detect, urlScore, matchedAtsName, isKnownNonJobHost, hasJobPostingJsonLd, hasApplicationForm, hasJobHeadings, hasJobBodyContent, hasJobMetaTags };`
  );
  return factory(window.document, window.location);
}

// --- tiny test runner (matches scrape.test.mjs) -----------------------------
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

const BLANK = `<!doctype html><html><head><title>Untitled</title></head><body></body></html>`;

// ---------------------------------------------------------------------------
// Tier 1 — urlScore()
// ---------------------------------------------------------------------------
test("urlScore: known ATS host (boards.greenhouse.io) scores 0.6", () => {
  const d = makeDetector(BLANK, "https://boards.greenhouse.io/acme/jobs/12345");
  assert(d.urlScore() === 0.6, `got ${d.urlScore()}`);
});

test("urlScore: linkedin.com/jobs/ path scores 0.6", () => {
  const d = makeDetector(BLANK, "https://www.linkedin.com/jobs/view/98765");
  assert(d.urlScore() === 0.6, `got ${d.urlScore()}`);
});

test("urlScore: indeed viewjob path scores 0.5", () => {
  const d = makeDetector(BLANK, "https://www.indeed.com/viewjob?jk=abc123");
  assert(d.urlScore() === 0.5, `got ${d.urlScore()}`);
});

test("urlScore: linkedin.com homepage (no /jobs/ path) scores 0", () => {
  const d = makeDetector(BLANK, "https://www.linkedin.com/feed/");
  assert(d.urlScore() === 0, `got ${d.urlScore()}`);
});

test("urlScore: unrelated site scores 0", () => {
  const d = makeDetector(BLANK, "https://example.com/careers/some-role");
  assert(d.urlScore() === 0, `got ${d.urlScore()}`);
});

test("matchedAtsName: boards.greenhouse.io reports 'Greenhouse'", () => {
  const d = makeDetector(BLANK, "https://boards.greenhouse.io/acme/jobs/12345");
  assert(d.matchedAtsName() === "Greenhouse", `got ${d.matchedAtsName()}`);
});

test("matchedAtsName: unrelated site reports null", () => {
  const d = makeDetector(BLANK, "https://example.com/careers/some-role");
  assert(d.matchedAtsName() === null, `got ${d.matchedAtsName()}`);
});

// ---------------------------------------------------------------------------
// Tier 2a — hasJobPostingJsonLd()
// ---------------------------------------------------------------------------
test("hasJobPostingJsonLd: true when a JobPosting block is present", () => {
  const html = `<!doctype html><html><head><title>x</title>
    <script type="application/ld+json">${JSON.stringify({
      "@context": "https://schema.org/",
      "@type": "JobPosting",
      title: "Backend Engineer",
    })}</script></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobPostingJsonLd() === true, "expected true");
});

test("hasJobPostingJsonLd: false with no JSON-LD at all", () => {
  const d = makeDetector(BLANK);
  assert(d.hasJobPostingJsonLd() === false, "expected false");
});

test("hasJobPostingJsonLd: false when JSON-LD present but not JobPosting", () => {
  const html = `<!doctype html><html><head><title>x</title>
    <script type="application/ld+json">${JSON.stringify({
      "@context": "https://schema.org/",
      "@type": "Organization",
      name: "Acme",
    })}</script></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobPostingJsonLd() === false, "expected false");
});

test("hasJobPostingJsonLd: malformed JSON-LD is swallowed, not thrown", () => {
  const html = `<!doctype html><html><head><title>x</title>
    <script type="application/ld+json">{ not: valid json </script></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobPostingJsonLd() === false, "expected false, not a throw");
});

test("hasJobPostingJsonLd: true for a JobPosting nested only inside @graph", () => {
  // Regression case for the jsonld.js dedupe: the previous detect.js-only
  // traversal didn't flatten @graph and would have missed this, even though
  // scrape.js's collectJobPostings() already handled it. Shared helper closes
  // that gap.
  const html = `<!doctype html><html><head><title>x</title>
    <script type="application/ld+json">${JSON.stringify({
      "@context": "https://schema.org/",
      "@graph": [
        { "@type": "Organization", name: "Acme" },
        { "@type": "JobPosting", title: "Backend Engineer" },
      ],
    })}</script></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobPostingJsonLd() === true, "expected true for @graph-nested JobPosting");
});

test("hasJobPostingJsonLd: true for a JobPosting script rendered inside an open shadow root", () => {
  const d = makeDetector(
    `<!doctype html><html><head><title>x</title></head><body><job-widget></job-widget></body></html>`,
    undefined,
    (document) => {
      const shadow = document.querySelector("job-widget").attachShadow({ mode: "open" });
      shadow.innerHTML = `<script type="application/ld+json">${JSON.stringify({
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        title: "Backend Engineer",
      })}</script>`;
    }
  );
  assert(d.hasJobPostingJsonLd() === true, "expected true for shadow-DOM-rendered JSON-LD");
});

// ---------------------------------------------------------------------------
// Tier 2b — hasApplicationForm()
// ---------------------------------------------------------------------------
test("hasApplicationForm: true for a 3+ field job application form", () => {
  const html = `<!doctype html><html><head><title>Apply</title></head><body>
    <form>
      <input name="first_name" />
      <input name="last_name" />
      <input name="resume" type="file" />
      <input name="email" />
    </form>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasApplicationForm() === true, "expected true");
});

test("hasApplicationForm: false when form has < 3 fields", () => {
  const html = `<!doctype html><html><head><title>Apply</title></head><body>
    <form>
      <input name="resume" type="file" />
      <input name="first_name" />
    </form>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasApplicationForm() === false, "expected false — under field threshold");
});

test("false positive guard: 3+ field newsletter/contact form does NOT count as an application form", () => {
  // Realistic contact-us / newsletter-signup shape: generic name/email/message
  // fields, none of which match APPLICATION_FIELD_RE (resume, cv, cover letter,
  // first/last name, linkedin, github, portfolio, work auth).
  const html = `<!doctype html><html><head><title>Contact us</title></head><body>
    <form>
      <input name="name" placeholder="Your name" />
      <input name="email" placeholder="Your email" />
      <textarea name="message" placeholder="Your message"></textarea>
    </form>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasApplicationForm() === false, "newsletter/contact form must not match");
});

test("hasApplicationForm: true for a job application form rendered inside an open shadow root", () => {
  const d = makeDetector(
    `<!doctype html><html><head><title>Apply</title></head><body><apply-widget></apply-widget></body></html>`,
    undefined,
    (document) => {
      const shadow = document.querySelector("apply-widget").attachShadow({ mode: "open" });
      shadow.innerHTML = `<form>
        <input name="first_name" />
        <input name="last_name" />
        <input name="resume" type="file" />
      </form>`;
    }
  );
  assert(d.hasApplicationForm() === true, "expected true for shadow-DOM-rendered application form");
});

// ---------------------------------------------------------------------------
// Tier 2c — hasJobHeadings()
// ---------------------------------------------------------------------------
test("hasJobHeadings: true when a heading contains job-description language", () => {
  const html = `<!doctype html><html><head><title>x</title></head><body>
    <h2>Responsibilities</h2><p>Own the payments pipeline.</p>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobHeadings() === true, "expected true");
});

test("hasJobHeadings: false with only generic headings", () => {
  const html = `<!doctype html><html><head><title>x</title></head><body>
    <h1>Welcome to Acme</h1><h2>Our story</h2>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobHeadings() === false, "expected false");
});

test("hasJobHeadings: true for a heading rendered inside an open shadow root", () => {
  const d = makeDetector(
    `<!doctype html><html><head><title>x</title></head><body><job-widget></job-widget></body></html>`,
    undefined,
    (document) => {
      const shadow = document.querySelector("job-widget").attachShadow({ mode: "open" });
      shadow.innerHTML = `<h2>Responsibilities</h2><p>Own the payments pipeline.</p>`;
    }
  );
  assert(d.hasJobHeadings() === true, "expected true for shadow-DOM-rendered heading");
});

// ---------------------------------------------------------------------------
// Tier 2d — hasJobBodyContent()
// ---------------------------------------------------------------------------
test("hasJobBodyContent: true at the 2-keyword threshold (years of experience + full-time)", () => {
  const html = `<!doctype html><html><head><title>x</title></head><body>
    <p>We're looking for someone with 5+ years of experience for this full-time position.</p>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobBodyContent() === true, "expected true at threshold");
});

test("hasJobBodyContent: false with only 1 matching keyword", () => {
  const html = `<!doctype html><html><head><title>x</title></head><body>
    <p>This role is remote.</p>
  </body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobBodyContent() === false, "expected false — below threshold");
});

// ---------------------------------------------------------------------------
// Tier 2e — hasJobMetaTags()
// ---------------------------------------------------------------------------
test("hasJobMetaTags: true via og:type containing 'job'", () => {
  const html = `<!doctype html><html><head><title>Acme Careers</title>
    <meta property="og:type" content="job" /></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobMetaTags() === true, "expected true via og:type");
});

test("hasJobMetaTags: true via <title> containing a heading keyword", () => {
  const html = `<!doctype html><html><head><title>Job Description – Backend Engineer</title></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobMetaTags() === true, "expected true via title");
});

test("hasJobMetaTags: false with a generic title and no og:type", () => {
  const html = `<!doctype html><html><head><title>Acme Inc.</title></head><body></body></html>`;
  const d = makeDetector(html);
  assert(d.hasJobMetaTags() === false, "expected false");
});

// ---------------------------------------------------------------------------
// Combined detect() confidence math
// ---------------------------------------------------------------------------
test("detect(): sums weighted signals correctly (applicationForm 0.25 + jobHeadings 0.2 = 0.45, over threshold)", () => {
  const html = `<!doctype html><html><head><title>Apply</title></head><body>
    <h2>Responsibilities</h2>
    <form>
      <input name="first_name" />
      <input name="last_name" />
      <input name="resume" type="file" />
    </form>
  </body></html>`;
  const d = makeDetector(html, "https://example.com/careers/some-role");
  const result = d.detect();
  assert(Math.abs(result.confidence - 0.45) < 1e-9, `confidence: ${result.confidence}`);
  assert(result.isJobPage === true, "0.45 should clear the 0.4 threshold");
  assert(result.signals.applicationForm === true, "signals.applicationForm");
  assert(result.signals.jobKeywords === true, "signals.jobKeywords (from headings)");
});

test("detect(): confidence clamps at 1.0 when signals overlap-sum past it", () => {
  const ld = { "@context": "https://schema.org/", "@type": "JobPosting", title: "SWE" };
  const html = `<!doctype html><html><head><title>x</title>
    <script type="application/ld+json">${JSON.stringify(ld)}</script></head><body>
    <form>
      <input name="first_name" /><input name="last_name" /><input name="resume" type="file" />
    </form>
  </body></html>`;
  // greenhouse (0.6) + json-ld (0.4) + applicationForm (0.25) = 1.25 -> clamps to 1
  const d = makeDetector(html, "https://boards.greenhouse.io/acme/jobs/1");
  const result = d.detect();
  assert(result.confidence === 1, `confidence should clamp at 1, got ${result.confidence}`);
});

test("detect(): below-threshold page (0 signals) is not a job page", () => {
  const d = makeDetector(BLANK, "https://example.com/about-us");
  const result = d.detect();
  assert(result.confidence === 0, `confidence: ${result.confidence}`);
  assert(result.isJobPage === false, "expected isJobPage false");
});

test("detect(): atsName is populated for a known ATS URL", () => {
  const d = makeDetector(BLANK, "https://jobs.lever.co/acme/12345");
  const result = d.detect();
  assert(result.atsName === "Lever", `got ${result.atsName}`);
});

test("detect(): atsName is null when the URL doesn't match a known ATS", () => {
  const d = makeDetector(BLANK, "https://example.com/careers/some-role");
  const result = d.detect();
  assert(result.atsName === null, `got ${result.atsName}`);
});

test("false positive guard: contact page with newsletter form + unrelated heading stays under threshold", () => {
  // Combines the false-positive form shape with a heading that happens to
  // share no job vocabulary — the scenario the report flags as the real risk
  // (a coincidental heading match tipping a non-job page over 0.4).
  const html = `<!doctype html><html><head><title>Contact Acme</title></head><body>
    <h1>Get in touch</h1>
    <form>
      <input name="name" placeholder="Your name" />
      <input name="email" placeholder="Your email" />
      <textarea name="message" placeholder="Your message"></textarea>
    </form>
  </body></html>`;
  const d = makeDetector(html, "https://example.com/contact");
  const result = d.detect();
  assert(result.isJobPage === false, `expected non-job page, got confidence ${result.confidence}`);
  assert(result.signals.applicationForm === false, "applicationForm signal must be false");
});

test("isKnownNonJobHost: recognizes each known AI chat host", () => {
  for (const url of [
    "https://claude.ai/chat/abc123",
    "https://chatgpt.com/c/abc123",
    "https://chat.openai.com/c/abc123",
    "https://gemini.google.com/app/abc123",
    "https://perplexity.ai/search/abc123",
  ]) {
    const d = makeDetector(BLANK, url);
    assert(d.isKnownNonJobHost() === true, `expected ${url} to be a known non-job host`);
  }
});

test("isKnownNonJobHost: an unrelated host is not flagged", () => {
  const d = makeDetector(BLANK, "https://smallstartup.example.com/careers/data-analyst");
  assert(d.isKnownNonJobHost() === false, "unrelated host must not match");
});

// A conversation on an AI chat tool where the assistant reviews a job
// posting: the response renders real headings/prose full of job-posting
// vocabulary, even though the page is a chat transcript, not a posting.
// See NON_JOB_HOSTS's comment in detect.js for the full mechanism.
const AI_CHAT_TRANSCRIPT_ABOUT_A_JOB = `<!doctype html><html><head><title>Data Analyst Job Description Review</title></head><body>
  <div class="chat-transcript">
    <div class="human-turn">Can you help me tailor my resume for this role? Here's the posting:
      Data Analyst - Full-time. Bachelor's degree required, 3+ years of experience.
      Competitive compensation and benefits include health insurance.
    </div>
    <div class="assistant-turn">
      <h2>About the role</h2>
      <p>This looks like a solid Data Analyst position. Here's a breakdown:</p>
      <h3>Requirements</h3>
      <ul><li>Bachelor's degree</li><li>3+ years of experience</li></ul>
      <h3>What you'll do</h3>
      <p>You will analyze datasets and build dashboards for stakeholders.</p>
    </div>
  </div>
</body></html>`;

test("false positive guard: a claude.ai conversation about a job posting is never flagged, regardless of keyword signals", () => {
  const d = makeDetector(AI_CHAT_TRANSCRIPT_ABOUT_A_JOB, "https://claude.ai/chat/abc123");
  const result = d.detect();
  assert(result.isJobPage === false, `expected non-job page, got confidence ${result.confidence}`);
  assert(result.confidence === 0, `expected confidence 0 (denylisted host short-circuits), got ${result.confidence}`);
  for (const key of ["urlMatch", "jsonLd", "applicationForm", "jobKeywords", "metaTags"]) {
    assert(result.signals[key] === false, `expected signals.${key} false on a denylisted host`);
  }
});

test("false positive guard: the same job-vocabulary-heavy content on a non-denylisted host still detects normally", () => {
  // Regression guard: the denylist must be scoped to the specific known
  // hosts, not a general suppression of Tier 2's keyword signals — a real
  // single-company careers page with the exact same shape of content
  // (headings + body keywords + a matching title, no ATS/schema/form) must
  // keep detecting, the way tests/fixtures/generic-no-ats.html does.
  const d = makeDetector(AI_CHAT_TRANSCRIPT_ABOUT_A_JOB, "https://smallstartup.example.com/careers/data-analyst");
  const result = d.detect();
  assert(result.isJobPage === true, `expected job page detected, got confidence ${result.confidence}`);
});

test("detect(): returns the stable contract (isJobPage/confidence/signals/url/detectedAt)", () => {
  const d = makeDetector(BLANK, "https://acme.com/careers/1");
  const result = d.detect();
  for (const key of ["isJobPage", "confidence", "signals", "url", "detectedAt"]) {
    assert(key in result, `missing key: ${key}`);
  }
  for (const key of ["urlMatch", "jsonLd", "applicationForm", "jobKeywords", "metaTags"]) {
    assert(key in result.signals, `missing signals key: ${key}`);
  }
  assert(result.url === "https://acme.com/careers/1", `url: ${result.url}`);
});

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
