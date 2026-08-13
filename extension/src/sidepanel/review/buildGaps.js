/**
 * Builds the Fit Warning banner's (Screen 13) gap summary from the backend's
 * GENERATE_RESUME response — matched_keywords/missing_keywords/added_keywords
 * (see api/v1/resume.py's ResumeGenerationResponse).
 *
 * missing_keywords/matched_keywords reflect the job's requirements against
 * the candidate's *original* profile — added_keywords are ones the AI wove
 * into the resume from real profile content the initial matcher missed (see
 * resume_generation_agent.py's filter_backed_keywords). So a keyword in both
 * lists is no longer actually missing once tailoring is done; this mirrors
 * the backend's own internal after_report computation
 * (resume_generation_agent.py's _build_report), just without a returned
 * field for the resulting list, so it's redone here from data already on
 * the response — nothing invented.
 *
 * The design spec groups gaps by theme ("ML/AI skills", "Cloud platforms",
 * ...), each with a one-line reason. The backend returns neither grouping
 * nor reasons — bucketing keywords into themes is a real categorization
 * problem this codebase hasn't solved, and writing a reason per group would
 * mean inventing text no one actually said (see buildChanges.js's same
 * rule). So this returns a single ungrouped bucket with no reason line,
 * until the backend groups missing_keywords itself.
 */
const FIT_WARNING_THRESHOLD = 0.4;

/**
 * @param {string[]} matchedKeywords result.matched_keywords
 * @param {string[]} missingKeywords result.missing_keywords
 * @param {string[]} addedKeywords result.added_keywords
 * @returns {{total: number, missing: number, groups: {theme: string, items: string[], reason: string|null}[]} | null}
 *   null when the gap doesn't clear the 40% threshold — nothing to warn about.
 */
export function buildGaps(matchedKeywords, missingKeywords, addedKeywords) {
  const matched = matchedKeywords ?? [];
  const missing = missingKeywords ?? [];
  const added = addedKeywords ?? [];

  const stillMissing = missing.filter((kw) => !added.includes(kw));
  const total = matched.length + added.length + stillMissing.length;

  if (total === 0 || stillMissing.length / total <= FIT_WARNING_THRESHOLD) return null;

  return {
    total,
    missing: stillMissing.length,
    groups: [{ theme: "Missing requirements", items: stillMissing, reason: null }],
  };
}
