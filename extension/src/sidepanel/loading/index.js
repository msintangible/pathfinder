/**
 * Loading screen controller — Screen 3 of the tailoring flow ("Loading — real
 * sub-steps with checkmarks, not a generic spinner", docs/pathfinder-uiux-
 * requirements.md:17).
 *
 * The backend has no per-step progress signal: POST /v1/resumes/generate
 * (backend/api/v1/resume.py's generate_resume) is one synchronous
 * request/response, and PRODUCTION_READINESS_REVIEW.md documents moving it
 * to a queue with real progress reporting as unbuilt future work. So the
 * checkmarks below are a paced *estimate*, not live backend status — the
 * "Estimated steps" caption says so, and the driver's actual honesty
 * boundary is real start (driveLoading() called) / real end (task()
 * settling): the final step is deliberately never auto-checked by the
 * pacing timers, only by task() actually resolving, and a rejection stops
 * everything immediately and shows the real error rather than letting the
 * pacing finish first.
 *
 * The 3 step labels below are drawn from ResumeGenerationAgent.generate()'s
 * real internal phases (backend/services/resume_generation_agent.py), not
 * invented copy:
 *
 *   Label here                                  | Real source
 *   ---------------------------------------------|--------------------------------------------------------------
 *   "Matching your resume to the listing"         | generate(), lines 169-170: `match_keywords(profile, job)`
 *                                                  | then `rank_profile(profile, keyword_report)`.
 *   "Rewriting content for ATS relevance"         | generate(), line 173: `await self._optimize(...)` — the
 *                                                  | Gemini call against _SYSTEM_PROMPT ("You are a professional
 *                                                  | resume editor... ATS keyword test..."). Confirmed as the
 *                                                  | dominant-cost step by PRODUCTION_READINESS_REVIEW.md:272
 *                                                  | ("currently the single largest latency risk since it's
 *                                                  | unbounded") and by live timing during this change (~85% of
 *                                                  | the ~1.6-1.8s measured total against a small test profile).
 *   "Applying edits to your document"             | generate(), lines 175 & 182: `apply_patches(layout, patches)`
 *                                                  | then `self._build_render_layout(...)`, plus the docx/pdf
 *                                                  | in-place render in resume.py's `_render_resume()` that runs
 *                                                  | after generate() returns.
 */

import { Message } from "../../shared/constants.js";

// Looked up fresh on every call rather than cached at module scope: unlike
// idle/index.js and detection/index.js (each only ever imported directly,
// with a fresh cache-busted import per test), this module is meant to be
// imported *by* other controllers (detection/index.js does). A module-level
// `const root = document.getElementById(...)` would only ever be evaluated
// once per process — fine in the real extension (one document, one page
// load), but in tests, Node's module cache reuses that first-captured DOM
// node across every later test's fresh JSDOM document once any other module
// imports this one without its own cache-busted specifier.
function getRoot() {
  return document.getElementById("loading-screen-root");
}

/** Cumulative ms (from driveLoading() start) at which a step's checkmark
 *  appears — null means "never auto-checked", only real task() settlement
 *  checks it. Tuned against the live timing measured for this change. */
export const STEPS = [
  { label: "Matching your resume to the listing", checkAtMs: 600 },
  { label: "Rewriting content for ATS relevance", checkAtMs: 2400 },
  { label: "Applying edits to your document", checkAtMs: null },
];

function header() {
  const el = document.createElement("div");
  el.className = "pf-header";

  const badge = document.createElement("span");
  badge.className = "pf-header__badge";
  badge.textContent = "P";

  const name = document.createElement("span");
  name.className = "pf-header__name";
  name.textContent = "Pathfinder";

  el.append(badge, name);
  return el;
}

function stepIcon(state) {
  const el = document.createElement("span");
  el.className = `load-step__icon load-step__icon--${state}`;
  if (state === "done") el.textContent = "✓";
  else if (state === "active") el.appendChild(document.createElement("span")).className = "load-spinner";
  return el;
}

function stepRow(step, state) {
  const el = document.createElement("div");
  el.className = `load-step load-step--${state}`;
  el.appendChild(stepIcon(state));

  const label = document.createElement("span");
  label.className = "load-step__label";
  label.textContent = step.label;
  el.appendChild(label);

  return el;
}

