/**
 * Shared type definitions (JSDoc typedefs).
 *
 * Plain JS, but every shape is documented here so editors give the same
 * autocomplete/checking a .ts file would. This is the single source of truth
 * for the profile data shapes used across the side panel.
 */

/**
 * @typedef {Object} Experience
 * @property {string|null} title
 * @property {string|null} company
 * @property {string|null} startDate
 * @property {string|null} endDate
 * @property {boolean} current
 * @property {string[]} bullets
 */

/**
 * @typedef {Object} Education
 * @property {string|null} institution
 * @property {string|null} degree
 * @property {string|null} field
 * @property {string|null} year
 */

/**
 * @typedef {Object} Project
 * @property {string|null} name
 * @property {string|null} description
 * @property {string|null} url
 * @property {string[]} technologies
 */

/**
 * @typedef {Object} Certification
 * @property {string|null} name
 * @property {string|null} issuer
 * @property {string|null} date
 * @property {string|null} url
 */

/**
 * The simple, displayed/persisted profile shape (mirrors the backend
 * UserProfile model). Missing data is null or [] — never invented.
 * @typedef {Object} UserProfile
 * @property {string|null} name
 * @property {string|null} email
 * @property {string|null} headline
 * @property {string|null} summary
 * @property {string[]} skills
 * @property {Experience[]} experience
 * @property {Education[]} education
 * @property {Project[]} projects
 * @property {Certification[]} certifications
 * @property {Record<string,string>} links
 */

/**
 * Per-field extraction confidence (0..1), keyed by profile field name.
 * Absent key = unknown confidence. Not currently surfaced in the UI.
 * @typedef {Record<string, number>} ConfidenceMap
 */

/**
 * Raw repository data as fetched from the GitHub API, before the agent
 * interprets it. @see backend/schemas/profile.py's RawGitHubRepo.
 * @typedef {Object} RawGitHubRepo
 * @property {string} name
 * @property {string|null} description
 * @property {string[]} languages
 * @property {string[]} topics
 * @property {string|null} url
 * @property {number|null} stars
 */

/**
 * The raw per-source content actually fed to the agent — lets the UI show
 * the user what was found in each source (CV, LinkedIn, GitHub, portfolio),
 * separate from the AI-merged UserProfile.
 * @typedef {Object} ImportSources
 * @property {string|null} resume_text
 * @property {string|null} linkedin_text
 * @property {string|null} github_profile
 * @property {RawGitHubRepo[]} github_repositories
 * @property {string|null} portfolio_text
 */

/**
 * @typedef {Object} ImportResult
 * @property {boolean} ok
 * @property {UserProfile} [profile]
 * @property {ConfidenceMap} [confidence]
 * @property {ImportSources} [sources]
 * @property {string|null} [profileId] backend id of the persisted profile — needed to reference it later (e.g. resume generation)
 * @property {string} [error]
 */

export {}; // marks this file as a module
