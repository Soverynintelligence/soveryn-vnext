'use strict';

/**
 * G8_OUTPUT_FIDELITY — generation-integrity probes.
 * Length + Unicode code-point comparison; deliberate can-it-fail cases for
 * corrupted API-ish identifiers (matchAllAll, upppercase, @@keyframes, config/ppi).
 */

const { assertExact, codePoints } = require('./assert');

/** Canonical good token → common corrupted / invented doubles */
const CORRUPTION_CASES = Object.freeze([
  { good: 'matchAll', bad: 'matchAllAll', label: 'matchAll-doubled' },
  { good: 'uppercase', bad: 'upppercase', label: 'uppercase-extra-p' },
  { good: '@keyframes', bad: '@@keyframes', label: 'keyframes-doubled-at' },
  { good: 'config/pi', bad: 'config/ppi', label: 'pi-path-doubled-p' },
  { good: 'getContext', bad: 'getContexxt', label: 'getContext-typo' },
  { good: 'AudioContext', bad: 'AudioContex', label: 'AudioContext-truncated' },
]);

/**
 * Length + code-point fidelity compare. Returns { ok, detail } (does not throw).
 */
function compareFidelity(actual, expected, label) {
  const a = String(actual);
  const e = String(expected);
  const tag = label || 'fidelity';
  if (a.length !== e.length) {
    return {
      ok: false,
      detail: `${tag}: length ${a.length} !== ${e.length}`,
      actual: a,
      expected: e,
    };
  }
  const ac = codePoints(a);
  const ec = codePoints(e);
  for (let i = 0; i < ac.length; i += 1) {
    if (ac[i] !== ec[i]) {
      return {
        ok: false,
        detail:
          `${tag}: code point at ${i}: U+${ac[i].toString(16).toUpperCase()}` +
          ` !== U+${ec[i].toString(16).toUpperCase()}`,
        actual: a,
        expected: e,
      };
    }
  }
  return { ok: true, detail: `${tag}: exact`, actual: a, expected: e };
}

/**
 * Run corruption battery:
 * - good≡good must pass assertExact
 * - bad≡good must throw ASSERT_EXACT (can-it-fail)
 * - real surface checks where applicable (String.prototype.matchAll exists; matchAllAll does not)
 */
function runFidelityProbes() {
  const results = [];

  for (const c of CORRUPTION_CASES) {
    try {
      assertExact(c.good, c.good, `${c.label}-identity`);
      results.push({ case: c.label, phase: 'identity', ok: true });
    } catch (e) {
      results.push({ case: c.label, phase: 'identity', ok: false, detail: e.message });
      continue;
    }

    let threw = false;
    try {
      assertExact(c.bad, c.good, `${c.label}-corrupt`);
    } catch (e) {
      threw = e.code === 'ASSERT_EXACT';
      results.push({
        case: c.label,
        phase: 'corrupt-must-fail',
        ok: threw,
        detail: threw ? 'threw ASSERT_EXACT' : `wrong error: ${e.code || e.message}`,
      });
      continue;
    }
    results.push({
      case: c.label,
      phase: 'corrupt-must-fail',
      ok: false,
      detail: 'DID NOT THROW — fidelity defanged',
    });
  }

  // Real surface: matchAll exists on String.prototype; invented matchAllAll must not
  const hasMatchAll = typeof String.prototype.matchAll === 'function';
  const hasMatchAllAll = typeof String.prototype.matchAllAll === 'function';
  results.push({
    case: 'String.prototype.matchAll',
    phase: 'surface',
    ok: hasMatchAll === true,
    detail: hasMatchAll ? 'typeof function' : 'MISSING on runtime',
  });
  results.push({
    case: 'String.prototype.matchAllAll',
    phase: 'surface-invented',
    ok: hasMatchAllAll === false,
    detail: hasMatchAllAll
      ? 'INVENTED member present — unexpected'
      : 'absent as required (not a real API)',
  });

  // Path fidelity: config/pi vs config/ppi via compareFidelity
  const pathCmp = compareFidelity('config/pi', 'config/pi', 'path-pi');
  results.push({ case: 'config/pi', phase: 'path-identity', ok: pathCmp.ok, detail: pathCmp.detail });
  const pathBad = compareFidelity('config/ppi', 'config/pi', 'path-ppi');
  results.push({
    case: 'config/ppi',
    phase: 'path-corrupt',
    ok: pathBad.ok === false,
    detail: pathBad.ok ? 'WRONGLY matched' : pathBad.detail,
  });

  const ok = results.every((r) => r.ok);
  return { ok, results, cases: CORRUPTION_CASES };
}

/**
 * Deliberate fail case for doctor --self-test: corrupted token must be rejected.
 */
function deliberateFailCase() {
  try {
    assertExact('matchAllAll', 'matchAll', 'g8-deliberate-fail');
    return { ok: false, detail: 'assertExact accepted matchAllAll === matchAll — DEFANGED' };
  } catch (e) {
    if (e.code === 'ASSERT_EXACT') {
      return { ok: true, detail: 'deliberate fail threw ASSERT_EXACT as required' };
    }
    return { ok: false, detail: `unexpected: ${e.message}` };
  }
}

module.exports = {
  CORRUPTION_CASES,
  compareFidelity,
  runFidelityProbes,
  deliberateFailCase,
  codePoints,
};
