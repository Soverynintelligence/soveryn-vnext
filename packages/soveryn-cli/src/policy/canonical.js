'use strict';

/**
 * Gate 4 — single-character / case corruption is first-class.
 * Canonical-name normalisation for profile ids, provider ids, and critical literals.
 */

/** Names the harness depends on; boot asserts these survive round-trip normalisation. */
const CRITICAL_NAMES = Object.freeze([
  'flash',
  'glm',
  'aetheria',
  'qwen3.8-flash-next',
  'soveryn-flash',
  'soveryn-glm',
  'soveryn-aetheria',
  'glm-5.3-flash',
]);

/**
 * Normalise an id: trim, NFC, lower-case ASCII letters only via toLowerCase.
 * Does not strip dots/digits/hyphens (model ids like qwen3.8-flash-next).
 */
function canonicalizeId(id) {
  if (id == null) return '';
  return String(id).normalize('NFC').trim().toLowerCase();
}

/**
 * Resolve a profile/provider key against a map using canonical match.
 * Returns the canonical key present in map, or null.
 */
function resolveCanonicalKey(map, id) {
  const want = canonicalizeId(id);
  if (!want) return null;
  if (Object.prototype.hasOwnProperty.call(map, want)) return want;
  for (const key of Object.keys(map)) {
    if (canonicalizeId(key) === want) return key;
  }
  return null;
}

/**
 * Boot-time assertion: every CRITICAL_NAME round-trips, and duplicates in the
 * list are intentional aliases only when canonicalize equal.
 */
function assertCriticalNames() {
  const seen = new Map();
  for (const name of CRITICAL_NAMES) {
    const canon = canonicalizeId(name);
    if (canon !== name) {
      const err = new Error(
        `CRITICAL name corruption: ${JSON.stringify(name)} → ${JSON.stringify(canon)}`
      );
      err.code = 'CANONICAL_CORRUPT';
      throw err;
    }
    // code-point identity with itself
    const cps = [...name].map((c) => c.codePointAt(0));
    const rebuilt = String.fromCodePoint(...cps);
    if (rebuilt !== name) {
      const err = new Error(
        `CRITICAL name code-point rebuild failed: ${JSON.stringify(name)}`
      );
      err.code = 'CANONICAL_CORRUPT';
      throw err;
    }
    if (seen.has(canon) && seen.get(canon) !== name) {
      // same canon from two distinct spellings — flag
      const err = new Error(
        `CRITICAL name collision: ${JSON.stringify(seen.get(canon))} vs ${JSON.stringify(name)}`
      );
      err.code = 'CANONICAL_COLLISION';
      throw err;
    }
    seen.set(canon, name);
  }
  return { ok: true, count: CRITICAL_NAMES.length };
}

module.exports = {
  CRITICAL_NAMES,
  canonicalizeId,
  resolveCanonicalKey,
  assertCriticalNames,
};
