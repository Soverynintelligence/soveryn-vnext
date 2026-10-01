'use strict';

/**
 * Exact string assert by Unicode code point (not fuzzy includes / substrings).
 * Gate 2 — a test must not be able to defang itself via truncated/mangled output.
 *
 * Uses code-point iteration so surrogate pairs compare as one character.
 */
function codePoints(str) {
  const s = String(str);
  const out = [];
  for (const ch of s) {
    out.push(ch.codePointAt(0));
  }
  return out;
}

function assertExact(actual, expected, label) {
  const a = codePoints(actual);
  const e = codePoints(expected);
  const tag = label ? ` (${label})` : '';
  if (a.length !== e.length) {
    const err = new Error(
      `assertExact failed${tag}: length ${a.length} !== ${e.length}` +
        `\n  actual:   ${JSON.stringify(String(actual))}` +
        `\n  expected: ${JSON.stringify(String(expected))}`
    );
    err.code = 'ASSERT_EXACT';
    throw err;
  }
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== e[i]) {
      const err = new Error(
        `assertExact failed${tag}: code point at index ${i}:` +
          ` U+${a[i].toString(16).toUpperCase()} !== U+${e[i].toString(16).toUpperCase()}` +
          `\n  actual:   ${JSON.stringify(String(actual))}` +
          `\n  expected: ${JSON.stringify(String(expected))}`
      );
      err.code = 'ASSERT_EXACT';
      throw err;
    }
  }
  return true;
}

module.exports = { assertExact, codePoints };
