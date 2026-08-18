#!/usr/bin/env node
/**
 * Rasterizes the Pathfinder mark from design_handoff_pathfinder_flow/logo/
 * into extension/icons/. Run via `npm run icons`.
 *
 * 16px is rendered from pathfinder-icon-16.svg (tightened bar gaps), never
 * scaled down from the 32px master — see that directory's README.md.
 * Dark-toolbar 16/32px variants are produced by recoloring the light SVGs'
 * hex fills before rasterizing, rather than maintaining separate "-dark"
 * source files for icon-16 (only mark-dark.svg exists as canonical source).
 */
import sharp from "sharp";
import { readFile } from "node:fs/promises";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const LOGO_DIR = path.resolve(__dirname, "../../design_handoff_pathfinder_flow/logo");
const OUT_DIR = path.resolve(__dirname, "../icons");

const GRID = 32; // pathfinder-mark.svg / pathfinder-icon-16.svg viewBox is 0 0 32 32

const LIGHT_TO_DARK = [
  ["#b84a33", "#e0715a"], // accent
  ["#1a1a1a", "#f2f2f0"], // ink
];

function toDark(svg) {
  return LIGHT_TO_DARK.reduce((out, [light, dark]) => out.replaceAll(light, dark), svg);
}

/** Rasterize an SVG string directly at `size`x`size` px — density is chosen
 * so librsvg renders at the exact target resolution instead of rendering at
 * a default size and resizing (which would blur the pill edges). */
async function renderPng(svgString, size, outPath) {
  await sharp(Buffer.from(svgString), { density: 96 * (size / GRID) })
    .resize(size, size)
    .png()
    .toFile(outPath);
}

async function main() {
  await mkdir(OUT_DIR, { recursive: true });

  const mark = await readFile(path.join(LOGO_DIR, "pathfinder-mark.svg"), "utf8");
  const markDark = await readFile(path.join(LOGO_DIR, "pathfinder-mark-dark.svg"), "utf8");
  const icon16 = await readFile(path.join(LOGO_DIR, "pathfinder-icon-16.svg"), "utf8");

  await Promise.all([
    renderPng(icon16, 16, path.join(OUT_DIR, "icon16.png")),
    renderPng(mark, 32, path.join(OUT_DIR, "icon32.png")),
    renderPng(mark, 48, path.join(OUT_DIR, "icon48.png")),
    renderPng(mark, 128, path.join(OUT_DIR, "icon128.png")),
    renderPng(toDark(icon16), 16, path.join(OUT_DIR, "icon16-dark.png")),
    renderPng(markDark, 32, path.join(OUT_DIR, "icon32-dark.png")),
  ]);

  console.log(`Wrote 6 icons to ${path.relative(process.cwd(), OUT_DIR)}/`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
