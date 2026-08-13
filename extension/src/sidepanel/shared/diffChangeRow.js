/**
 * Diff-change-row — one changed section on the Review Changes screen
 * (Screen 4): a short reason, a Revert action, the new (highlighted)
 * content, and a muted secondary line showing the other version. Standalone
 * piece; Screen 4 is what wires this up to real diff data and a live "X of Y
 * changes kept" count — this module only builds the row itself.
 *
 * Clicking Revert actually swaps which version this row displays as primary
 * (was previously a no-op on the row itself — only a parent-owned counter
 * changed, which is what "Revert" claimed to do but didn't). A reverted row
 * shows the original as primary text and the AI's suggestion struck through
 * below, mirroring the un-reverted layout exactly, so the row's own display
 * never claims more than it does. What this can't do — because there's no
 * backend endpoint to exclude a patch and re-render the file — is change
 * what Download actually returns; the review screen surfaces that limitation
 * separately, once it's relevant, rather than pretending this button reaches
 * the file.
 *
 * Intentional deviation from Pathfinder Diff.dc.html: the reference file
 * drops the secondary line entirely on revert, showing only the restored
 * original. Here it stays, relabeled "AI suggested:", because the
 * suggested-vs-chosen contrast is the receipt this product's trust mechanic
 * depends on — it shouldn't disappear the moment a user acts on it.
 *
 * `onRevertClick(event, isReverted)` is optional, same pattern as
 * detection/index.js's tailorButton(): omitted means the Revert button is
 * disabled rather than silently doing nothing on click.
 */
export function diffChangeRow({ reason, newText, oldText, onRevertClick }) {
  const row = document.createElement("div");
  row.className = "pf-diff-row";

  const head = document.createElement("div");
  head.className = "pf-diff-row__head";

  const reasonEl = document.createElement("span");
  reasonEl.className = "pf-diff-row__reason";
  reasonEl.textContent = reason;
  head.appendChild(reasonEl);

  const revertBtn = document.createElement("button");
  revertBtn.className = "pf-diff-row__revert";
  revertBtn.textContent = "Revert";
  revertBtn.disabled = !onRevertClick;
  head.appendChild(revertBtn);

  row.appendChild(head);

  const primaryEl = document.createElement("p");
  primaryEl.className = "pf-diff-row__new";
  primaryEl.textContent = newText;
  row.appendChild(primaryEl);

  const secondaryEl = document.createElement("p");
  secondaryEl.className = "pf-diff-row__old";
  const secondaryLabel = document.createElement("span");
  secondaryLabel.textContent = "was: ";
  const secondaryTextEl = document.createElement("span");
  secondaryTextEl.className = "pf-diff-row__old-text";
  secondaryTextEl.textContent = oldText;
  secondaryEl.append(secondaryLabel, secondaryTextEl);
  row.appendChild(secondaryEl);

  let reverted = false;

  function render() {
    row.classList.toggle("pf-diff-row--reverted", reverted);
    primaryEl.classList.toggle("pf-diff-row__new--original", reverted);
    primaryEl.textContent = reverted ? oldText : newText;
    reasonEl.textContent = reverted ? "Reverted to original" : reason;
    secondaryLabel.textContent = reverted ? "AI suggested: " : "was: ";
    secondaryTextEl.textContent = reverted ? newText : oldText;
    revertBtn.textContent = reverted ? "Restore" : "Revert";
  }

  if (onRevertClick) {
    revertBtn.addEventListener("click", (event) => {
      reverted = !reverted;
      render();
      onRevertClick(event, reverted);
    });
  }

  return row;
}
