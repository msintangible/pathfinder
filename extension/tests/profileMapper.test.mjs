/**
 * Unit tests for the schema bridge (normalizeProfile / emptyProfile).
 * Pure logic — no DOM — so it runs directly under Node ESM.
 *
 * Run via: npm test
 */

import { normalizeProfile, emptyProfile, extractConfidence } from "../src/shared/profileMapper.js";

let pass = 0;
let fail = 0;
function test(name, fn) {
  try { fn(); console.log(`✓ ${name}`); pass++; }
  catch (err) { console.log(`✗ ${name}\n    ${err.message}`); fail++; }
}
function assert(cond, msg) { if (!cond) throw new Error(msg || "assertion failed"); }
const eq = (a, b, m) => assert(JSON.stringify(a) === JSON.stringify(b), `${m}: got ${JSON.stringify(a)}`);

test("null/undefined → empty profile (never invents)", () => {
  eq(normalizeProfile(null), emptyProfile(), "null");
  eq(normalizeProfile(undefined), emptyProfile(), "undefined");
});

test("rich agent shape → simple shape, skills merged + deduped", () => {
  const rich = {
    name: "Maya",
    technical_skills: ["Docker"],
    programming_languages: ["Python", "python"], // dupe across case
    frameworks: ["FastAPI"],
    soft_skills: ["Communication"],
    work_experience: [
      { title: "Eng", company: "Acme", start_date: "2020", end_date: "2022", current: false, bullets: ["Built X"] },
    ],
    education: [{ institution: "ATU", degree: "BSc", field: "CS", end_date: "2020" }],
    projects: [{ name: "P", description: "d", technologies: ["Go"] }],
    certifications: [{ name: "AWS", issuer: "Amazon" }],
    links: { github: "https://github.com/maya" },
  };
  const p = normalizeProfile(rich);
  eq(p.name, "Maya", "name");
  eq(p.skills, ["Docker", "Python", "FastAPI", "Communication"], "skills merged+deduped");
  eq(p.experience.length, 1, "experience count");
  eq(p.experience[0].startDate, "2020", "experience start mapped");
  eq(p.education[0].year, "2020", "education year from end_date");
  eq(p.projects[0].technologies, ["Go"], "project tech");
  eq(p.certifications[0].issuer, "Amazon", "cert issuer");
  eq(p.links.github, "https://github.com/maya", "links");
});

test("already-simple shape passes through", () => {
  const simple = {
    name: "Dev", email: "d@x.com", skills: ["TS"],
    experience: [{ title: "X", company: "Y", startDate: "2021", endDate: null, current: true, bullets: [] }],
    education: [], projects: [], certifications: [], links: {},
  };
  const p = normalizeProfile(simple);
  eq(p.skills, ["TS"], "skills");
  eq(p.experience[0].current, true, "current preserved");
  eq(p.email, "d@x.com", "email");
});

test("wrapped { profile, confidence } payload", () => {
  const payload = { profile: { name: "Z", skills: ["A"] }, confidence: { name: 0.9, skills: 0.4 } };
  eq(normalizeProfile(payload).name, "Z", "unwraps profile");
  eq(extractConfidence(payload), { name: 0.9, skills: 0.4 }, "confidence extracted");
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
