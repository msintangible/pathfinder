/**
 * Idle screen controller — Screens 1 and 8 in the redesign: the two "no job
 * page" states, branching on whether a profile has been imported yet
 * (docs/pathfinder-uiux-requirements.md, page-detection states).
 *
 * Shows only when the tab has zero detection confidence (truly no signal).
 * Any non-zero confidence — including the keywords-only state, which also
 * has isJobPage === false — belongs to detection/index.js's 3 job-page-ish
 * screens; this module deliberately no-ops rather than claim the panel in
 * that case, so the two modules can't race each other for the same tab.
 *
 * Screen 8 (no profile) uses the reworked layout from "Pathfinder New
 * Screens.dc.html", not the original in README.md — the original's "View
 * profile" link has nothing to point to for a user who hasn't imported one
 * yet. The reworked version's "How it works" footer link is omitted rather
 * than shipped as a dead link, since no destination content exists for it.
 *
 * Recent activity (Screen 1 only) shows the real weekly count
 * (shared/weeklyCount.js), incremented so far only by review/index.js's
 * "Download resume" — the design's other trigger, a submitted autofill,
 * doesn't exist yet. At zero the whole section is omitted rather than shown
 * as "0" (design note: never a scolding empty state).
 */

import { loadProfile } from "../../shared/profileApi.js";
import { loadWeeklyCount } from "../../shared/weeklyCount.js";
import { pfHeader } from "../shared/header.js";

const root = document.getElementById("idle-root");
const legacyRoot = document.getElementById("legacy-root");

/** Return the active tab (or null). */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
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

/** Quiet, factual trace of recent activity. Caller omits this entirely at zero. */
function activitySection(weeklyCount) {
  const el = document.createElement("div");
  el.className = "idle-section";
  el.appendChild(sectionLabel("Recent activity"));

  const row = document.createElement("div");
  row.className = "idle-activity";

  const count = document.createElement("span");
  count.className = "idle-activity__count";
  count.textContent = String(weeklyCount);

  const text = document.createElement("span");
  text.className = "idle-activity__text";
  text.textContent = "applications tailored this week";

  row.append(count, text);
  el.appendChild(row);
  return el;
}

/** Document icon in a 40px outlined circle — Screen 8's icon, distinct from
 *  Screen 1's plain status dot (same circle, different content). */
function importIcon() {
  const dot = document.createElement("div");
  dot.className = "idle-dot";
  dot.innerHTML =
    '<svg width="17" height="17" viewBox="0 0 18 18" fill="none" aria-hidden="true">' +
    '<path d="M4.5 2.5 h6 l3 3 v10 h-9 z M10.5 2.5 v3 h3" stroke="var(--label)" stroke-width="1.4" stroke-linejoin="round"/>' +
    "</svg>";
  return dot;
}

/** Icon + heading + body + primary action — Screen 8's activation gate.
 *  Import CV is the only real action; everything else recedes to the footer. */
function newUserStatusBlock() {
  const el = document.createElement("div");
  el.className = "idle-status newuser-status";

  const heading = document.createElement("h2");
  heading.className = "idle-heading";
  heading.textContent = "Import your CV to get started";

  const body = document.createElement("p");
  body.className = "idle-body";
  body.textContent = "Pathfinder tailors this one CV to every job you open. Your original is never changed.";

  el.append(importIcon(), heading, body);
  return el;
}

function newUserAction(onImportCV) {
  const el = document.createElement("div");
  el.className = "newuser-action";

  const button = document.createElement("button");
  button.className = "newuser-import-btn pf-btn pf-btn--block pf-btn--fill";
  button.textContent = "Import CV";
  button.addEventListener("click", onImportCV);

  const caption = document.createElement("p");
  caption.className = "newuser-caption";
  caption.textContent = "Takes 30 seconds · PDF or Word";

  el.append(button, caption);
  return el;
}

/** Page status, demoted to a quiet footer line below the primary action. */
function newUserFooter() {
  const el = document.createElement("div");
  el.className = "newuser-footer";

  const status = document.createElement("p");
  status.className = "newuser-footer__status";
  status.textContent = "No job detected yet";

  el.appendChild(status);
  return el;
}

function buildNewUserScreen(onImportCV) {
  const screen = document.createElement("div");
  screen.className = "idle-screen";
  screen.appendChild(pfHeader());

  const main = document.createElement("div");
  main.className = "idle-main";
  main.append(newUserStatusBlock(), newUserAction(onImportCV), newUserFooter());

  screen.appendChild(main);
  return screen;
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
  button.className = "idle-btn-secondary pf-btn pf-btn--pill";
  button.textContent = "View profile";
  button.addEventListener("click", onViewProfile);

  el.append(info, button);
  return el;
}

function buildScreen(onViewProfile, weeklyCount) {
  const screen = document.createElement("div");
  screen.className = "idle-screen";
  screen.appendChild(pfHeader());

  const main = document.createElement("div");
  main.className = "idle-main";
  main.append(statusBlock(), divider());
  if (weeklyCount > 0) main.append(activitySection(weeklyCount), divider());
  main.append(profileSection(onViewProfile));

  screen.appendChild(main);
  return screen;
}

/** "View profile" has no dedicated screen in this design pass — it reveals
 *  the existing legacy stack, where profile/index.js already lives. */
function showLegacy() {
  root.hidden = true;
  root.innerHTML = "";
  legacyRoot.hidden = false;
  // Defensive: a finished review screen (review/index.js) may still be
  // visible from before the user switched to this tab — claim the panel outright.
  const reviewScreenRoot = document.getElementById("review-screen-root");
  if (reviewScreenRoot) reviewScreenRoot.hidden = true;
}

async function showIdleScreen() {
  legacyRoot.hidden = true;
  // Defensive: a detection-state, loading, or review screen may still be
  // visible from before the user switched to this tab — claim the panel outright.
  const detectionScreenRoot = document.getElementById("detection-screen-root");
  if (detectionScreenRoot) detectionScreenRoot.hidden = true;
  const reviewScreenRoot = document.getElementById("review-screen-root");
  if (reviewScreenRoot) reviewScreenRoot.hidden = true;
  const weeklyCount = await loadWeeklyCount();
  root.innerHTML = "";
  root.appendChild(buildScreen(showLegacy, weeklyCount));
  root.hidden = false;
}

/** Screen 8: no profile imported yet. "Import CV" reveals the legacy stack,
 *  same mechanism as Screen 1's "View profile" — that's where profile/index.js's
 *  import flow already lives. */
function showNewUserScreen() {
  legacyRoot.hidden = true;
  // Defensive: a detection-state or review screen may still be visible from
  // before the user switched to this tab — claim the panel outright.
  const detectionScreenRoot = document.getElementById("detection-screen-root");
  if (detectionScreenRoot) detectionScreenRoot.hidden = true;
  const reviewScreenRoot = document.getElementById("review-screen-root");
  if (reviewScreenRoot) reviewScreenRoot.hidden = true;
  root.innerHTML = "";
  root.appendChild(buildNewUserScreen(showLegacy));
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
    await showIdleScreen();
  } else {
    showNewUserScreen();
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
