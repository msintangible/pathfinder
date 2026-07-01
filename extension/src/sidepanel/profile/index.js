/**
 * Profile controller — import only, no editing UI.
 *
 *   no saved profile → ProfileSetup (CV drag&drop + LinkedIn/GitHub/portfolio URLs)
 *   saved profile     → name + a short summary + a per-source verification section + "Re-import"
 *
 * A successful import persists silently and shows just enough back to the
 * user to confirm what was extracted from each source — not a full editable card.
 */

import { ImportState, Message } from "../../shared/constants.js";
import { loadProfile, saveProfile, loadSources, saveSources, saveProfileId } from "../../shared/profileApi.js";
import { createProfileSetup } from "./ProfileSetup.js";

const SOURCE_PREVIEW_CHARS = 160;

const root = document.getElementById("profile-root");
let state = ImportState.IDLE;

function banner(text, variant) {
  const p = document.createElement("p");
  p.className = "status" + (variant ? ` status--${variant}` : "");
  p.textContent = text;
  return p;
}

function line(text, className) {
  const p = document.createElement("p");
  p.className = className;
  p.textContent = text;
  return p;
}

/** Up to 3 short lines confirming what was actually extracted. */
function summaryLines(profile) {
  const lines = [];

  if (profile.headline) lines.push(profile.headline);

  if (profile.skills?.length) {
    const shown = profile.skills.slice(0, 5).join(", ");
    const more = profile.skills.length > 5 ? ` (+${profile.skills.length - 5} more)` : "";
    lines.push(`Skills: ${shown}${more}`);
  }

  if (profile.experience?.length) {
    const latest = profile.experience[0];
    const role = [latest.title, latest.company].filter(Boolean).join(" at ");
    lines.push(
      role
        ? `Most recent: ${role}`
        : `${profile.experience.length} work experience ${profile.experience.length === 1 ? "entry" : "entries"}`
    );
  }

  return lines.slice(0, 3);
}

function truncate(text) {
  if (!text) return null;
  const trimmed = text.trim();
  if (!trimmed) return null;
  return trimmed.length > SOURCE_PREVIEW_CHARS
    ? `${trimmed.slice(0, SOURCE_PREVIEW_CHARS).trimEnd()}…`
    : trimmed;
}

function githubSourceText(sources) {
  const repos = sources.github_repositories || [];
  const parts = [];
  if (sources.github_profile) parts.push(truncate(sources.github_profile));
  if (repos.length) {
    const names = repos.slice(0, 3).map((r) => r.name).join(", ");
    const more = repos.length > 3 ? `, +${repos.length - 3} more` : "";
    parts.push(`${repos.length} ${repos.length === 1 ? "repo" : "repos"}: ${names}${more}`);
  }
  return parts.length ? parts.join(" — ") : null;
}

/** [label, previewText|null] per source — null means nothing was found/provided. */
function sourceSummary(sources) {
  if (!sources) return [];
  return [
    ["CV", truncate(sources.resume_text)],
    ["LinkedIn", truncate(sources.linkedin_text)],
    ["GitHub", githubSourceText(sources)],
    ["Portfolio", truncate(sources.portfolio_text)],
  ];
}

function sourceRow(label, text) {
  const row = document.createElement("p");
  row.className = "pf-source-line" + (text ? "" : " pf-source-line--empty");
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  row.appendChild(strong);
  row.appendChild(document.createTextNode(text || "not provided"));
  return row;
}

function showSetup() {
  state = ImportState.IDLE;
  root.innerHTML = "";
  const { element } = createProfileSetup({
    onImported: (result) => {
      saveProfile(result.profile);
      saveSources(result.sources);
      saveProfileId(result.profileId);
      showSaved(result.profile, result.sources);
    },
  });
  root.appendChild(element);
}

function showSaved(profile, sources) {
  state = ImportState.SUCCESS;
  root.innerHTML = "";
  root.appendChild(banner(Message.SAVED, "ok"));

  if (profile?.name) root.appendChild(line(profile.name, "pf-summary-name"));
  for (const text of summaryLines(profile || {})) {
    root.appendChild(line(text, "pf-summary-line"));
  }

  const rows = sourceSummary(sources);
  if (rows.length) {
    root.appendChild(line("What we found:", "pf-sources-heading"));
    for (const [label, text] of rows) root.appendChild(sourceRow(label, text));
  }

  const reimport = document.createElement("button");
  reimport.className = "btn-link";
  reimport.textContent = Message.REIMPORT;
  reimport.addEventListener("click", showSetup);
  root.appendChild(reimport);
}

(async function init() {
  if (!root) return;
  const saved = await loadProfile();
  if (saved) {
    const sources = await loadSources();
    showSaved(saved, sources);
  } else {
    showSetup();
  }
})();
