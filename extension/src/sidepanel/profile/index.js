/**
 * Profile controller — import only, no editing UI.
 *
 *   no saved profile → ProfileSetup (CV drag&drop + LinkedIn/GitHub/portfolio URLs)
 *   saved profile     → a status message + "Re-import"
 *
 * A successful import persists silently; the profile is never displayed or
 * edited here, only used later by resume generation.
 */

import { ImportState, Message } from "../../shared/constants.js";
import { loadProfile, saveProfile } from "../../shared/profileApi.js";
import { createProfileSetup } from "./ProfileSetup.js";

const root = document.getElementById("profile-root");
let state = ImportState.IDLE;

function banner(text, variant) {
  const p = document.createElement("p");
  p.className = "status" + (variant ? ` status--${variant}` : "");
  p.textContent = text;
  return p;
}

function showSetup() {
  state = ImportState.IDLE;
  root.innerHTML = "";
  const { element } = createProfileSetup({
    onImported: (result) => {
      saveProfile(result.profile);
      showSaved();
    },
  });
  root.appendChild(element);
}

function showSaved() {
  state = ImportState.SUCCESS;
  root.innerHTML = "";
  root.appendChild(banner(Message.SAVED, "ok"));

  const reimport = document.createElement("button");
  reimport.className = "btn-link";
  reimport.textContent = Message.REIMPORT;
  reimport.addEventListener("click", showSetup);
  root.appendChild(reimport);
}

(async function init() {
  if (!root) return;
  const saved = await loadProfile();
  if (saved) showSaved();
  else showSetup();
})();
