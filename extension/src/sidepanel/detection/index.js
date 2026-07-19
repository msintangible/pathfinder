/**
 * Detection controller — owns the "Current page" job-detection badge (legacy
 * fallback, debug builds also get the Tier-1/Tier-2 signal breakdown), and
 * the 3 job-page-ish full-screen states in the redesign: Known ATS, Unknown
 * ATS, Keywords only. The 4th detection state (true idle, zero confidence)
 * is idle/index.js's domain — see the note on loadDetection() below for how
 * the two modules avoid racing each other for the same tab.
 *
 * Detection goes through the service worker (TDD 6.1) via GET_DETECTION,
 * re-run whenever the active tab changes or finishes loading.
 *
 * The "Tailor my resume"/"Tailor with what's here" buttons drive the real
 * tailoring pipeline (analyze the job if needed, then generate) behind
 * loading/index.js's Screen 3. There is no Screen 4 (diff review) yet, so a
 * success currently falls back to revealing the legacy stack's own Optimize
 * CV result panel (optimize/index.js's existing renderResult, picked up
 * automatically via its chrome.storage.onChanged listener once
 * SAVE_RESUME_RESULT writes the result) — a deliberate temporary bridge,
 * not a stand-in for building the real diff-review screen.
 */

import { loadProfileId } from "../../shared/profileApi.js";
import { driveLoading, hideLoadingScreen } from "../loading/index.js";

/** Debug-only: the signals <dl>. Off by default, same as sidepanel.js. */
const DEBUG_MODE = false;

const root = document.getElementById("detection-root");
const screenRoot = document.getElementById("detection-screen-root");
const legacyRoot = document.getElementById("legacy-root");
const idleRoot = document.getElementById("idle-root");
const loadingRoot = document.getElementById("loading-screen-root");

/** Return the active tab (or null). */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

function badge(text, variant) {
  const span = document.createElement("span");
  span.className = `badge badge--${variant}`;
  span.textContent = text;
  return span;
}

/** The individual Tier-1/Tier-2 detection signals. */
function signalsList(signals) {
  const labels = {
    urlMatch: "Known ATS URL",
    jsonLd: "JobPosting data",
    applicationForm: "Application form",
    jobKeywords: "Job keywords",
  };
  const dl = document.createElement("dl");
  dl.className = "signals";
  for (const [key, label] of Object.entries(labels)) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = signals[key] ? "✓" : "—";
    dl.append(dt, dd);
  }
  return dl;
}

/** Re-render #detection-root from a badge element and (debug-only) signals. */
function render(badgeEl, signals) {
  if (!root) return;
  root.innerHTML = "";
  root.appendChild(badgeEl);
  if (DEBUG_MODE && signals) root.appendChild(signalsList(signals));
}

// ---------------------------------------------------------------------------
// Redesign: Known ATS / Unknown ATS / Keywords only full screens
// ---------------------------------------------------------------------------

const METER = {
  "known-ats": { label: "Strong match", filled: 3 },
  "unknown-ats": { label: "Partial match", filled: 2 },
  "keywords-only": { label: "Low match", filled: 1 },
};

/** Which of the 3 job-page-ish states applies, or null (idle/index.js's turn). */
function classify(detection) {
  if (detection.isJobPage && detection.signals.urlMatch) return "known-ats";
  if (detection.isJobPage && !detection.signals.urlMatch) return "unknown-ats";
  if (!detection.isJobPage && detection.confidence > 0) return "keywords-only";
  return null;
}

function header() {
  const el = document.createElement("div");
  el.className = "pf-header";

  const badgeEl = document.createElement("span");
  badgeEl.className = "pf-header__badge";
  badgeEl.textContent = "P";

  const name = document.createElement("span");
  name.className = "pf-header__name";
  name.textContent = "Pathfinder";

  el.append(badgeEl, name);
  return el;
}

