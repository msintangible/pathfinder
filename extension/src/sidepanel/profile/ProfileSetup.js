/**
 * ProfileSetup — onboarding UI: CV drag&drop (PDF only, 10MB) + optional URLs.
 *
 * Emits onImported(result) on success. "Import profile" enables as soon as
 * there's anything to import from — a CV, a URL, or scraped LinkedIn text —
 * so a CV isn't required.
 */

import { importProfile } from "../../shared/profileApi.js";
import { Upload, Message } from "../../shared/constants.js";

/** @returns {string|null} an error message, or null if the file is valid. */
function validateFile(file) {
  const isPdf = file.type === Upload.ACCEPTED_MIME || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return Message.PDF_ONLY;
  if (file.size > Upload.MAX_BYTES) return Message.TOO_LARGE;
  return null;
}

/**
 * @param {{ onImported:(r:import("../../shared/types.js").ImportResult)=>void }} cb
 */
export function createProfileSetup({ onImported }) {
  let file = null;
  let linkedinText = "";
  const el = document.createElement("div");
  el.className = "pf-setup";
  el.innerHTML = `
    <label class="pf-drop" tabindex="0">
      <input type="file" accept="${Upload.ACCEPTED_EXT}" class="pf-drop__input" hidden>
      <span class="pf-drop__label">${Message.DROP_HINT}</span>
    </label>
    <div class="pf-urls">
      <div class="pf-linkedin-row">
        <input class="input" type="url" data-url="linkedin" placeholder="LinkedIn URL (optional)">
        <button type="button" class="btn-link" data-role="scrape-linkedin">Use open tab</button>
      </div>
      <p class="pf-hint" data-role="linkedin-hint" hidden></p>
      <input class="input" type="url" data-url="github" placeholder="GitHub URL (optional)">
      <input class="input" type="url" data-url="portfolio" placeholder="Portfolio URL (optional)">
    </div>
    <div class="pf-progress" hidden><div class="pf-progress__bar"></div></div>
    <p class="status" data-role="status" hidden></p>
    <button class="btn" data-role="import" disabled>Import profile</button>`;

  const drop = el.querySelector(".pf-drop");
  const input = el.querySelector(".pf-drop__input");
  const dropLabel = el.querySelector(".pf-drop__label");
  const progress = el.querySelector(".pf-progress");
  const bar = el.querySelector(".pf-progress__bar");
  const status = el.querySelector('[data-role="status"]');
  const importBtn = el.querySelector('[data-role="import"]');
  const scrapeLinkedinBtn = el.querySelector('[data-role="scrape-linkedin"]');
  const linkedinHint = el.querySelector('[data-role="linkedin-hint"]');
  const urlOf = (k) => el.querySelector(`[data-url="${k}"]`).value.trim();

  function setStatus(msg, isError) {
    status.hidden = !msg;
    status.textContent = msg || "";
    status.className = isError ? "status status--err" : "status";
  }

  function updateImportEnabled() {
    importBtn.disabled = !(file || linkedinText || urlOf("linkedin") || urlOf("github") || urlOf("portfolio"));
  }

  function chooseFile(picked) {
    const err = picked ? validateFile(picked) : null;
    if (err) {
      file = null;
      dropLabel.textContent = Message.DROP_HINT;
      setStatus(err, true);
      updateImportEnabled();
      return;
    }
    file = picked;
    dropLabel.textContent = file.name;
    setStatus("", false);
    updateImportEnabled();
  }

  input.addEventListener("change", () => chooseFile(input.files[0]));
  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("pf-drop--over");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("pf-drop--over"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("pf-drop--over");
    chooseFile(e.dataTransfer.files[0]);
  });

  for (const key of ["linkedin", "github", "portfolio"]) {
    el.querySelector(`[data-url="${key}"]`).addEventListener("input", updateImportEnabled);
  }

  function setLinkedinHint(msg) {
    linkedinHint.hidden = !msg;
    linkedinHint.textContent = msg || "";
  }

  scrapeLinkedinBtn.addEventListener("click", async () => {
    scrapeLinkedinBtn.disabled = true;
    setLinkedinHint("Reading the open tab…");
    try {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      if (!tab) {
        setLinkedinHint("No active tab to read.");
        return;
      }
      const scraped = await chrome.tabs.sendMessage(tab.id, { type: "SCRAPE_PAGE" });
      if (scraped?.text) {
        linkedinText = scraped.text;
        el.querySelector('[data-url="linkedin"]').value = tab.url || "";
        updateImportEnabled();
        setLinkedinHint(
          `Captured ${scraped.text.length} chars from the open tab. Scroll through your ` +
          `LinkedIn profile first so more of it has loaded, then re-scrape if needed.`
        );
      } else {
        setLinkedinHint("No text found on that tab.");
      }
    } catch {
      setLinkedinHint("Couldn't read that tab — reload it and try again.");
    } finally {
      scrapeLinkedinBtn.disabled = false;
    }
  });

  importBtn.addEventListener("click", async () => {
    importBtn.disabled = true;
    progress.hidden = false;
    bar.style.width = "0%";
    setStatus(Message.UPLOADING, false);

    const result = await importProfile({
      file,
      linkedin: urlOf("linkedin"),
      linkedinText,
      github: urlOf("github"),
      portfolio: urlOf("portfolio"),
      onProgress: (f) => (bar.style.width = `${Math.round(f * 100)}%`),
    });

    progress.hidden = true;
    if (result.ok) {
      onImported(result);
    } else {
      setStatus(`${Message.IMPORT_FAILED} ${result.error}`, true);
      updateImportEnabled();
    }
  });

  return { element: el };
}
