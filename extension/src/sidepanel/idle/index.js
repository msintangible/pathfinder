/**
 * Idle screen controller — Screen 1 in the redesign: "no job page, returning
 * user" state (docs/pathfinder-uiux-requirements.md, page-detection states).
 *
 * Shows only when the tab has zero detection confidence (truly no signal)
 * AND a profile already exists. Any non-zero confidence — including the
 * keywords-only state, which also has isJobPage === false — belongs to
 * detection/index.js's 3 job-page-ish screens; this module deliberately
 * no-ops rather than fall back to legacy in that case, so the two modules
 * can't race each other for the same tab. No profile yet (the "new user"
 * idle variant isn't built yet) falls back to the legacy always-visible
 * card stack, unchanged.
 *
 * Recent activity always shows 0 — there is no application-history tracking
 * anywhere in the codebase yet (checked extension storage and the backend
 * models). Wiring a real count is a follow-up once the tailoring flow
 * (screens 3-7) exists to produce something worth counting.
 */

import { loadProfile } from "../../shared/profileApi.js";

const root = document.getElementById("idle-root");
const legacyRoot = document.getElementById("legacy-root");

/** Return the active tab (or null). */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

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

function sectionLabel(text) {
  const el = document.createElement("div");
  el.className = "idle-label";
  el.textContent = text.toUpperCase();
  return el;
}

function divider() {
  const el = document.createElement("div");
  el.className = "idle-divider";
  return el;
}

/** The dot indicator + heading + body copy — the resting state, not styled as an alert. */
function statusBlock() {
  const el = document.createElement("div");
  el.className = "idle-status";

  const dot = document.createElement("div");
  dot.className = "idle-dot";
  const dotCenter = document.createElement("span");
  dotCenter.className = "idle-dot__center";
  dot.appendChild(dotCenter);

  const heading = document.createElement("h2");
  heading.className = "idle-heading";
  heading.textContent = "No job posting on this page";

  const body = document.createElement("p");
  body.className = "idle-body";
  body.textContent = "Open a job listing in this tab and Pathfinder reads it here automatically.";

  el.append(dot, heading, body);
  return el;
}

/** Quiet, factual trace of recent activity — always 0 today, see module doc. */
function activitySection() {
  const el = document.createElement("div");
  el.className = "idle-section";
  el.appendChild(sectionLabel("Recent activity"));

  const row = document.createElement("div");
  row.className = "idle-activity";

  const count = document.createElement("span");
  count.className = "idle-activity__count";
  count.textContent = "0";

  const text = document.createElement("span");
  text.className = "idle-activity__text";
  text.textContent = "applications tailored this week";

  row.append(count, text);
  el.appendChild(row);
  return el;
}

/** Profile status + the only action offered in this state. */
function profileSection(onViewProfile) {
  const el = document.createElement("div");
  el.className = "idle-profile";

  const info = document.createElement("div");
  info.appendChild(sectionLabel("Profile"));
  const status = document.createElement("p");
  status.className = "idle-profile__status";
  status.textContent = "Ready";
  info.appendChild(status);

  const button = document.createElement("button");
  button.className = "idle-btn-secondary";
  button.textContent = "View profile";
  button.addEventListener("click", onViewProfile);

  el.append(info, button);
  return el;
}

function buildScreen(onViewProfile) {
  const screen = document.createElement("div");
  screen.className = "idle-screen";
  screen.appendChild(header());

  const main = document.createElement("div");
  main.className = "idle-main";
  main.append(statusBlock(), divider(), activitySection(), divider(), profileSection(onViewProfile));

  screen.appendChild(main);
  return screen;
}

/** "View profile" has no dedicated screen in this design pass — it reveals
 *  the existing legacy stack, where profile/index.js already lives. */
function showLegacy() {
  root.hidden = true;
  root.innerHTML = "";
  legacyRoot.hidden = false;
}

function showIdleScreen() {
  legacyRoot.hidden = true;
  // Defensive: a detection-state screen (detection/index.js) may still be
  // visible from before the user switched to this tab — claim the panel outright.
  const detectionScreenRoot = document.getElementById("detection-screen-root");
  if (detectionScreenRoot) detectionScreenRoot.hidden = true;
  root.innerHTML = "";
  root.appendChild(buildScreen(showLegacy));
  root.hidden = false;
}

/** Re-check whether the idle screen applies to the active tab. */
async function evaluate() {
  const tab = await getActiveTab();
  if (!tab) {
    showLegacy();
    return;
  }

  const res = await chrome.runtime.sendMessage({
    type: "GET_DETECTION",
    payload: { tabId: tab.id },
  });
  const detection = res?.detection;
  if (!detection) {
    showLegacy();
    return;
  }

  // Any non-zero confidence belongs to detection/index.js's 3 job-page-ish
  // states (known ATS / unknown ATS / keywords only) — including the
  // keywords-only case, which also has isJobPage === false. Only a true
  // zero-signal page is this module's domain. Do nothing here otherwise;
  // detection/index.js owns the decision and will hide this screen if needed.
  if (detection.confidence > 0) return;

  const profile = await loadProfile();
  if (profile) {
    showIdleScreen();
  } else {
    showLegacy();
  }
}

// Auto-refresh when the user switches tabs, a page finishes loading, or an
// SPA route change updates the URL without a full navigation (History API
// pushState — changeInfo.status never re-enters "complete" for that case,
// only changeInfo.url is set, so both are checked) — same pattern as
// detection/index.js.
chrome.tabs.onActivated.addListener(evaluate);
chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  if (tab.active && (changeInfo.status === "complete" || changeInfo.url)) {
    evaluate();
  }
});

evaluate();
