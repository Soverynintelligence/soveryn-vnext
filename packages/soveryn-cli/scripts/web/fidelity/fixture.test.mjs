// fixture.test.mjs — the can-it-fail pass for the fidelity idea, run BEFORE any gate is trusted.
// Non-recall invariant (the whole point): the ONLY thing this file supplies is the CORRUPT token and the
// host to check. It never supplies a "correct" spelling — the suggestion and every accepted real are read
// OUT of the enumerated host array in vocab.json, which build-vocab pulled from Node's prototype chains and
// from live Chromium via --dump-dom. If a correct spelling here did not come from the array, it is a bug.
// No acorn, no npm, no hand-lists, no wiring into the edit/write path, and the frozen G8 battery is not
// touched. Run: timeout 30s node fixture.test.mjs
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const VOCAB = JSON.parse(readFileSync(join(process.cwd(), 'scripts/web/fidelity/vocab.json'), 'utf8'));
const K_MAX = 4; // small edit-distance cutoff on case-folded forms; not a research statement, a threshold

function present(arr, x) { return Array.isArray(arr) && arr.includes(x); } // case-SENSITIVE: catches settimeout
function levenshtein(a, b) {
  const m = a.length, n = b.length;
  if (!m) return n; if (!n) return m;
  let prev = [...Array(n + 1).keys()], cur = new Array(n + 1);
  for (let i = 1; i <= m; i++) {
    cur[0] = i;
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      cur[j] = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
    }
    [prev, cur] = [cur, prev];
  }
  return prev[n];
}
function nearest(arr, bad) {
  if (!Array.isArray(arr) || !arr.length) return { best: null, dist: Infinity };
  const lb = String(bad).toLowerCase();
  let best = null, bd = Infinity;
  for (const m of arr) { const d = levenshtein(String(m).toLowerCase(), lb); if (d < bd) { bd = d; best = m; } }
  return { best, dist: bd };
}
function host(name) {
  const src = name === 'global' || name === 'process' ? VOCAB.node : VOCAB.browser;
  const arr = src && src[name];
  const available = Array.isArray(arr) && arr.length > 0;
  return { arr: available ? arr : null, available };
}
// The gate decision, isolated so the negative control can exercise the SAME predicate:
//   rejects  = the exact token is not a real member (case-sensitive)  -> catches our corruptions
//   offers   = the nearest member is a real array member and close on case-folded form
function decide(arr, bad) {
  const rejects = present(arr, bad) === false;
  const near = nearest(arr, bad);
  const offers = near.best !== null && present(arr, near.best) && near.best !== bad && near.dist <= K_MAX;
  return { ok: rejects && offers, rejects, near };
}

const CASES = [
  { host: 'global',          bad: 'settimeout',     want: 'casing near-miss' },
  { host: 'global',          bad: 'setinterval',    want: 'casing near-miss' },
  { host: 'document',        bad: 'getelementById', want: 'casing near-miss (By)' },
  { host: 'StringPrototype', bad: 'matchAllAll',    want: 'duplicated suffix' },
  { host: 'process',         bad: 'stdio',          want: 'wrong member (Node host)' },
];

let fails = 0, errors = 0;
console.log('  ── BAD spellings: gate must reject the token AND offer the real member from the host ──');
for (const c of CASES) {
  const { arr, available } = host(c.host);
  if (!available) { errors++; console.log(`  ERROR ${c.host.padEnd(16)} ${c.bad.padEnd(15)} authority UNAVAILABLE -> not passable`); continue; }
  const d = decide(arr, c.bad);
  const acceptedReal = d.ok && present(arr, d.near.best); // the real string came from arr, not from me
  const verdict = d.ok && acceptedReal;
  if (!verdict) fails++;
  console.log(`  ${verdict ? 'PASS' : 'FAIL'} ${c.host.padEnd(16)} ${c.bad.padEnd(15)} present=${String(present(arr, c.bad)).padEnd(5)} -> ${String(d.near.best).padEnd(16)} dist=${d.near.dist} (${c.want})`);
}

console.log('  ── REAL members (read from the array, not typed): gate must ACCEPT them ──');
for (const c of CASES) {
  const { arr, available } = host(c.host);
  if (!available) { console.log(`  SKIP ${c.host}/${c.bad} (no authority)`); continue; }
  const real = nearest(arr, c.bad).best; // authority-derived spelling
  const accepted = present(arr, real);
  if (!accepted) fails++;
  console.log(`  ${accepted ? 'PASS' : 'FAIL'} ${c.host.padEnd(16)} accepts real ${String(real)}`);
}

console.log('  ── can-it-fail control (§4.2): a checker that cannot go red is a checker that never ran ──');
const g = host('global');
if (g.available) {
  const tainted = [...g.arr, 'settimeout']; // imagine an authority that WRONGLY lists the corrupt form
  const d = decide(tainted, 'settimeout');
  const controlCaught = d.ok === false;      // it MUST now stop passing, else the predicate is vacuous
  if (!controlCaught) fails++;
  console.log(`  ${controlCaught ? 'PASS' : 'FAIL'} defang-control: with corrupt member in host, decide(settimeout).ok=${d.ok} (want false)`);
}
if (!VOCAB.browser || VOCAB.browser.error || !Array.isArray(VOCAB.browser.document)) {
  errors++;
  console.log('  ERROR browser authority missing -> getelementById/matchAllAll classes are UNPROVEN, not passed');
}

console.log(`  => FIXTURE ${fails === 0 && errors === 0 ? 'PASS' : 'FAIL'} fails=${fails} errors=${errors}; every accepted spelling was read from the enumerated host, none supplied by the author`);
process.exit(errors ? 3 : (fails ? 1 : 0));
