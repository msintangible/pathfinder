/**
 * Confidence meter — bar strength + label pair. Used by detection/index.js's
 * 3 job-page-ish screens today, and by Screen 5 (Decide) once it exists,
 * which needs the same known-ATS "Strong match" reading shown there.
 * Styled by .pf-meter* in sidepanel.css.
 */
export const METER = {
  "known-ats": { label: "Strong match", filled: 3 },
  "unknown-ats": { label: "Partial match", filled: 2 },
  "keywords-only": { label: "Low match", filled: 1 },
};

export function confidenceMeter(state) {
  const { label, filled } = METER[state];

  const wrap = document.createElement("div");
  wrap.className = "pf-meter";

  const bars = document.createElement("div");
  bars.className = "pf-meter__bars";
  for (let i = 0; i < 3; i++) {
    const bar = document.createElement("span");
    bar.className = "pf-meter__bar" + (i < filled ? ` pf-meter__bar--${state}` : "");
    bars.appendChild(bar);
  }

  const text = document.createElement("span");
  text.className = "pf-meter__label";
  text.textContent = label;

  wrap.append(bars, text);
  return wrap;
}