function confidenceMeter(state) {
  const { label, filled } = METER[state];

  const wrap = document.createElement("div");
  wrap.className = "det-meter";

  const bars = document.createElement("div");
  bars.className = "det-meter__bars";
  for (let i = 0; i < 3; i++) {
    const bar = document.createElement("span");
    bar.className = "det-meter__bar" + (i < filled ? ` det-meter__bar--${state}` : "");
    bars.appendChild(bar);
  }

  const text = document.createElement("span");
  text.className = "det-meter__label";
  text.textContent = label;

  wrap.append(bars, text);
  return wrap;
}

const SYSTEM_LABEL = {
  "known-ats": "Known application system",
  "unknown-ats": "Unrecognised system",
  "keywords-only": "Keywords only",
};

function divider() {
  const el = document.createElement("div");
  el.className = "det-divider";
  return el;
}

function link(text, onClick) {
  const el = document.createElement("button");
  el.className = "det-link";
  el.textContent = text;
  el.addEventListener("click", onClick);
  return el;
}

/** Join list items into natural-language prose: "a", "a and b", "a, b, and c". */
function joinWithAnd(items) {
  if (items.length === 1) return items[0];
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")}, and ${items[items.length - 1]}`;
}

/** Honest, signal-derived "what's missing" copy for Unknown ATS — built from
 *  which detect.js signals are actually false, not the specific structured
 *  fields (location, salary range, ...) the mockup shows, since extracting
 *  those requires backend analysis this screen doesn't have. */
const MISSING_SIGNAL_LABELS = {
  jsonLd: "structured job data",
  applicationForm: "an application form",
  jobKeywords: "job description keywords",
  metaTags: "job metadata",
};

function missingSignalsCopy(signals) {
  const missing = Object.entries(MISSING_SIGNAL_LABELS)
    .filter(([key]) => !signals[key])
    .map(([, label]) => label);

  if (!missing.length) {
    return "Pathfinder found this listing, but couldn't confirm it against a known application system. It can still tailor from what's here.";
  }
  return `Pathfinder found this listing, but couldn't find: ${joinWithAnd(missing)}. It can still tailor from what's here.`;
}

/** jobAnalysis is stored per-tab, not per-URL (see the currentPageBlock doc
 *  below), so a stale analysis from a previous page on this same tab must
 *  never be treated as covering the page currently on screen. Shared by
 *  currentPageBlock (display) and handleTailor (deciding whether to skip
 *  re-analyzing before generating). */
function freshJobAnalysis(jobAnalysis, detection) {
  return jobAnalysis?.url === detection.url ? jobAnalysis : null;
}

/** Job title / company / ATS name / URL block — the middle three states share
 *  this shape. jobAnalysis is null until the user has run "Analyse this page"
 *  for this tab; there is no free/local way to get a title or company before
 *  that, so this falls back to a generic heading rather than fabricating one.
 *
 *  jobAnalysis is stored per-tab, not per-URL (see handlePageDetected in
 *  background/index.js — only cleared on tab close, not navigation), so a
 *  stale analysis from a previously-visited page on this same tab could
 *  otherwise show the wrong title/company here. Guarded below by comparing
 *  its stored url against the current detection.url. */
function currentPageBlock(state, detection, jobAnalysis) {
  const analysis = freshJobAnalysis(jobAnalysis, detection);

  const wrap = document.createElement("div");
  wrap.appendChild(headerLabel());
  wrap.appendChild(confidenceMeter(state));

  const system = document.createElement("p");
  system.className = "det-system";
  system.textContent = SYSTEM_LABEL[state];
  wrap.appendChild(system);

  const title = document.createElement("p");
  title.className = "det-title";
  title.textContent = analysis?.title || (state === "known-ats" ? "Job listing detected" : "Possible job listing");
  wrap.appendChild(title);

  const companyParts = [analysis?.company, state === "known-ats" ? detection.atsName : null].filter(Boolean);
  if (companyParts.length) {
    const company = document.createElement("p");
    company.className = "det-company";
    company.textContent = companyParts.join(" · ");
    wrap.appendChild(company);
  }

  const url = document.createElement("p");
  url.className = "det-url";
  url.textContent = detection.url || "";
  wrap.appendChild(url);

  return wrap;
}

