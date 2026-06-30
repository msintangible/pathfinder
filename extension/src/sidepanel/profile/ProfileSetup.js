/**
 * ProfileSetup — onboarding UI: CV drag&drop (PDF only, 10MB) + optional URLs.
 *
 * Emits onImported(result) on success and onManual() when the user chooses to
 * skip and enter details by hand. The user is NEVER blocked: a failed import
 * still leaves the "enter manually" path open.
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
 * @param {{ onImported:(r:import("../../shared/types.js").ImportResult)=>void,
 *           onManual:()=>void }} cb
 */
export function createProfileSetup({ onImported, onManual }) {
  let file = null;
  const el = document.createElement("div");
  el.className = "pf-setup";
  el.innerHTML = `
    <label class="pf-drop" tabindex="0">
      <input type="file" accept="${Upload.ACCEPTED_EXT}" class="pf-drop__input" hidden>
      <span class="pf-drop__label">${Message.DROP_HINT}</span>
    </label>
    <div class="pf-urls">
      <input class="input" type="url" data-url="linkedin" placeholder="LinkedIn URL (optional)">
      <input class="input" type="url" data-url="github" placeholder="GitHub URL (optional)">
      <input class="input" type="url" data-url="portfolio" placeholder="Portfolio URL (optional)">
    </div>
    <div class="pf-progress" hidden><div class="pf-progress__bar"></div></div>
    <p class="status" data-role="status" hidden></p>
    <button class="btn" data-role="import" disabled>Import profile</button>
    <button class="btn-link" data-role="manual">${Message.ENTER_MANUALLY}</button>`;

  const drop = el.querySelector(".pf-drop");
  const input = el.querySelector(".pf-drop__input");
  const dropLabel = el.querySelector(".pf-drop__label");
  const progress = el.querySelector(".pf-progress");
  const bar = el.querySelector(".pf-progress__bar");
  const status = el.querySelector('[data-role="status"]');
  const importBtn = el.querySelector('[data-role="import"]');
  const manualBtn = el.querySelector('[data-role="manual"]');
  const urlOf = (k) => el.querySelector(`[data-url="${k}"]`).value.trim();

  function setStatus(msg, isError) {
    status.hidden = !msg;
    status.textContent = msg || "";
    status.className = isError ? "status status--err" : "status";
  }

  function chooseFile(picked) {
    const err = picked ? validateFile(picked) : null;
    if (err) {
      file = null;
      dropLabel.textContent = Message.DROP_HINT;
      setStatus(err, true);
      importBtn.disabled = true;
      return;
    }
    file = picked;
    dropLabel.textContent = file.name;
    setStatus("", false);
    importBtn.disabled = false;
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

  manualBtn.addEventListener("click", onManual);

  importBtn.addEventListener("click", async () => {
    importBtn.disabled = true;
    progress.hidden = false;
    bar.style.width = "0%";
    setStatus(Message.UPLOADING, false);

    const result = await importProfile({
      file,
      linkedin: urlOf("linkedin"),
      github: urlOf("github"),
      portfolio: urlOf("portfolio"),
      onProgress: (f) => (bar.style.width = `${Math.round(f * 100)}%`),
    });

    progress.hidden = true;
    if (result.ok) {
      onImported(result);
    } else {
      setStatus(`${Message.IMPORT_FAILED} ${result.error}`, true);
      importBtn.disabled = false;
    }
  });

  return { element: el };
}
