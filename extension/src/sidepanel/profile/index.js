/**
 * Profile controller — owns the ImportState machine and mounts the right view.
 *
 *   no saved profile        → ProfileSetup (IDLE)
 *   imported, low confidence → ProfileCard  (NEEDS_REVIEW, flags shown)
 *   imported, all confident  → ProfileCard  (SUCCESS)
 *   user skipped / manual    → empty ProfileCard (MANUAL)
 *
 * The user is never blocked: from Setup they can always "enter manually", and
 * from the card they can always "re-import from CV".
 */

import { ImportState, Message, CONFIDENCE_LOW } from "../../shared/constants.js";
import { loadProfile, saveProfile } from "../../shared/profileApi.js";
import { emptyProfile } from "../../shared/profileMapper.js";
import { createProfileSetup } from "./ProfileSetup.js";
import { createProfileCard } from "./ProfileCard.js";

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
    onImported: (result) => showCard(result.profile, result.confidence, { fromImport: true }),
    onManual: () => showCard(emptyProfile(), {}, { manual: true }),
  });
  root.appendChild(element);
}

function showCard(profile, confidence = {}, { fromImport = false, manual = false } = {}) {
  const lowFields = Object.values(confidence).filter((v) => v < CONFIDENCE_LOW).length;
  state = manual
    ? ImportState.MANUAL
    : lowFields > 0
    ? ImportState.NEEDS_REVIEW
    : ImportState.SUCCESS;

  root.innerHTML = "";
  if (state === ImportState.NEEDS_REVIEW) root.appendChild(banner(Message.NEEDS_REVIEW, "warn"));
  else if (fromImport) root.appendChild(banner(Message.SAVED, "ok"));

  const card = createProfileCard({ profile, confidence, onChange: saveProfile });
  root.appendChild(card.element);
  saveProfile(profile); // persist the starting point immediately

  const reimport = document.createElement("button");
  reimport.className = "btn-link";
  reimport.textContent = Message.REIMPORT;
  reimport.addEventListener("click", showSetup);
  root.appendChild(reimport);
}

(async function init() {
  if (!root) return;
  const saved = await loadProfile();
  if (saved) showCard(saved);
  else showSetup();
})();
