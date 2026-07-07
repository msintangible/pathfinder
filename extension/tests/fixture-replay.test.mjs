/**
 * Fixture-replay integration suite.
 *
 * Unit tests in detect.test.mjs/scrape.test.mjs isolate one signal at a
 * time with minimal hand-built HTML. They don't prove the pipeline still
 * works against a realistic, full page for a given ATS/job board — noise
 * (nav, footers, cookie banners, related-jobs sidebars) and real class/id
 * naming conventions can interact in ways a narrow unit test can't catch.
 * This suite replays detect() + scrapePage() against one synthetic-but-
 * representative fixture per target platform (tests/fixtures/*.html) plus a
 * few true-negative shapes, so a structural regression in content/* shows up
 * here instead of the first time a real user visits that site.
 *
 * Fixtures are hand-built, not scraped from live sites: real ATS markup
 * changes constantly (making fixtures go stale) and copying real page HTML
 * verbatim has its own staleness/ToS wrinkles even anonymized. Each fixture
 * instead reproduces the platform's well-known structural pattern (its
 * typical class/id names, whether it embeds JSON-LD, its ATS URL shape).
 *
 * Run with: npm test
 */

import { JSDOM } from "jsdom";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONTENT_DIR = path.join(__dirname, "../src/content");
const FIXTURES_DIR = path.join(__dirname, "fixtures");

// Same load order as manifest.json's content_scripts array.
const SRC = ["dom.js", "jsonld.js", "detect.js", "scrape.js"]
  .map((f) => fs.readFileSync(path.join(CONTENT_DIR, f), "utf8"))
  .join("\n");

/** Load detect()+scrapePage() against a fixture file at the given URL. */
function replay(fixtureFile, url) {
  const html = fs.readFileSync(path.join(FIXTURES_DIR, fixtureFile), "utf8");
  const dom = new JSDOM(html, { url });
  const { window } = dom;
  // jsdom doesn't implement innerText; detect.js's hasJobBodyContent() reads
  // document.body.innerText directly (see detect.test.mjs for the same
  // polyfill/rationale).
  Object.defineProperty(window.HTMLElement.prototype, "innerText", {
    configurable: true,
    get() {
      return this.textContent;
    },
  });
  const factory = new Function(
    "document", "location", "getComputedStyle", "DOMParser", "Node",
    `${SRC}\nreturn { detect, scrapePage };`
  );
  return factory(
    window.document,
    window.location,
    window.getComputedStyle.bind(window),
    window.DOMParser,
    window.Node
  );
}

// --- tiny test runner (matches detect.test.mjs / scrape.test.mjs) ----------
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
// True positives — one fixture per representative platform shape
// ---------------------------------------------------------------------------
const POSITIVES = [
  {
    file: "greenhouse.html",
    url: "https://boards.greenhouse.io/acme/jobs/4521300",
    source: "json-ld",
    textIncludes: "payments infrastructure",
  },
  {
    file: "lever.html",
    url: "https://jobs.lever.co/acme/8f3c1a2b-1234-5678-9abc-def012345678",
    source: "readable",
    textIncludes: "checkout experience redesign",
  },
  {
    file: "workday.html",
    url: "https://acme.myworkdayjobs.com/en-US/AcmeCareers/job/Remote/Senior-Backend-Engineer_R00012345",
    source: "readable",
    textIncludes: "petabyte-scale data platform",
  },
  {
    file: "linkedin.html",
    url: "https://www.linkedin.com/jobs/view/3812345678",
    source: "json-ld",
    textIncludes: "growing the platform engineering team",
  },
  {
    file: "indeed.html",
    url: "https://www.indeed.com/viewjob?jk=abc123def456",
    source: "readable",
    textIncludes: "inbound support queue",
  },
  {
    file: "generic-jsonld.html",
    url: "https://careers.acmewidgets.example.com/jobs/senior-platform-engineer",
    source: "json-ld",
    textIncludes: "internal developer platform",
  },
  {
    file: "generic-no-ats.html",
    url: "https://smallstartup.example.com/careers/product-designer",
    source: "readable",
    textIncludes: "design system",
  },
];

for (const { file, url, source, textIncludes } of POSITIVES) {
  test(`${file}: detected as a job page`, () => {
    const { detect } = replay(file, url);
    const d = detect();
    assert(d.isJobPage === true, `expected isJobPage, confidence=${d.confidence}`);
  });

  test(`${file}: scrape picks up the expected content via '${source}'`, () => {
    const { scrapePage } = replay(file, url);
    const r = scrapePage();
    assert(r.source === source, `source: ${r.source}`);
    assert(r.text.includes(textIncludes), `missing "${textIncludes}": ${r.text.slice(0, 120)}`);
    assert(r.lowConfidence === false, `expected lowConfidence=false, length=${r.length}`);
  });
}

// ---------------------------------------------------------------------------
// True negatives — shapes that must NOT be detected as job pages
// ---------------------------------------------------------------------------
const NEGATIVES = [
  { file: "homepage.html", url: "https://acmewidgets.example.com/" },
  { file: "contact-form.html", url: "https://acmewidgets.example.com/contact" },
  { file: "blog-post.html", url: "https://acmewidgets.example.com/blog/five-tips-for-staying-productive" },
];

for (const { file, url } of NEGATIVES) {
  test(`${file}: NOT detected as a job page`, () => {
    const { detect } = replay(file, url);
    const d = detect();
    assert(d.isJobPage === false, `expected not a job page, confidence=${d.confidence}`);
  });
}

// ---------------------------------------------------------------------------
console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
