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
 * @property {string[]} skills
 * @property {Experience[]} experience
 * @property {Education[]} education
 * @property {Project[]} projects
 * @property {Certification[]} certifications
 * @property {Record<string,string>} links
 */

/**
 * Per-field extraction confidence (0..1). Keys are ProfileField values.
 * Absent key = unknown confidence (not flagged).
 * @typedef {Record<string, number>} ConfidenceMap
 */

/**
 * @typedef {Object} ImportResult
 * @property {boolean} ok
 * @property {UserProfile} [profile]
 * @property {ConfidenceMap} [confidence]
 * @property {string} [error]
 */

export {}; // marks this file as a module