function renderSteps(steps, stepStates) {
  const root = getRoot();
  if (!root) return;
  const list = root.querySelector(".load-steps");
  if (!list) return;
  list.innerHTML = "";
  steps.forEach((step, i) => list.appendChild(stepRow(step, stepStates[i])));
}

function buildScreen(steps, stepStates) {
  const screen = document.createElement("div");
  screen.className = "load-screen";
  screen.appendChild(header());

  const main = document.createElement("div");
  main.className = "load-main";

  const heading = document.createElement("h2");
  heading.className = "load-heading";
  heading.textContent = Message.GENERATING;
  main.appendChild(heading);

  const caption = document.createElement("p");
  caption.className = "load-caption";
  caption.textContent = "Estimated steps — not live status";
  main.appendChild(caption);

  const list = document.createElement("div");
  list.className = "load-steps";
  steps.forEach((step, i) => list.appendChild(stepRow(step, stepStates[i])));
  main.appendChild(list);

  screen.appendChild(main);
  return screen;
}

function buildErrorScreen(error, onRetry) {
  const screen = document.createElement("div");
  screen.className = "load-screen";
  screen.appendChild(header());

  const main = document.createElement("div");
  main.className = "load-main";

  const heading = document.createElement("h2");
  heading.className = "load-heading load-heading--error";
  heading.textContent = Message.GENERATE_FAILED;
  main.appendChild(heading);

  const body = document.createElement("p");
  body.className = "load-error-body";
  body.textContent = error?.message || String(error);
  main.appendChild(body);

  if (onRetry) {
    const retryBtn = document.createElement("button");
    retryBtn.className = "load-retry-btn";
    retryBtn.textContent = "Try again";
    retryBtn.addEventListener("click", onRetry);
    main.appendChild(retryBtn);
  }

  screen.appendChild(main);
  return screen;
}

function showLoadingScreen(steps, stepStates) {
  const root = getRoot();
  if (!root) return;
  root.innerHTML = "";
  root.appendChild(buildScreen(steps, stepStates));
  root.hidden = false;
}

function showError(error, onRetry) {
  const root = getRoot();
  if (!root) return;
  root.innerHTML = "";
  root.appendChild(buildErrorScreen(error, onRetry));
  root.hidden = false;
}

/** Hides the loading screen. Revealing whichever screen comes next is the
 *  caller's responsibility, same as every other redesign screen module. */
export function hideLoadingScreen() {
  const root = getRoot();
  if (!root) return;
  root.hidden = true;
  root.innerHTML = "";
}

/**
 * Shows the loading screen and runs `task`, pacing step checkmarks against
 * `steps` (defaults to STEPS) while it's in flight. Resolves with
 * `{ ok: true, result }` on success or `{ ok: false, error }` on failure —
 * never throws, so callers don't need a try/catch.
 *
 * The pacing timers only ever move a step from "active" to "done" and the
 * next step from "pending" to "active" — they're cleared the instant `task`
 * settles, and a step past the pacing schedule just stays "active" (spinner)
 * rather than silently marking itself done, since only a real result can
 * make that claim.
 *
 * `onRetry`, if given, is rendered as a "Try again" button on the error
 * screen and called on click — driveLoading itself doesn't re-run `task`,
 * the caller decides what retrying means (e.g. re-invoking its own handler).
 */
export async function driveLoading(task, { steps = STEPS, onRetry } = {}) {
  const stepStates = steps.map(() => "pending");
  stepStates[0] = "active";
  let settled = false;

  showLoadingScreen(steps, stepStates);

  const timers = steps
    .map((step, i) => {
      if (step.checkAtMs == null) return null;
      return setTimeout(() => {
        if (settled) return;
        stepStates[i] = "done";
        if (stepStates[i + 1] === "pending") stepStates[i + 1] = "active";
        renderSteps(steps, stepStates);
      }, step.checkAtMs);
    })
    .filter(Boolean);

  try {
    const result = await task();
    settled = true;
    timers.forEach(clearTimeout);
    renderSteps(steps, stepStates.fill("done"));
    return { ok: true, result };
  } catch (error) {
    settled = true;
    timers.forEach(clearTimeout);
    showError(error, onRetry);
    return { ok: false, error };
  }
}
