/**
 * Matches the backend's LLM-authored change reasons (report.highlights) to
 * real before/after text, so the Review changes screen (Screen 4) can show
 * a truthful "was: ..." line for each one.
 *
 * The backend's ResumeGenerationResponse never returns before-text — only
 * the after content (optimized_resume) and grouped reasons
 * (report.highlights: [{section, summary, impact}]). highlights[].section is
 * free text the LLM writes itself, not a fixed key, so matching it to a real
 * field (the locally-stored candidate profile's summary/skills/experience)
 * is necessarily a heuristic. A highlight that can't be matched with
 * confidence is dropped rather than shown with guessed content — same
 * "never fabricate" rule the rest of the product follows. This means the
 * resulting change count can be lower than report.highlights.length.
 *
 * (The backend could eventually return real before/after text per section
 * directly, which would remove the need for this matching entirely — a
 * future backend change, not built here.)
 */

function matchExperience(sectionText, experience) {
  const needle = sectionText.toLowerCase();
  return (experience ?? []).find(
    (e) =>
      (e.company && needle.includes(e.company.toLowerCase())) ||
      (e.title && needle.includes(e.title.toLowerCase()))
  );
}

function changedText(oldText, newText) {
  const oldTrimmed = oldText?.trim();
  const newTrimmed = newText?.trim();
  return oldTrimmed && newTrimmed && oldTrimmed !== newTrimmed ? { oldText: oldTrimmed, newText: newTrimmed } : null;
}

/**
 * @param {import("../../shared/types.js").UserProfile} profile locally-stored candidate profile
 * @param {object} optimizedResume backend's OptimizedResume (result.optimized_resume)
 * @param {{section: string, summary: string, impact: string}[]} highlights result.report.highlights
 * @returns {{section: string, reason: string, oldText: string, newText: string}[]}
 */
export function buildChanges(profile, optimizedResume, highlights) {
  if (!profile || !optimizedResume) return [];

  const rows = [];
  for (const highlight of highlights ?? []) {
    const section = highlight.section?.toLowerCase() ?? "";

    if (section.includes("summary") || section.includes("headline")) {
      const change = changedText(profile.summary, optimizedResume.summary);
      if (change) rows.push({ section: "Professional summary", reason: highlight.summary, ...change });
      continue;
    }

    if (section.includes("skill")) {
      const change = changedText(profile.skills?.join(", "), optimizedResume.skills?.join(", "));
      if (change) rows.push({ section: "Skills", reason: highlight.summary, ...change });
      continue;
    }

    const oldExp = matchExperience(section, profile.experience);
    if (oldExp) {
      const newExp = (optimizedResume.experience ?? []).find(
        (e) => e.company === oldExp.company && e.title === oldExp.title
      );
      const change = changedText(oldExp.bullets?.join(" "), newExp?.bullets?.join(" "));
      if (change) {
        rows.push({
          section: [oldExp.title, oldExp.company].filter(Boolean).join(" at "),
          reason: highlight.summary,
          ...change,
        });
      }
      continue;
    }

    // No confident match — skip rather than guess (see module doc).
  }
  return rows;
}