function headerLabel() {
  const el = document.createElement("div");
  el.className = "det-label";
  el.textContent = "Current page";
  return el;
}

function spacer() {
  const el = document.createElement("div");
  el.className = "det-spacer";
  return el;
}

/** onClick is omitted for the keywords-only state on purpose — the design
 *  brief explicitly rules out full tailoring from thin data there ("Copy
 *  keywords instead" is a different, not-yet-built action, not this flow).
 *  Genuinely disabled rather than just unwired when there's no handler, so
 *  it visually reads as "not available yet" instead of silently doing
 *  nothing on click — same honesty rule as every other screen in this design. */
function tailorButton(className, text, onClick) {
  const btn = document.createElement("button");
  btn.className = className;
  btn.textContent = text;
  btn.disabled = !onClick;
  if (onClick) btn.addEventListener("click", onClick);
  return btn;
}

function buildKnownAtsScreen(detection, jobAnalysis, onViewProfile) {
  const screen = document.createElement("div");
  screen.className = "det-screen";
  screen.appendChild(header());

  const main = document.createElement("div");
  main.className = "det-main";
  main.appendChild(currentPageBlock("known-ats", detection, jobAnalysis));
  main.appendChild(divider());

  const body = document.createElement("p");
  body.className = "det-body";
  body.textContent = "Everything Pathfinder needs to tailor your resume is on this page.";
  main.appendChild(body);

  main.appendChild(spacer());
  main.appendChild(tailorButton("det-btn-primary", "Tailor my resume", () => handleTailor(detection, jobAnalysis)));
  main.appendChild(link("View profile", onViewProfile));

  screen.appendChild(main);
  return screen;
}

function buildUnknownAtsScreen(detection, jobAnalysis, onViewProfile) {
  const screen = document.createElement("div");
  screen.className = "det-screen";
  screen.appendChild(header());

  const main = document.createElement("div");
  main.className = "det-main";
  main.appendChild(currentPageBlock("unknown-ats", detection, jobAnalysis));
  main.appendChild(divider());

  const notice = document.createElement("div");
  notice.className = "det-notice";
  const noticeTitle = document.createElement("p");
  noticeTitle.className = "det-notice__title";
  noticeTitle.textContent = "Some details are missing";
  const noticeBody = document.createElement("p");
  noticeBody.className = "det-notice__body";
  noticeBody.textContent = missingSignalsCopy(detection.signals);
  notice.append(noticeTitle, noticeBody);
  main.appendChild(notice);

  main.appendChild(spacer());
  main.appendChild(
    tailorButton("det-btn-accent-outline", "Tailor with what's here", () => handleTailor(detection, jobAnalysis))
  );
  main.appendChild(link("View profile", onViewProfile));

  screen.appendChild(main);
  return screen;
}

function buildKeywordsOnlyScreen(detection, jobAnalysis, onViewProfile) {
  const screen = document.createElement("div");
  screen.className = "det-screen";
  screen.appendChild(header());

  const main = document.createElement("div");
  main.className = "det-main";
  main.appendChild(currentPageBlock("keywords-only", detection, jobAnalysis));
  main.appendChild(divider());

  const heading = document.createElement("p");
  heading.className = "det-heading";
  heading.textContent = "Not enough to tailor from";
  main.appendChild(heading);

  const body = document.createElement("p");
  body.className = "det-body";
  body.textContent =
    "Pathfinder found scattered keywords here, but not a full job description. Tailoring a resume from this would be guesswork.";
  main.appendChild(body);

  // No "Keywords found" pills — that needs skill/domain-keyword extraction,
  // which doesn't exist anywhere in this codebase yet. Known gap, same
  // reasoning as the title/company fallback above: no fabricated data.
  main.appendChild(divider());

  main.appendChild(spacer());
  main.appendChild(tailorButton("det-btn-secondary", "Copy keywords instead"));
  main.appendChild(link("View profile", onViewProfile));

  screen.appendChild(main);
  return screen;
}

