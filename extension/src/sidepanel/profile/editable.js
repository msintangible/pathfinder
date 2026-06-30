/**
 * Reusable inline-edit primitives (no framework).
 *
 * Each factory returns a DOM element that toggles between a display view and an
 * edit view. On save it calls back with the new value — the caller owns the
 * data, so a user edit always wins over the AI's extraction.
 */

const PLACEHOLDER = "—";

/** Build the small label row, flagging low-confidence fields for review. */
function labelRow(label, lowConfidence) {
  const wrap = document.createElement("div");
  wrap.className = "pf-label";
  const span = document.createElement("span");
  span.textContent = label;
  wrap.appendChild(span);
  if (lowConfidence) {
    const flag = document.createElement("span");
    flag.className = "pf-review";
    flag.textContent = "review";
    flag.title = "Low-confidence extraction — please check";
    wrap.appendChild(flag);
  }
  return wrap;
}

function editButton(onClick) {
  const btn = document.createElement("button");
  btn.className = "pf-edit";
  btn.type = "button";
  btn.textContent = "Edit";
  btn.addEventListener("click", onClick);
  return btn;
}

/**
 * Editable single value (text or multiline).
 * @param {{label:string, value:string|null, placeholder?:string,
 *          multiline?:boolean, lowConfidence?:boolean,
 *          onSave:(value:string|null)=>void}} opts
 */
export function createEditableText(opts) {
  const { label, multiline, lowConfidence, placeholder, onSave } = opts;
  let value = opts.value;
  const row = document.createElement("div");
  row.className = "pf-field" + (lowConfidence ? " pf-field--review" : "");

  function render(editing) {
    row.innerHTML = "";
    row.appendChild(labelRow(label, lowConfidence));

    if (!editing) {
      const view = document.createElement("div");
      view.className = "pf-value" + (value ? "" : " pf-value--empty");
      view.textContent = value || placeholder || PLACEHOLDER;
      row.append(view, editButton(() => render(true)));
      return;
    }

    const input = multiline ? document.createElement("textarea") : document.createElement("input");
    input.className = "pf-input";
    input.value = value || "";
    if (placeholder) input.placeholder = placeholder;
    const save = document.createElement("button");
    save.className = "pf-save";
    save.type = "button";
    save.textContent = "Save";
    save.addEventListener("click", () => {
      value = input.value.trim() || null;
      onSave(value);
      render(false);
    });
    row.append(input, save);
    input.focus();
  }

  render(false);
  return row;
}

/**
 * Editable list of short strings rendered as chips. Edited as one-per-line text.
 * @param {{label:string, values:string[], lowConfidence?:boolean,
 *          onSave:(values:string[])=>void}} opts
 */
export function createEditableChips(opts) {
  const { label, lowConfidence, onSave } = opts;
  let values = Array.isArray(opts.values) ? [...opts.values] : [];
  const row = document.createElement("div");
  row.className = "pf-field" + (lowConfidence ? " pf-field--review" : "");

  function render(editing) {
    row.innerHTML = "";
    row.appendChild(labelRow(label, lowConfidence));

    if (!editing) {
      if (values.length === 0) {
        const empty = document.createElement("div");
        empty.className = "pf-value pf-value--empty";
        empty.textContent = PLACEHOLDER;
        row.append(empty, editButton(() => render(true)));
        return;
      }
      const chips = document.createElement("div");
      chips.className = "pf-chips";
      for (const v of values) {
        const chip = document.createElement("span");
        chip.className = "pf-chip";
        chip.textContent = v;
        chips.appendChild(chip);
      }
      row.append(chips, editButton(() => render(true)));
      return;
    }

    const ta = document.createElement("textarea");
    ta.className = "pf-input";
    ta.value = values.join("\n");
    ta.placeholder = "One per line";
    const save = document.createElement("button");
    save.className = "pf-save";
    save.type = "button";
    save.textContent = "Save";
    save.addEventListener("click", () => {
      values = ta.value.split("\n").map((s) => s.trim()).filter(Boolean);
      onSave(values);
      render(false);
    });
    row.append(ta, save);
    ta.focus();
  }

  render(false);
  return row;
}
