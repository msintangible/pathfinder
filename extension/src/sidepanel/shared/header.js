/**
 * Shared screen header (P-badge + "Pathfinder" wordmark) — identical across
 * every full-screen redesign state. Styled by .pf-header in sidepanel.css.
 */
export function pfHeader() {
  const el = document.createElement("div");
  el.className = "pf-header";

  const badge = document.createElement("span");
  badge.className = "pf-header__badge";
  badge.textContent = "P";

  const name = document.createElement("span");
  name.className = "pf-header__name";
  name.textContent = "Pathfinder";

  el.append(badge, name);
  return el;
}