// ---------------------------------------------------------------------------
// Tailoring (Screen 3: loading)
// ---------------------------------------------------------------------------

/** Scrape + analyze the given tab, same sequence as job-analysis/index.js's
 *  analyseJob(), and persist it the same way (SAVE_JOB_ANALYSIS, plus
 *  clearing any resume result left over from a previous job on this tab) so
 *  the rest of the extension can't tell the difference from a manual
 *  "Analyse this page" click. Returns the new job id, or throws — driveLoading
 *  turns a throw into the error screen, so error messages here are meant to
 *  be read directly by the user, which is why res.error (raw "HTTP 500: {...}"
 *  text from background/api.js) is logged for debugging but never thrown
 *  as-is — see docs/pathfinder-uiux-requirements.md's Voice rule: "No raw
 *  error strings/JSON ever shown to users". */
async function analyzeCurrentTab(tab) {
  let scrape;
  try {
    // frameId: 0 pins this to the top-level frame — see job-analysis/index.js.
    scrape = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE_PAGE" }, { frameId: 0 });
  } catch {
    throw new Error("Can't read this page — reload the tab and try again.");
  }
  if (!scrape?.text) throw new Error("No text scraped from this page.");

  const res = await chrome.runtime.sendMessage({
    type: "ANALYZE_JOB",
    payload: { raw_text: scrape.text, url: scrape.url },
  });
  if (!res?.ok) {
    console.error("ANALYZE_JOB failed:", res?.error);
    throw new Error("Couldn't read this job posting. Try again.");
  }

  await chrome.runtime.sendMessage({
    type: "SAVE_JOB_ANALYSIS",
    payload: { tabId: tab.id, id: res.data.id, title: res.data.title, company: res.data.company, url: scrape.url },
  });
  await chrome.runtime.sendMessage({
    type: "SAVE_RESUME_RESULT",
    payload: { tabId: tab.id, data: null },
  });
  return res.data.id;
}

/** Same GENERATE_RESUME + SAVE_RESUME_RESULT sequence as optimize/index.js's
 *  optimizeCv(), so the legacy Optimize CV panel picks up this result the
 *  same way it picks up its own — see the module doc's note on the bridge.
 *  Same raw-error handling as analyzeCurrentTab above: res.error is logged,
 *  never thrown as-is. */
async function generateResumeFor(tab, profileId, jobId) {
  const res = await chrome.runtime.sendMessage({
    type: "GENERATE_RESUME",
    payload: { user_profile_id: profileId, job_id: jobId },
  });
  if (!res?.ok) {
    console.error("GENERATE_RESUME failed:", res?.error);
    throw new Error("Couldn't generate your resume. Try again.");
  }

  await chrome.runtime.sendMessage({
    type: "SAVE_RESUME_RESULT",
    payload: { tabId: tab.id, data: res.data },
  });
  return res.data;
}

/** "Tailor my resume" / "Tailor with what's here" handler. Analyzes the
 *  current tab first only if its saved job analysis is missing or stale
 *  (see freshJobAnalysis), then generates — both driven behind the Screen 3
 *  loading UI. `detection`/`jobAnalysis` are captured at the moment the
 *  button was rendered, matching every other handler in this module. */
