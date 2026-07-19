/**
 * Optimize CV controller.
 *
 * Enabled only once a profile has been imported AND the active tab has a
 * completed job analysis. Both conditions can become true from other
 * sidepanel modules (profile/index.js, sidepanel.js) while this panel is
 * open, so state is kept in sync via chrome.storage.onChanged (cross-script
 * writes) and chrome.tabs.onActivated (switching to a tab with different
 * per-tab state) rather than polling.
 */

import { Message, StorageKey } from "../../shared/constants.js";
import { loadProfile, loadProfileId, getBaseUrl } from "../../shared/profileApi.js";
import { getAuthToken } from "../../shared/auth.js";

const root = document.getElementById("optimize-root");

/**
 * @type {{ tabId: number|null, profileId: string|null, hasProfileData: boolean,
 *          jobAnalysis: object|null, resumeResult: object|null, generating: boolean,
 *          error: string|null }}
 */
const state = {
  tabId: null,
  profileId: null,
  hasProfileData: false,
  jobAnalysis: null,
  resumeResult: null,
  generating: false,
  error: null,
};

function statusLine(text, variant) {
  const p = document.createElement("p");
  p.className = "status" + (variant ? ` status--${variant}` : "");
  p.textContent = text;
  return p;
}

/** Which hint (if any) is blocking optimization right now. */
function blockingHint() {
  if (!state.profileId) {
    // A saved profile without an id predates profileId capture (or it was
    // otherwise lost) — the "Your Profile" card will still show it as
    // imported, so telling the user to import again would be confusing.
    return state.hasProfileData ? Message.PROFILE_NEEDS_REIMPORT_HINT : Message.NO_PROFILE_HINT;
  }
  if (!state.jobAnalysis) return Message.NO_JOB_HINT;
  return null;
}

function keywordPill(text, variant) {
  const span = document.createElement("span");
  span.className = `badge badge--${variant}`;
  span.textContent = text;
  return span;
}

function keywordSection(label, keywords, variant) {
  const wrap = document.createElement("div");
  wrap.className = "opt-keywords";

  const heading = document.createElement("p");
  heading.className = "opt-keywords-heading";
  heading.textContent = label;
  wrap.appendChild(heading);

  const list = document.createElement("div");
  list.className = "opt-keyword-list";
  for (const kw of keywords) list.appendChild(keywordPill(kw, variant));
  wrap.appendChild(list);

  return wrap;
}

/** Open the generated resume's PDF in a new browser tab.
 *  A plain tab navigation can't carry an Authorization header, so the token
 *  rides along as a query param instead — see get_current_user_allow_query_token. */
async function openResume(downloadUrl) {
  const base = await getBaseUrl();
  const token = await getAuthToken(base);
  const url = new URL(`${base}${downloadUrl}`);
  url.searchParams.set("token", token);
  chrome.tabs.create({ url: url.toString() });
}

/** Render the keyword match, ATS score, change explanation, and PDF link. */
function renderResult(container, result) {
  container.innerHTML = "";

  // Keyword sections lead the panel — added_keywords is a subset of
  // missing_keywords (see services/keyword_matcher.py::find_added_keywords
  // on the backend), so it's excluded from "Missing" once shown under
  // "Added" rather than appearing, confusingly, in both.
  const added = result.added_keywords ?? [];
  const stillMissing = (result.missing_keywords ?? []).filter((kw) => !added.includes(kw));

  if (added.length) {
    container.appendChild(keywordSection("Added to your CV", added, "warn"));
  }
  if (result.matched_keywords?.length) {
    container.appendChild(keywordSection("Matched keywords", result.matched_keywords, "ok"));
  }
  if (stillMissing.length) {
    container.appendChild(keywordSection("Missing keywords", stillMissing, "err"));
  }

  const score = document.createElement("p");
  score.className = "opt-score";
  score.textContent = `ATS score: ${Math.round(result.ats_score)}`;
  container.appendChild(score);

  const changes = result.optimized_resume?.changes_summary;
  if (changes?.length) {
    const heading = document.createElement("p");
    heading.className = "opt-changes-heading";
    heading.textContent = "What changed";
    container.appendChild(heading);

    const ul = document.createElement("ul");
    ul.className = "opt-changes";
    for (const change of changes) {
      const li = document.createElement("li");
      li.textContent = change;
      ul.appendChild(li);
    }
    container.appendChild(ul);
  }

  const openResumeBtn = document.createElement("button");
  openResumeBtn.className = "btn btn--secondary";
  openResumeBtn.textContent = Message.OPEN_RESUME;
  openResumeBtn.addEventListener("click", () => openResume(result.download_url));
  container.appendChild(openResumeBtn);
}

