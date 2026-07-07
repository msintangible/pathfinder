/**
 * Shadow-DOM-aware traversal helpers shared by jsonld.js, detect.js, and
 * scrape.js.
 *
 * querySelectorAll (and TreeWalker) never cross shadow-root boundaries, so a
 * web-component-based ATS UI that renders its job title/description inside a
 * custom element's shadow root is invisible to every selector-based signal
 * detect.js checks and to scrape.js's text extraction. Only *open* shadow
 * roots are handled here — closed roots are unreachable from a content
 * script by design; there is no workaround for that.
 *
 * Loaded first in manifest.json's content_scripts array (before jsonld.js,
 * detect.js, scrape.js) — same shared-global pattern as jsonld.js: content
 * scripts share one global scope per injection, with no module system.
 */

/** Every open shadow root nested anywhere under `root`, depth-first. */
function collectShadowRoots(root, out = []) {
  for (const el of root.querySelectorAll("*")) {
    if (el.shadowRoot) {
      out.push(el.shadowRoot);
      collectShadowRoots(el.shadowRoot, out);
    }
  }
  return out;
}

/** querySelectorAll that also searches inside every open shadow root under `root`. */
function querySelectorAllDeep(root, selector) {
  const results = [];
  for (const r of [root, ...collectShadowRoots(root)]) {
    results.push(...r.querySelectorAll(selector));
  }
  return results;
}
