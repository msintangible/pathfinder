# Pathfinder — UI/UX design requirements (v1)

Full designer brief: `Pathfinder_UIUX_Design_Requirements.docx`. This file is the engineering-facing condensed version for reference during implementation.

## Non-negotiable rule
Never fabricate experience. Every tailored resume shows a diff of what changed. Confidence level (known ATS / unknown ATS / keywords-only) must be visually distinct, never uniform. No inflated numbers or false-cheerful copy anywhere, including progress/metrics screens.

## Four page-detection states (core of the popup)
| State | Confidence | Primary action | Notes |
|---|---|---|---|
| No job page | neutral | none (secondary: view profile) | Default/most common state. Never styled as warning or error. |
| Known ATS | high | filled primary button: "Tailor my resume" | Only state with a high-emphasis filled CTA. |
| Unknown ATS | partial | secondary button: "Tailor with what's here" | Must name exactly what's missing in the copy. |
| Keywords only | low | no tailor option — "Copy keywords instead" | Do not offer full tailoring from thin data. |

## Tailoring flow
1. Loading — real sub-steps with checkmarks, not a generic spinner.
2. Diff review — changed lines visually distinct from unchanged original. Most important screen in the product.
3. Decision — download always available; autofill only offered on known-ATS (high confidence), always behind an explicit confirmation step before anything is submitted.

## Color meaning (not decorative)
- Neutral/resting: calm muted tone, default state.
- One reserved accent: "AI acting now" only — tailor button, loading, diff highlight.
- Amber: informational catch (unknown ATS, duplicate-application notice) — not an error.
- Red: genuine failure only (backend down, parse failure).
- Green: held back for a real-world outcome, not routine resume generation.

## Interaction rules
- One primary (filled) CTA per screen, max.
- All debug/dev info (backend URL, connection status, raw scraped JSON, internal ids) hidden behind a dev-mode flag — never in the default build a pilot user sees.
- Progressive disclosure: show only what's relevant to current state.
- Returning users see a quiet factual trace of recent activity (e.g. "2 applications this week"), not a blank screen.
- Duplicate-listing detection uses amber "helpful catch" styling, not red.
- Metrics screen leads with a count the user controls ("applications tailored"), not a raw response rate, especially at low sample sizes.

## Voice
Plain, calm, present tense. No raw error strings/JSON ever shown to users. No guilt-based nudges, streaks, or artificial urgency anywhere in the product.

## Pilot success criteria
- Time from primary-action click to completed tailored resume: under 15s on known-ATS.
- Zero backend/debug info visible in default build.
- No more than one filled CTA visible per screen.
- A first-time user reaches a completed tailored resume with nothing explained out loud.

Full detail, exact copy strings, and the color/table breakdowns: see the docx.
