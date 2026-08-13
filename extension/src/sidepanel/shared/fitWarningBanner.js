/**
 * Fit Warning banner (Screen 13) — shown above the diff on the Review
 * changes screen when a significant share of the job's requirements have no
 * match in the candidate's background (see review/buildGaps.js for the
 * threshold and how `groups` is derived). Amber, informational, never a
 * blocker: collapsed by default, dismissible, and dismissing or leaving it
 * collapsed never stops the user from reviewing or downloading.
 *
 * Session-scoped by construction rather than by stored state: review/
 * index.js builds a fresh banner (and a fresh review screen) per tailoring
 * run, so there's nothing to persist or reset between jobs — the "don't
 * persist across jobs" rule in the design spec falls out for free.
 *
 * `group.reason` is optional. The real data usually won't have one yet (see
 * buildGaps.js's doc) — when absent, the reason line is simply omitted
 * rather than showing invented text.
 */
export function fitWarningBanner({ total, missing, groups, onDismiss }) {
  const el = document.createElement("div");
  el.className = "pf-fitwarn";

  // Shared padded wrapper for the header row and the toggle beneath it — the
  // toggle's own left margin is relative to this padding, which is what
  // lines it up under the text column rather than the glyph (see the CSS).
  const top = document.createElement("div");
  top.className = "pf-fitwarn__top";

  const header = document.createElement("div");
  header.className = "pf-fitwarn__header";

  const infoGlyph = document.createElement("span");
  infoGlyph.className = "pf-fitwarn__info";
  infoGlyph.textContent = "i";
  infoGlyph.setAttribute("aria-hidden", "true");
  header.appendChild(infoGlyph);

  const textCol = document.createElement("div");
  textCol.className = "pf-fitwarn__text";

  const headline = document.createElement("p");
  headline.className = "pf-fitwarn__headline";
  headline.textContent = "This role is a significant stretch";
  textCol.appendChild(headline);

  const detail = document.createElement("p");
  detail.className = "pf-fitwarn__detail";
  detail.textContent = `${missing} of ${total} core requirements aren't in your background yet.`;
  textCol.appendChild(detail);

  header.appendChild(textCol);

  const dismissBtn = document.createElement("button");
  dismissBtn.type = "button";
  dismissBtn.className = "pf-fitwarn__dismiss";
  dismissBtn.setAttribute("aria-label", "Dismiss");
  dismissBtn.innerHTML =
    '<svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true">' +
    '<path d="M3.2 3.2L8.8 8.8M8.8 3.2L3.2 8.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"></path>' +
    "</svg>";
  dismissBtn.addEventListener("click", () => {
    el.hidden = true;
    onDismiss?.();
  });
  header.appendChild(dismissBtn);

  top.appendChild(header);

  const areaWord = groups.length === 1 ? "area" : "areas";
  const collapsedLabel = `See what's missing (${groups.length} ${areaWord})`;

  const toggleBtn = document.createElement("button");
  toggleBtn.type = "button";
  toggleBtn.className = "pf-fitwarn__toggle";
  toggleBtn.setAttribute("aria-expanded", "false");

  const toggleLabel = document.createElement("span");
  toggleLabel.textContent = collapsedLabel;

  const caret = document.createElement("span");
  caret.className = "pf-fitwarn__caret";
  caret.innerHTML =
    '<svg width="9" height="6" viewBox="0 0 10 7" aria-hidden="true">' +
    '<path d="M1 1.5L5 5.5L9 1.5" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"></path>' +
    "</svg>";

  toggleBtn.append(toggleLabel, caret);
  top.appendChild(toggleBtn);
  el.appendChild(top);

  const body = document.createElement("div");
  body.className = "pf-fitwarn__body";
  body.hidden = true;

  groups.forEach((group) => {
    const groupEl = document.createElement("div");
    groupEl.className = "pf-fitwarn__group";

    const groupHead = document.createElement("div");
    groupHead.className = "pf-fitwarn__group-head";

    const theme = document.createElement("span");
    theme.className = "pf-fitwarn__theme";
    theme.textContent = group.theme;
    groupHead.appendChild(theme);

    const count = document.createElement("span");
    count.className = "pf-fitwarn__count";
    count.textContent = `${group.items.length} missing`;
    groupHead.appendChild(count);

    groupEl.appendChild(groupHead);

    const chips = document.createElement("div");
    chips.className = "pf-fitwarn__chips";
    group.items.forEach((item) => {
      const chip = document.createElement("span");
      chip.className = "pf-fitwarn__chip";
      chip.textContent = item;
      chips.appendChild(chip);
    });
    groupEl.appendChild(chips);

    if (group.reason) {
      const reasonEl = document.createElement("p");
      reasonEl.className = "pf-fitwarn__reason";
      reasonEl.textContent = group.reason;
      groupEl.appendChild(reasonEl);
    }

    body.appendChild(groupEl);
  });

  const closing = document.createElement("p");
  closing.className = "pf-fitwarn__closing";
  closing.textContent = "Pathfinder won't invent experience you don't have. These stayed out of your resume.";
  body.appendChild(closing);

  el.appendChild(body);

  let expanded = false;
  toggleBtn.addEventListener("click", () => {
    expanded = !expanded;
    body.hidden = !expanded;
    toggleBtn.setAttribute("aria-expanded", String(expanded));
    toggleLabel.textContent = expanded ? "Hide what's missing" : collapsedLabel;
    caret.classList.toggle("pf-fitwarn__caret--open", expanded);
  });

  return el;
}
