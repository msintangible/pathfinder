/**
 * Download-success controller — Screen 12 in the redesign: the confirmation
 * shown after "Download resume" on Screen 4 (docs/pathfinder-uiux-
 * requirements.md's "Alt: Success — after download", built to mirror the
 * structure of the not-yet-built Screen 7).
 *
 * Not self-initializing like idle/index.js or detection/index.js — same
 * pattern as review/index.js: it has no state of its own to poll for, so
 * it's only ever shown by review/index.js's Download resume handler, with
 * that click's real title/company/kept-count/weekly-count.
 *
 * Both design mockups for this screen invent an example filename
 * ("Data_Analyst_Reperio.pdf") for the body copy. The backend's real
 * download filename is `resume-{uuid}.{ext}` (backend/api/v1/resume.py) —
 * not human-readable, and not something this screen should claim to know
 * precisely. The body names the real job/company instead, never a filename.
 *
 * Done's job, per the design, is "closes popup, returns to idle next open".
 * A side panel has no equivalent close/reopen lifecycle — chrome.sidePanel
 * exposes no way for a panel to close itself — so this reloads the document
 * instead. That re-runs every screen module's own self-initialization
 * (idle/index.js, detection/index.js, ...) exactly as a fresh open would,
 * which correctly re-derives whichever screen actually applies now (e.g.
 * Screen 2 again, if the same known-ATS job is still on the active tab) —
 * without this module needing to import and re-invoke every other screen's
 * internal refresh logic itself.
 */

import { pfHeader } from "../shared/header.js";

function getRoot() {
  return document.getElementById("success-screen-root");
}

function divider() {
  const el = document.createElement("div");
  el.className = "success-divider";
  return el;
}

function sectionLabel(text) {
  const el = document.createElement("div");
  el.className = "success-label";
  el.textContent = text.toUpperCase();
  return el;
}

/** Outlined (not filled) circle with a check — deliberately quieter than the
 *  filled markers used elsewhere (loading steps, autofill field markers). */
function statusIcon() {
  const el = document.createElement("div");
  el.className = "success-icon";
  el.innerHTML =
    '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">' +
    '<path d="M3 8.5L6.2 11.5L13 4.5" stroke="var(--text-3)" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>' +
    "</svg>";
  return el;
}

/** Real job/company only — never a fabricated filename (see module doc). */
function bodyText(title, company) {
  const jobPhrase = [title, company].filter(Boolean).join(" at ");
  return jobPhrase
    ? `Your resume for ${jobPhrase} was downloaded. Your original was left untouched.`
    : "Your resume was downloaded. Your original was left untouched.";
}

function statusBlock(title, company) {
  const el = document.createElement("div");
  el.className = "success-status";

  const heading = document.createElement("h2");
  heading.className = "success-heading";
  heading.textContent = "Resume downloaded";

  const body = document.createElement("p");
  body.className = "success-body";
  body.textContent = bodyText(title, company);

  el.append(statusIcon(), heading, body);
  return el;
}

function applicationSection(title, company, keptCount, totalCount) {
  const el = document.createElement("div");
  el.className = "success-section";
  el.appendChild(sectionLabel("This application"));

  const jobLine = [title, company].filter(Boolean).join(" · ");
  if (jobLine) {
    const p = document.createElement("p");
    p.className = "success-job-line";
    p.textContent = jobLine;
    el.appendChild(p);
  }

  const kept = document.createElement("p");
  kept.className = "success-kept-line";
  kept.textContent = `${keptCount} of ${totalCount} tailored changes kept`;
  el.appendChild(kept);

  return el;
}

function activitySection(weeklyCount) {
  const el = document.createElement("div");
  el.className = "success-section";
  el.appendChild(sectionLabel("Recent activity"));

  const row = document.createElement("div");
  row.className = "success-activity";

  const count = document.createElement("span");
  count.className = "success-activity__count";
  count.textContent = String(weeklyCount);

  const text = document.createElement("span");
  text.className = "success-activity__text";
  text.textContent = "applications tailored this week";

  row.append(count, text);
  el.appendChild(row);
  return el;
}

function footer(onDone) {
  const el = document.createElement("div");
  el.className = "success-footer";

  const button = document.createElement("button");
  button.className = "success-done-btn pf-btn pf-btn--block pf-btn--outline";
  button.textContent = "Done";
  button.addEventListener("click", onDone);

  el.appendChild(button);
  return el;
}

function buildScreen({ title, company, keptCount, totalCount, weeklyCount, onDone }) {
  const screen = document.createElement("div");
  screen.className = "success-screen";
  screen.appendChild(pfHeader());

  const main = document.createElement("div");
  main.className = "success-main";
  main.append(
    statusBlock(title, company),
    divider(),
    applicationSection(title, company, keptCount, totalCount),
    divider(),
    activitySection(weeklyCount),
    footer(onDone)
  );

  screen.appendChild(main);
  return screen;
}

/** See module doc: no per-module refresh to call, so this is the side
 *  panel's closest equivalent to "close and reopen". */
function handleDone() {
  window.location.reload();
}

export function hideDownloadSuccessScreen() {
  const root = getRoot();
  if (!root) return;
  root.hidden = true;
  root.innerHTML = "";
}

/**
 * Shows Screen 12 for a resume that was just downloaded from Screen 4.
 * @param {{ title?: string, company?: string, keptCount: number,
 *           totalCount: number, weeklyCount: number }} args
 */
export function showDownloadSuccessScreen({ title, company, keptCount, totalCount, weeklyCount }) {
  const root = getRoot();
  if (!root) return;

  const legacyRoot = document.getElementById("legacy-root");
  const idleRoot = document.getElementById("idle-root");
  const detectionScreenRoot = document.getElementById("detection-screen-root");
  const loadingRoot = document.getElementById("loading-screen-root");
  const reviewScreenRoot = document.getElementById("review-screen-root");
  if (legacyRoot) legacyRoot.hidden = true;
  if (idleRoot) idleRoot.hidden = true;
  if (detectionScreenRoot) detectionScreenRoot.hidden = true;
  if (loadingRoot) loadingRoot.hidden = true;
  if (reviewScreenRoot) reviewScreenRoot.hidden = true;

  root.innerHTML = "";
  root.appendChild(buildScreen({ title, company, keptCount, totalCount, weeklyCount, onDone: handleDone }));
  root.hidden = false;
}