/** Re-render #optimize-root from the current state. Pure function of `state`. */
function render() {
  if (!root) return;
  root.innerHTML = "";

  const hint = blockingHint();
  if (hint) root.appendChild(statusLine(hint, "warn"));

  const btn = document.createElement("button");
  btn.id = "optimize-cv";
  btn.className = "btn";
  btn.disabled = Boolean(hint) || state.generating;
  btn.textContent = state.resumeResult ? Message.REOPTIMIZE : Message.OPTIMIZE_CV;
  btn.addEventListener("click", optimizeCv);
  root.appendChild(btn);

  if (state.generating) {
    root.appendChild(statusLine(Message.GENERATING, "warn"));
  } else if (state.error) {
    root.appendChild(statusLine(`${Message.GENERATE_FAILED} ${state.error}`, "err"));
  }

  const resultEl = document.createElement("div");
  resultEl.id = "optimize-result";
  resultEl.className = "opt-result";
  root.appendChild(resultEl);
  if (state.resumeResult) renderResult(resultEl, state.resumeResult);
}

/** Generate a tailored resume for the active tab's job against the saved profile. */
async function optimizeCv() {
  if (blockingHint() || state.generating) return;

  const requestTabId = state.tabId;
  state.generating = true;
  state.error = null;
  render();

  const res = await chrome.runtime.sendMessage({
    type: "GENERATE_RESUME",
    payload: { user_profile_id: state.profileId, job_id: state.jobAnalysis.id },
  });

  if (res?.ok) {
    // Always persist, so the tab this was generated for picks it up later
    // even if the user has since switched away from it.
    await chrome.runtime.sendMessage({
      type: "SAVE_RESUME_RESULT",
      payload: { tabId: requestTabId, data: res.data },
    });
    if (requestTabId !== state.tabId) return;
    state.generating = false;
    state.resumeResult = res.data;
    render();
    return;
  }

  if (requestTabId !== state.tabId) return;
  state.generating = false;
  // background/api.js's generateResume() already logs the real failure
  // detail and sanitizes res.error before returning — kept as a fixed
  // "Try again." here (rather than showing res.error directly) only to
  // avoid doubling up with the Message.GENERATE_FAILED sentence below.
  state.error = "Try again.";
  render();
}

/** Fetch job analysis, resume result, and profile id, and refresh `state`. */
async function loadStateForTab(tabId) {
  const [jobAnalysisRes, resumeResultRes, profileId, profile] = await Promise.all([
    chrome.runtime.sendMessage({ type: "GET_JOB_ANALYSIS", payload: { tabId } }),
    chrome.runtime.sendMessage({ type: "GET_RESUME_RESULT", payload: { tabId } }),
    loadProfileId(),
    loadProfile(),
  ]);
  state.tabId = tabId;
  state.jobAnalysis = jobAnalysisRes?.jobAnalysis ?? null;
  state.resumeResult = resumeResultRes?.resumeResult ?? null;
  state.profileId = profileId;
  state.hasProfileData = profile != null;
  state.generating = false;
  state.error = null;
}

async function getActiveTabId() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab?.id ?? null;
}

// ---------------------------------------------------------------------------
// Cross-module sync
// ---------------------------------------------------------------------------

// The user switched tabs: job analysis / resume result are per-tab, so refetch.
chrome.tabs.onActivated.addListener(async ({ tabId }) => {
  await loadStateForTab(tabId);
  render();
});

// Another script (profile import, job analysis, resume generation) wrote to
// storage while this panel is open — refresh whichever part of state changed.
chrome.storage.onChanged.addListener(async (changes, areaName) => {
  if (areaName === "local" && StorageKey.PROFILE_ID in changes) {
    state.profileId = changes[StorageKey.PROFILE_ID].newValue ?? null;
    render();
    return;
  }
  if (areaName === "session" && state.tabId != null) {
    await loadStateForTab(state.tabId);
    render();
  }
});

(async function init() {
  if (!root) return;
  const tabId = await getActiveTabId();
  if (tabId != null) {
    await loadStateForTab(tabId);
  } else {
    state.profileId = await loadProfileId();
    state.hasProfileData = (await loadProfile()) != null;
  }
  render();
})();
