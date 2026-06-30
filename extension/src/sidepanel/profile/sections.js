/**
 * Section builders composed from the inline-edit primitives.
 *
 * createListSection renders an editable list of objects (experience, education,
 * projects, certifications): each item's fields become inline editors, with
 * Remove per item and an Add button. The caller owns the array; we mutate it
 * in place and call onChange so user edits persist immediately.
 */

import { createEditableText, createEditableChips } from "./editable.js";

/** A titled section wrapper, with an optional "review" flag. */
export function createSection(title, lowConfidence) {
  const section = document.createElement("section");
  section.className = "pf-section";
  const h = document.createElement("h3");
  h.className = "pf-section__title";
  h.textContent = title;
  if (lowConfidence) {
    const flag = document.createElement("span");
    flag.className = "pf-review";
    flag.textContent = "review";
    h.appendChild(flag);
  }
  section.appendChild(h);
  return section;
}

/**
 * @param {{ title:string, items:object[], lowConfidence?:boolean,
 *           specs:{key:string,label:string,type?:"text"|"textarea"|"chips"}[],
 *           makeEmpty:()=>object, onChange:()=>void }} opts
 */
export function createListSection({ title, items, specs, makeEmpty, lowConfidence, onChange }) {
  const section = createSection(title, lowConfidence);
  const list = document.createElement("div");
  list.className = "pf-list";
  section.appendChild(list);

  function fieldFor(spec, item) {
    if (spec.type === "chips") {
      return createEditableChips({
        label: spec.label,
        values: item[spec.key] || [],
        onSave: (v) => { item[spec.key] = v; onChange(); },
      });
    }
    return createEditableText({
      label: spec.label,
      value: item[spec.key] ?? null,
      multiline: spec.type === "textarea",
      onSave: (v) => { item[spec.key] = v; onChange(); },
    });
  }

  function rebuild() {
    list.innerHTML = "";
    items.forEach((item, idx) => {
      const entry = document.createElement("div");
      entry.className = "pf-entry";
      for (const spec of specs) entry.appendChild(fieldFor(spec, item));

      const remove = document.createElement("button");
      remove.className = "pf-remove";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => {
        items.splice(idx, 1);
        onChange();
        rebuild();
      });
      entry.appendChild(remove);
      list.appendChild(entry);
    });

    const add = document.createElement("button");
    add.className = "pf-add";
    add.type = "button";
    add.textContent = "+ Add";
    add.addEventListener("click", () => {
      items.push(makeEmpty());
      onChange();
      rebuild();
    });
    list.appendChild(add);
  }

  rebuild();
  return section;
}
