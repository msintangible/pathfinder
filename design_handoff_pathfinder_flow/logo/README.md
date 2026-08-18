# Pathfinder mark — "the cairn"

Three descending pill bars — the confidence meter, stacked. The mark is built
from the shape the product repeats most (see `src/sidepanel/shared/confidenceMeter.js`
in the extension), so the icon and the interface share one vocabulary. Neutral
by default; the top bar carries terracotta. This directory is the binding
source of truth for the mark — treat every rule below as a constraint, not a
suggestion.

## Files

| File | Use |
|---|---|
| `pathfinder-mark.svg` | Standalone mark, light theme. 32×32 grid. |
| `pathfinder-mark-dark.svg` | Standalone mark, dark theme. |
| `pathfinder-mark-mono.svg` | One ink, `fill="currentColor"` on all three bars — embossing, favicons under 16px, single-colour print, and any React/DOM context that wants to inherit text color. |
| `pathfinder-icon-16.svg` | 16px-only geometry. Vertical gaps tightened to 3 units (from 3.5) so the three bars survive rasterisation at that size. Do not fix this to match the 32px master — that's the point of the file. |
| `pathfinder-lockup.svg` | Horizontal lockup — mark + "pathfinder" wordmark, light theme. |
| `pathfinder-lockup-dark.svg` | Horizontal lockup, dark theme. |

## Construction

- 32-unit grid. Bars are 5 tall, radius 2.5 (full pill), gap 3.5 (3 at 16px — see above).
- Widths step 22 / 16 / 10 — a consistent 6-unit decrement.
- Left edges align at x=5. The stack is optically flush-left, never centered.
- Clear space on all sides equals one bar height (5 units, or 15.6% of the
  mark's width). Nothing else enters it. On the standalone mark files this is
  simply the inset from the 32×32 viewBox edge to the bars.
- In the lockup, the gap between the mark's right edge and the wordmark's
  left edge equals two bar heights (10 units). Cap height of the wordmark
  matches the mark's height (22 units, bar-1-top to bar-3-bottom) — the
  wordmark is sized off the font's cap-height metric, not a visual guess,
  even though the rendered text is lowercase. The lockup canvas is then the
  actual ink bounding box of (mark ∪ wordmark) padded by the same 5-unit
  clear space on all four outer edges; ascenders/descenders in the wordmark
  are part of the lockup's own content, not something encroaching on the
  standalone mark's isolated clear zone, so they're allowed to extend past
  the mark's own 5..27 band as long as the combined shape still carries its
  own uniform margin.

## Colour

| | Light | Dark |
|---|---|---|
| Top bar (accent, exactly one bar, always the top one) | `#b84a33` | `#e0715a` |
| Lower two bars (ink) | `#1a1a1a` | `#f2f2f0` |
| Wordmark | same as ink | same as ink |

Never the light-mode accent on a dark surface — contrast fails.

Mono fallback is one ink color for all three bars via `currentColor`; the
Chrome extension resolves it to `#8a8a88` (its existing `--label` design
token) when it needs a single flat icon for both toolbar themes — see
`extension/scripts/build-icons.mjs`.

## Wordmark

IBM Plex Sans 600 (SemiBold), lowercase always — no title case, no caps —
tracking −0.03em. The Chrome extension (`extension/`) is plain JS with no
bundler and does not bundle IBM Plex Sans anywhere. Per the standing rule for
that case, the wordmark in `pathfinder-lockup.svg` / `-dark.svg` is **not**
live text and does not substitute a similar system sans — it's the real IBM
Plex Sans SemiBold glyph outlines, converted to vector paths and baked into
the SVG, so the lockup renders identically with zero font dependency.

Provenance, for anyone regenerating this: the static SemiBold instance was
produced from Google Fonts' variable `IBMPlexSans[wdth,wght].ttf` via
`fonttools varLib.instancer -o IBMPlexSans-SemiBold.ttf IBMPlexSans-VF.ttf
wght=600 wdth=100`, then glyph paths were extracted with `opentype.js`
(`font.charToGlyph(ch).getPath(x, baselineY, fontSize)`), sized so the font's
`OS/2.sCapHeight` metric equals 22 units, with −0.03em tracking applied
between glyphs manually (`opentype.js` doesn't support letter-spacing in
`getPath` directly). Neither `fonttools` nor `opentype.js` nor the font file
itself needs to ship with the extension — the output is static path data.

## Misuse

Don't centre the bars. Don't colour more than one bar. Don't square the
ends. Don't rotate or skew. Don't add a rounded-square plate behind the
mark. No gradients.
