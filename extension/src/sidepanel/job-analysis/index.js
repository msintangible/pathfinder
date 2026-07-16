/**
 * Job Analysis controller — owns the "Analyse this page" button and its
 * status line.
 *
 * Scrapes the active tab's text directly from the content script, sends it
 * to the service worker for analysis, and persists the result (job id) for
 * the active tab so the Optimize CV module can find it. Any resume already
 * generated for a previous analysis of this tab is cleared so a stale
 * result doesn't linger under a new job.
 */

const root = document.getElementById("job-analysis-root");

const state = {
  analysing: false,
  statusText: null,
  statusVariant: null,
};

function statusLine(text, variant) {
  const p = document.createElement("p");
  p.className = "status" + (variant ? ` status--${variant}` : "");
  p.textContent = text;
  return p;
}

/** Re-render #job-analysis-root from the current state. Pure function of `state`. */
function render() {
  if (!root) return;
  root.innerHTML = "";

  if (state.statusText) root.appendChild(statusLine(state.statusText, state.statusVariant));

  const btn = document.createElement("button");
  btn.id = "analyse-job";
  btn.className = "btn";
  btn.textContent = "Analyse this page";
  btn.disabled = state.analysing;
  btn.addEventListener("click", analyseJob);
  root.appendChild(btn);
}

/** Return the active tab (or null). */
async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab ?? null;
}

/**
 * Scrape the active tab, send the text to the service worker for analysis,
 * and persist the result for other modules to pick up.
 */
async function analyseJob() {
  state.analysing = true;
  state.statusText = "Scraping page…";
  state.statusVariant = null;
  render();

  const tab = await getActiveTab();
  if (!tab) {
    state.analysing = false;
    state.statusText = "No active tab.";
    state.statusVariant = "err";
    render();
    return;
  }

  let scrape;
  try {
    // frameId: 0 pins this to the top-level frame — see the comment on the
    // equivalent call in sidepanel.js's scrapeActivePage().
    scrape = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE_PAGE" }, { frameId: 0 });
  } catch {
    state.analysing = false;
    state.statusText = "Can't read this page — reload the tab and try again.";
    state.statusVariant = "err";
    render();
    return;
  }

  if (!scrape?.text) {
    state.analysing = false;
    state.statusText = "No text scraped from this page.";
    state.statusVariant = "err";
    render();
    return;
  }

  state.statusText = `Sending ${scrape.text.length} chars to backend…`;
  render();

  const res = await chrome.runtime.sendMessage({
    type: "ANALYZE_JOB",
    payload: { raw_text: scrape.text, url: scrape.url },
  });

  state.analysing = false;

  if (res?.ok) {
    state.statusText = "Analysis complete.";
    state.statusVariant = null;
    render();

    await chrome.runtime.sendMessage({
      type: "SAVE_JOB_ANALYSIS",
      payload: { tabId: tab.id, id: res.data.id, title: res.data.title, company: res.data.company, url: scrape.url },
    });
    await chrome.runtime.sendMessage({
      type: "SAVE_RESUME_RESULT",
      payload: { tabId: tab.id, data: null },
    });
  } else {
    state.statusText = res?.error || "Analysis failed.";
    state.statusVariant = "err";
    render();
  }
}

render();
