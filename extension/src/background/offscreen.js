/**
 * Runs inside the offscreen document created by index.js. The MV3 service
 * worker has no window/matchMedia, so this is the only place that can read
 * the browser's toolbar theme — reports it once on load and again on every
 * change, so the toolbar icon can track a live theme switch.
 */
const media = window.matchMedia("(prefers-color-scheme: dark)");

function reportColorScheme() {
  chrome.runtime.sendMessage({
    type: "COLOR_SCHEME_CHANGED",
    payload: { isDark: media.matches },
  });
}

media.addEventListener("change", reportColorScheme);
reportColorScheme();
