/**
 * Shared JSON-LD parsing for content scripts.
 *
 * detect.js and scrape.js each used to parse script[type="application/ld+json"]
 * blocks independently, with two slightly different traversal implementations
 * (scrape.js's flattened @graph arrays; detect.js's didn't) — a page with a
 * JobPosting nested only inside @graph could be missed by detection but found
 * by scraping. One traversal, used by both, removes that divergence risk.
 *
 * Loaded before detect.js and scrape.js in manifest.json's content_scripts
 * array (after dom.js, which this depends on for shadow-root-aware
 * querying). Content scripts share one global scope per injection (no
 * module system), so this declares a plain global function like the rest of
 * the pipeline — not an ES export.
 */

/**
 * Parse every JSON-LD block on the page, flatten any @graph arrays, and
 * return every node whose @type includes `typeName`. Malformed JSON-LD
 * blocks are skipped, not thrown.
 */
function collectJsonLdNodesByType(typeName) {
  const results = [];
  for (const el of querySelectorAllDeep(document, 'script[type="application/ld+json"]')) {
    let json;
    try {
      json = JSON.parse(el.textContent || "");
    } catch {
      continue; // malformed JSON-LD — skip this block
    }
    const stack = Array.isArray(json) ? [...json] : [json];
    while (stack.length) {
      const node = stack.pop();
      if (!node || typeof node !== "object") continue;
      if (Array.isArray(node["@graph"])) stack.push(...node["@graph"]);
      const types = Array.isArray(node["@type"]) ? node["@type"] : [node["@type"]];
      if (types.includes(typeName)) results.push(node);
    }
  }
  return results;
}
