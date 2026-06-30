/**
 * ProfileCard — renders a UserProfile scannably in the ~380px side panel, with
 * every field inline-editable. Low-confidence fields are flagged "review".
 *
 * Pure composition over the editable primitives + section builders. The card
 * owns a working copy of the profile; every edit calls onChange(profile) so the
 * user's correction is persisted and wins over the AI's extraction.
 */

import { createEditableText, createEditableChips } from "./editable.js";
import { createSection, createListSection } from "./sections.js";
import { ProfileField, CONFIDENCE_LOW } from "../../shared/constants.js";

/**
 * @param {{ profile:import("../../shared/types.js").UserProfile,
 *           confidence?:import("../../shared/types.js").ConfidenceMap,
 *           onChange:(p:import("../../shared/types.js").UserProfile)=>void }} opts
 */
export function createProfileCard({ profile, confidence = {}, onChange }) {
  const data = structuredClone(profile);
  const low = (field) => confidence[field] != null && confidence[field] < CONFIDENCE_LOW;
  const commit = () => onChange(data);

  const el = document.createElement("div");
  el.className = "pf-card";

  // Identity
  const identity = createSection("Identity", low(ProfileField.NAME) || low(ProfileField.EMAIL));
  identity.appendChild(createEditableText({
    label: "Name", value: data.name, placeholder: "Your name",
    lowConfidence: low(ProfileField.NAME), onSave: (v) => { data.name = v; commit(); },
  }));
  identity.appendChild(createEditableText({
    label: "Email", value: data.email, placeholder: "you@example.com",
    lowConfidence: low(ProfileField.EMAIL), onSave: (v) => { data.email = v; commit(); },
  }));
  el.appendChild(identity);

  // Skills
  const skills = createSection("Skills", low(ProfileField.SKILLS));
  skills.appendChild(createEditableChips({
    label: "Skills", values: data.skills, lowConfidence: low(ProfileField.SKILLS),
    onSave: (v) => { data.skills = v; commit(); },
  }));
  el.appendChild(skills);

  // Experience
  el.appendChild(createListSection({
    title: "Experience", items: data.experience, lowConfidence: low(ProfileField.EXPERIENCE),
    onChange: commit,
    specs: [
      { key: "title", label: "Title" },
      { key: "company", label: "Company" },
      { key: "startDate", label: "Start" },
      { key: "endDate", label: "End" },
      { key: "bullets", label: "Highlights", type: "chips" },
    ],
    makeEmpty: () => ({ title: null, company: null, startDate: null, endDate: null, current: false, bullets: [] }),
  }));

  // Education
  el.appendChild(createListSection({
    title: "Education", items: data.education, lowConfidence: low(ProfileField.EDUCATION),
    onChange: commit,
    specs: [
      { key: "institution", label: "Institution" },
      { key: "degree", label: "Degree" },
      { key: "field", label: "Field" },
      { key: "year", label: "Year" },
    ],
    makeEmpty: () => ({ institution: null, degree: null, field: null, year: null }),
  }));

  // Projects
  el.appendChild(createListSection({
    title: "Projects", items: data.projects, lowConfidence: low(ProfileField.PROJECTS),
    onChange: commit,
    specs: [
      { key: "name", label: "Name" },
      { key: "description", label: "Description", type: "textarea" },
      { key: "url", label: "URL" },
      { key: "technologies", label: "Tech", type: "chips" },
    ],
    makeEmpty: () => ({ name: null, description: null, url: null, technologies: [] }),
  }));

  // Certifications
  el.appendChild(createListSection({
    title: "Certifications", items: data.certifications, lowConfidence: low(ProfileField.CERTIFICATIONS),
    onChange: commit,
    specs: [
      { key: "name", label: "Name" },
      { key: "issuer", label: "Issuer" },
      { key: "date", label: "Date" },
      { key: "url", label: "URL" },
    ],
    makeEmpty: () => ({ name: null, issuer: null, date: null, url: null }),
  }));

  // Links
  const links = createSection("Links", low(ProfileField.LINKS));
  for (const key of ["linkedin", "github", "portfolio"]) {
    links.appendChild(createEditableText({
      label: key[0].toUpperCase() + key.slice(1),
      value: data.links[key] ?? null,
      placeholder: "https://…",
      onSave: (v) => { if (v) data.links[key] = v; else delete data.links[key]; commit(); },
    }));
  }
  el.appendChild(links);

  return { element: el, getProfile: () => data };
}