async function handleTailor(detection, jobAnalysis) {
  const analysis = freshJobAnalysis(jobAnalysis, detection);
  const startTab = await getActiveTab();
  if (!startTab) return;

  // Claim the panel outright for the loading screen, same reasoning as
  // showDetectionScreen/showLegacyScreen claiming it for their own states.
  if (screenRoot) screenRoot.hidden = true;
  if (legacyRoot) legacyRoot.hidden = true;
  if (idleRoot) idleRoot.hidden = true;

  const task = async () => {
    const profileId = await loadProfileId();
    if (!profileId) throw new Error("Import your profile before tailoring a resume.");

    const jobId = analysis ? analysis.id : await analyzeCurrentTab(startTab);
    return generateResumeFor(startTab, profileId, jobId);
  };

  const outcome = await driveLoading(task, { onRetry: () => handleTailor(detection, jobAnalysis) });
  if (!outcome.ok) return; // error screen (with Try again) is already showing itself

  hideLoadingScreen();
  // The user may have switched tabs mid-request — if so, chrome.tabs.onActivated
  // already re-ran loadDetection() for whichever tab is active now, and that
  // already-correct screen must not be clobbered by this stale request's result.
  const stillActive = await getActiveTab();
  if (stillActive?.id === startTab.id) showLegacyScreen();
}

/** "View profile" has no dedicated screen in this design pass — reveals the
 *  legacy stack, same behaviour as idle/index.js's View profile link. */
function showLegacyScreen() {
  if (screenRoot) {
    screenRoot.hidden = true;
    screenRoot.innerHTML = "";
  }
  // Defensive: a tailoring run may still have the loading screen up from
  // before the user switched to this tab — claim the panel outright, same
  // reasoning as idleRoot below.
  if (loadingRoot) loadingRoot.hidden = true;
  if (legacyRoot) legacyRoot.hidden = false;
}

function showDetectionScreen(state, detection, jobAnalysis) {
  if (!screenRoot || !legacyRoot) return;
  legacyRoot.hidden = true;
  // Defensive: the idle screen may still be visible from before the user
  // switched to this tab — claim the panel outright.
  if (idleRoot) idleRoot.hidden = true;
  if (loadingRoot) loadingRoot.hidden = true;

  screenRoot.innerHTML = "";
  const builders = {
    "known-ats": () => buildKnownAtsScreen(detection, jobAnalysis, showLegacyScreen),
    "unknown-ats": () => buildUnknownAtsScreen(detection, jobAnalysis, showLegacyScreen),
    "keywords-only": () => buildKeywordsOnlyScreen(detection, jobAnalysis, showLegacyScreen),
  };
  screenRoot.appendChild(builders[state]());
  screenRoot.hidden = false;
}

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------

/**
 * Ask the service worker for the active tab's detection result, render the
 * legacy badge (unchanged), and — for the 3 job-page-ish states — take over
 * the full panel with the matching redesign screen.
 *
 * Zero-confidence pages are idle/index.js's domain: this function no-ops on
 * the screen-routing decision for that case (still renders the legacy badge)
 * rather than falling back to legacy itself, so the two modules can't
 * contradict each other about which root should be visible.
 */
async function loadDetection() {
  const tab = await getActiveTab();
  if (!tab) {
    render(badge("No active tab", "neutral"), null);
    showLegacyScreen();
    return;
  }

  const res = await chrome.runtime.sendMessage({
    type: "GET_DETECTION",
    payload: { tabId: tab.id },
  });
  const detection = res?.detection;

  if (!detection) {
    render(badge("Not analysed", "neutral"), null);
    showLegacyScreen();
    return;
  }

  const b = detection.isJobPage
    ? badge(`Job page (${Math.round(detection.confidence * 100)}%)`, "ok")
    : badge("Not a job page", "warn");
  render(b, detection.signals);

  const state = classify(detection);
  if (!state) return; // zero confidence — idle/index.js's turn, don't touch legacy/screen roots

  const jobAnalysisRes = await chrome.runtime.sendMessage({
    type: "GET_JOB_ANALYSIS",
    payload: { tabId: tab.id },
  });
  showDetectionScreen(state, detection, jobAnalysisRes?.jobAnalysis ?? null);
}

// Auto-refresh when the user switches tabs, a page finishes loading, or an
// SPA route change updates the URL without a full navigation (History API
// pushState — changeInfo.status never re-enters "complete" for that case,
// only changeInfo.url is set, so both are checked).
chrome.tabs.onActivated.addListener(loadDetection);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.status === "complete" || changeInfo.url)) {
    loadDetection();
  }
});

loadDetection();
