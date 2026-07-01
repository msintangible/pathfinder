/**
 * Normalises whatever the backend returns into the simple UserProfile shape.
 *
 * The CandidateProfileAgent emits a rich schema (many skill buckets,
 * work_experience, github_repositories, …). The DB model + UI use a simpler
 * shape. This mapper bridges the two and is tolerant of both the rich and the
 * already-simple shape, so the frontend never breaks if the contract evolves.
 *
 * Core rule: never invent. Missing → null or []. We only re-shape what's there.
 */

/** @returns {import("./types.js").UserProfile} */
export function emptyProfile() {
  return {
    name: null,
    email: null,
    headline: null,
    summary: null,
    skills: [],
    experience: [],
    education: [],
    projects: [],
    certifications: [],
    links: {},
  };
}

/** Case-insensitive dedupe that keeps the first-seen casing. */
function dedupe(values) {
  const seen = new Set();
  const out = [];
  for (const v of values) {
    if (typeof v !== "string") continue;
    const t = v.trim();
    if (!t) continue;
    const key = t.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(t);
  }
  return out;
}

const arr = (v) => (Array.isArray(v) ? v : []);

function mapExperience(e) {
  return {
    title: e.title ?? null,
    company: e.company ?? null,
    startDate: e.start_date ?? e.startDate ?? e.start ?? null,
    endDate: e.end_date ?? e.endDate ?? e.end ?? null,
    current: Boolean(e.current),
    bullets: arr(e.bullets),
  };
}

function mapEducation(e) {
  return {
    institution: e.institution ?? null,
    degree: e.degree ?? null,
    field: e.field ?? null,
    year: e.year ?? e.end_date ?? null,
  };
}

function mapProject(p) {
  return {
    name: p.name ?? null,
    description: p.description ?? null,
    url: p.url ?? null,
    technologies: arr(p.technologies).length ? arr(p.technologies) : arr(p.tech),
  };
}

function mapCertification(c) {
  return {
    name: c.name ?? null,
    issuer: c.issuer ?? null,
    date: c.date ?? null,
    url: c.url ?? null,
  };
}

/**
 * @param {any} data raw backend payload (may wrap the profile under `profile`)
 * @returns {import("./types.js").UserProfile}
 */
export function normalizeProfile(data) {
  if (!data) return emptyProfile();
  const p = data.profile ?? data;

  return {
    name: p.name ?? null,
    email: p.email ?? null,
    headline: p.headline ?? null,
    summary: p.summary ?? null,
    // Merge every skill bucket the rich schema might use, plus a plain `skills`.
    skills: dedupe([
      ...arr(p.skills),
      ...arr(p.technical_skills),
      ...arr(p.programming_languages),
      ...arr(p.frameworks),
      ...arr(p.libraries),
      ...arr(p.databases),
      ...arr(p.cloud_platforms),
      ...arr(p.devops_tools),
      ...arr(p.ai_ml_tools),
      ...arr(p.development_tools),
      ...arr(p.soft_skills),
    ]),
    experience: arr(p.experience).length
      ? arr(p.experience).map(mapExperience)
      : arr(p.work_experience).map(mapExperience),
    education: arr(p.education).map(mapEducation),
    projects: arr(p.projects).map(mapProject),
    certifications: arr(p.certifications).map(mapCertification),
    links: p.links && typeof p.links === "object" ? p.links : {},
  };
}

/** @returns {import("./types.js").ConfidenceMap} */
export function extractConfidence(data) {
  return data && typeof data.confidence === "object" ? data.confidence : {};
}
