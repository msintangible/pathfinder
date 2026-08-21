/**
 * Review changes controller — Screen 4 in the redesign: the diff review
 * shown after a successful tailoring run (docs/pathfinder-uiux-
 * requirements.md: "Diff review — changed lines visually distinct from
 * unchanged original. Most important screen in the product.").
 *
 * Not self-initializing like idle/index.js or detection/index.js — it has
 * no state of its own to poll for, so it's only ever shown by
 * detection/index.js's handleTailor() once a tailoring run actually
 * succeeds, with that run's real result and job title/company.
 *
 * The Download resume button reuses shared/openResume.js — the only
 * mechanism this codebase has for getting the generated file — rather than
 * re-implementing it, then hands off to success/index.js's Screen 12 with
 * the kept-count as it stood at the moment of the click (reverts made after
 * downloading don't retroactively change what was actually in the file).
 * Revert swaps a row's own displayed text (see
 * shared/diffChangeRow.js) and updates the on-screen "kept" count, but it
 * doesn't regenerate the downloaded file (the backend has no endpoint to
 * exclude specific patches and re-render) — Download always returns the
 * full tailored version regardless of what's marked reverted here. That gap
 * is real and can't be closed from this side, so once any row is reverted,
 * downloadNotice() surfaces it plainly next to the Download button instead
 * of leaving the button to imply otherwise.
 *
 * The Fit Warning banner (Screen 13) sits above the diff when buildGaps.js
 * decides the tailored resume is a significant stretch — see that module
 * for why it's a single ungrouped bucket today, not the themed groups the
 * design shows.
 */

import { loadProfile } from "../../shared/profileApi.js";
import { incrementWeeklyCount } from "../../shared/weeklyCount.js";
import { pfHeader } from "../shared/header.js";
import { diffChangeRow } from "../shared/diffChangeRow.js";
import { fitWarningBanner } from "../shared/fitWarningBanner.js";
import { openResume } from "../shared/openResume.js";
import { showDownloadSuccessScreen } from "../success/index.js";
import { buildChanges } from "./buildChanges.js";
import { buildGaps } from "./buildGaps.js";

// Looked up fresh on every call rather than cached at module scope — this
// module is meant to be imported *by* detection/index.js (not directly, with
// its own cache-busted specifier per test), so a module-level `const root =
// document.getElementById(...)` would only ever be evaluated once per
// process. Same landmine, same fix, as loading/index.js's getRoot().
function getRoot() {
  return document.getElementById("review-screen-root");
}

function sectionLabel(text) {
  const el = document.createElement("div");
  el.className = "review-section-label";
  el.textContent = text.toUpperCase();
  return el;
}

function keptCountLine(total) {
  const el = document.createElement("p");
  el.className = "review-kept-count";
  el.textContent = `${total} of ${total} changes kept`;
  return el;
}

/** Amber "informational catch" — same semantic and styling as detection/index.js's
 *  Unknown ATS notice (not an error, just something worth knowing). Hidden until
 *  a revert makes it true, so the happy path (nothing reverted, the download
 *  really does match everything shown) stays uncluttered. */
function downloadNotice() {
  const el = document.createElement("div");
  el.className = "review-notice";
  el.hidden = true;

  const title = document.createElement("p");
  title.className = "review-notice__title";
  title.textContent = "Reverted changes still download";

  const body = document.createElement("p");
  body.className = "review-notice__body";
  body.textContent =
    "The download below always includes every change above, even ones you've reverted here. " +
    "Remove them from the file yourself after opening it.";

  el.append(title, body);
  return el;
}

function buildScreen(changes, title, company, downloadUrl, gaps) {
  const screen = document.createElement("div");
  screen.className = "review-screen";

  const header = document.createElement("div");
  header.className = "review-header";
  header.appendChild(pfHeader());

  const heading = document.createElement("h2");
  heading.className = "review-heading";
  heading.textContent = "Review changes";
  header.appendChild(heading);

  const subtitleText = [title, company].filter(Boolean).join(" · ");
  if (subtitleText) {
    const subtitle = document.createElement("p");
    subtitle.className = "review-subtitle";
    subtitle.textContent = subtitleText;
    header.appendChild(subtitle);
  }

  const reassurance = document.createElement("p");
  reassurance.className = "review-reassurance";
  reassurance.textContent =
    "Pathfinder rewords and reorders facts already in your profile. It never adds experience you don't have.";
  header.appendChild(reassurance);

  screen.appendChild(header);

  const scroll = document.createElement("div");
  scroll.className = "review-scroll";

  if (gaps) {
    scroll.appendChild(fitWarningBanner(gaps));
  }

  const reverted = new Set();
  const countLine = keptCountLine(changes.length);
  const notice = downloadNotice();

  changes.forEach((change, i) => {
    scroll.appendChild(sectionLabel(change.section));
    scroll.appendChild(
      diffChangeRow({
        reason: change.reason,
        newText: change.newText,
        oldText: change.oldText,
        onRevertClick: (_event, isReverted) => {
          if (isReverted) reverted.add(i);
          else reverted.delete(i);
          countLine.textContent = `${changes.length - reverted.size} of ${changes.length} changes kept`;
          notice.hidden = reverted.size === 0;
        },
      })
    );
  });

  screen.appendChild(scroll);

  const footer = document.createElement("div");
  footer.className = "review-footer";
  footer.appendChild(countLine);
  footer.appendChild(notice);

  const downloadBtn = document.createElement("button");
  downloadBtn.className = "review-download-btn pf-btn pf-btn--block pf-btn--fill";
  downloadBtn.textContent = "Download resume";
  downloadBtn.addEventListener("click", async () => {
    openResume(downloadUrl);
    const weeklyCount = await incrementWeeklyCount();
    showDownloadSuccessScreen({
      title,
      company,
      keptCount: changes.length - reverted.size,
      totalCount: changes.length,
      weeklyCount,
    });
  });
  footer.appendChild(downloadBtn);

  screen.appendChild(footer);
  return screen;
}

/** Hide every other known screen root — same defensive pattern every other
 *  redesign screen uses when it claims the panel. */
function claimPanel() {
  const legacyRoot = document.getElementById("legacy-root");
  const idleRoot = document.getElementById("idle-root");
  const detectionScreenRoot = document.getElementById("detection-screen-root");
  const loadingRoot = document.getElementById("loading-screen-root");
  if (legacyRoot) legacyRoot.hidden = true;
  if (idleRoot) idleRoot.hidden = true;
  if (detectionScreenRoot) detectionScreenRoot.hidden = true;
  if (loadingRoot) loadingRoot.hidden = true;
}

export function hideReviewScreen() {
  const root = getRoot();
  if (!root) return;
  root.hidden = true;
  root.innerHTML = "";
}

/**
 * Shows Screen 4 for a completed tailoring run.
 * @param {{ result: object, title?: string, company?: string }} args
 *   `result` is the GENERATE_RESUME response (ResumeGenerationResponse);
 *   `title`/`company` are the job's, for the header subtitle.
 */
export async function showReviewScreen({ result, title, company }) {
  const root = getRoot();
  if (!root) return;
  claimPanel();

  const profile = await loadProfile();
  const changes = buildChanges(profile, result.optimized_resume, result.report?.highlights);
  const gaps = buildGaps(result.matched_keywords, result.missing_keywords, result.added_keywords);

  root.innerHTML = "";
  root.appendChild(buildScreen(changes, title, company, result.download_url, gaps));
  root.hidden = false;
}
