// build-vocab.mjs — enumerate the AUTHORITATIVE member vocabulary for the two hosts my recall keeps
// mangling, and cache it as JSON. Nothing here is a hand-written list: every name is pulled from a live
// host. Node hosts come from this process's own prototype chains; browser hosts are serialized by the
// page INSIDE real Chromium and read back with --dump-dom, exactly the bounded pattern web-api-probe uses.
// Built-ins only: no acorn, no npm, no parser. Run via `timeout 60s` (Chrome is additionally capped by
// CHROME_TIMEOUT_SEC so a wedged render can never hang the run — RESEARCH 4.1).
import { writeFileSync, mkdtempSync, rmSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { findChrome, CHROME_TIMEOUT_SEC } from '../find-chrome.mjs';

// chain members of an object up its prototype, string keys only, de-duplicated.
function membersOf(root) {
  const seen = new Set();
  const out = [];
  let o = root;
  while (o) {
    let ks = [];
    try { ks = Object.getOwnPropertyNames(o); } catch { ks = []; }
    for (const k of ks) if (typeof k === 'string' && !seen.has(k)) { seen.add(k); out.push(k); }
    try { o = Object.getPrototypeOf(o); } catch { o = null; }
  }
  return out;
}

// ---- node hosts, enumerated in THIS process (no Chrome needed) ----
function nodeVocab() {
  return {
    // process is the host for the stdio/stdin/stdout class of slip
    process: membersOf(process),
    // node's globalThis is the host for settimeout/setinterval/requestAnimationFrame-class slips
    global: (() => {
      const g = (0, eval)('typeof globalThis === "undefined" ? globalThis : globalThis');
      return membersOf(g).concat(Object.keys(g)).filter((v, i, a) => a.indexOf(v) === i).sort();
    })(),
  };
}

// ---- browser hosts, enumerated BY the page inside Chromium ----
function browserProbeHtml() {
  const collect = `
    function chain(o){var seen={},out=[];while(o){var ks;try{ks=Object.getOwnPropertyNames(o)}catch(e){ks=[]}
      for(var i=0;i<ks.length;i++){var k=ks[i];if(typeof k==='string'&&!seen[k]){seen[k]=1;out.push(k)}}
      try{o=Object.getPrototypeOf(o)}catch(e){o=null}}return out}
    function host(n){try{
      if(n==='window')return Object.keys(window).concat(chain(Object.getPrototypeOf(window)));
      if(n==='StringPrototype')return chain(String.prototype);
      var o=window[n];return chain(o);
    }catch(e){return null}}
    var want=['window','document','StringPrototype'];var res={};
    for(var i=0;i<want.length;i++)res[want[i]]=host(want[i]);
    document.getElementById('vocab').textContent=JSON.stringify(res);`;
  return '<!doctype html><meta charset="utf-8"><body><pre id="vocab"></pre><script>' +
    collect + '<\/script></body></html>';
}

function browserVocab() {
  const chrome = findChrome();
  if (!chrome) return { error: 'chrome-not-found' };
  const dir = mkdtempSync(join(tmpdir(), 'soveryn-vocab-'));
  try {
    const htmlPath = join(dir, 'vocab.html');
    writeFileSync(htmlPath, browserProbeHtml());
    const url = pathToFileURL(htmlPath).href;
    const args = ['--headless=new', '--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage',
      '--dump-dom', url];
    const r = spawnSync('timeout', [String(CHROME_TIMEOUT_SEC) + 's', chrome, ...args], {
      encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
    });
    const dom = String(r.stdout || '');
    const m = dom.match(/<pre id="vocab">([\s\S]*?)<\/pre>/i);
    if (!m) return { error: `no-<pre>-in-dom (status=${r.status} sig=${r.signal})` };
    try { return JSON.parse(m[1]); } catch (e) { return { error: 'json-parse: ' + e.message }; }
  } finally { try { rmSync(dir, { recursive: true, force: true }); } catch {} }
}

const nv = nodeVocab();
const bv = browserVocab();
const vocab = {
  generatedAt: new Date().toISOString(),
  chrome: findChrome() || null,
  node: nv,
  browser: bv,
};
const out = new URL('./vocab.json', import.meta.url).pathname;
writeFileSync(out, JSON.stringify(vocab, null, 0));

// self-proof: the exact members tonight's corpus depends on MUST be present, or the fixture below is a
// lie. Print them so a human sees the authority is real, and exit non-zero if a needed anchor is missing.
function has(arr, name) { return Array.isArray(arr) && arr.includes(name); }
const checks = [
  ['node.global', 'setTimeout', has(nv.global, 'setTimeout')],
  ['node.global', 'setInterval', has(nv.global, 'setInterval')],
  ['node.process', 'stdin', has(nv.process, 'stdin')],
  ['node.process', 'stdout', has(nv.process, 'stdout')],
  ['browser.document', 'getElementById', bv.error ? false : has(bv.document, 'getElementById')],
  ['browser.window', 'requestAnimationFrame', bv.error ? false : has(bv.window, 'requestAnimationFrame')],
  ['browser.StringPrototype', 'matchAll', bv.error ? false : has(bv.StringPrototype, 'matchAll')],
];
let bad = 0;
for (const [host, name, ok] of checks) {
  if (!ok) bad++;
  console.log(`  ${ok ? 'PRESENT' : 'MISSING '} ${host}.${name}`);
}
console.log(`  wrote ${out} (${existsSync(out) ? 'ok' : 'FAIL'})  needed-anchor-missing=${bad}`);
process.exit(bad ? 3 : 0);
