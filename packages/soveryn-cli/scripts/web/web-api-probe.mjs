#!/usr/bin/env node
/**
 * web-api-probe — evaluate typeof/existence of named browser APIs in real Chromium.
 * Usage: node web-api-probe.mjs [API...]
 *        node web-api-probe.mjs --json AudioContext WebGL2RenderingContext canvas.getContext
 * Exit 0 always when Chrome ran; JSON on stdout. Exit 2 if Chrome missing.
 */
import { spawnSync } from 'node:child_process';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { findChrome, CHROME_TIMEOUT_SEC } from './find-chrome.mjs';

const DEFAULT_APIS = [
  'AudioContext',
  'webkitAudioContext',
  'OfflineAudioContext',
  'WebGLRenderingContext',
  'WebGL2RenderingContext',
  'OffscreenCanvas',
  'requestAnimationFrame',
  'PointerEvent',
  'ResizeObserver',
  'devicePixelRatio',
  'HTMLCanvasElement',
  'CanvasRenderingContext2D',
];

function parseArgs(argv) {
  const out = { json: true, apis: [], help: false };
  for (const a of argv) {
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--json') out.json = true;
    else if (a === '--text') out.json = false;
    else if (a.startsWith('-')) {
      console.error(`unknown flag: ${a}`);
      process.exit(1);
    } else out.apis.push(a);
  }
  if (!out.apis.length) out.apis = DEFAULT_APIS;
  return out;
}

function buildProbeHtml(apis) {
  const list = JSON.stringify(apis);
  return `<!doctype html><html><head><meta charset="utf-8"><title>soveryn-web-api-probe</title></head><body><pre id="out"></pre><script>
(function () {
  var names = ${list};
  var result = { ok: true, engine: "chromium-headless", apis: {}, notes: [] };
  function resolve(path) {
    var parts = String(path).split(".");
    var cur = window;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return { exists: false, typeof: "undefined", value: null };
      cur = cur[parts[i]];
    }
    var t = typeof cur;
    return { exists: t !== "undefined", typeof: t };
  }
  for (var i = 0; i < names.length; i++) {
    var name = names[i];
    try {
      if (name === "canvas.getContext") {
        var gl2 = null, gl = null, c2d = null;
        try { gl2 = document.createElement("canvas").getContext("webgl2"); } catch (e) {}
        try {
          var c1 = document.createElement("canvas");
          gl = c1.getContext("webgl") || c1.getContext("experimental-webgl");
        } catch (e) {}
        try { c2d = document.createElement("canvas").getContext("2d"); } catch (e) {}
        result.apis[name] = {
          exists: true,
          typeof: "function",
          webgl2: !!gl2,
          webgl: !!gl,
          canvas2d: !!c2d
        };
      } else {
        result.apis[name] = resolve(name);
      }
    } catch (e) {
      result.apis[name] = { exists: false, typeof: "error", error: String(e && e.message || e) };
    }
  }
  try {
    result.userAgent = navigator.userAgent;
  } catch (e) {
    result.notes.push("no userAgent");
  }
  document.getElementById("out").textContent = JSON.stringify(result);
  document.title = "SOVERYN_PROBE_OK";
})();
</script></body></html>`;
}

function extractJson(dom) {
  const m = String(dom).match(/<pre id="out">([\s\S]*?)<\/pre>/i);
  if (m) {
    try { return JSON.parse(m[1]); } catch (_) {}
  }
  const m2 = String(dom).match(/\{[\s\S]*"apis"[\s\S]*\}/);
  if (m2) {
    try { return JSON.parse(m2[0]); } catch (_) {}
  }
  return null;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    console.log(`Usage: web-api-probe.mjs [--json|--text] [API...]
Probes named browser APIs in real Chromium (headless). Default API list covers Audio/WebGL/canvas.
Chrome timeout: ${CHROME_TIMEOUT_SEC}s (SOVERYN_CHROME_TIMEOUT).`);
    process.exit(0);
  }

  const chrome = findChrome();
  if (!chrome) {
    const payload = {
      ok: false,
      engine: null,
      error: 'Chrome/Chromium not found. Install google-chrome or set CHROME_BIN. Falling back unavailable — do not invent browser APIs.',
      apis: Object.fromEntries(opts.apis.map((a) => [a, { exists: null, typeof: 'unknown', probed: false }])),
    };
    console.log(JSON.stringify(payload, null, 2));
    process.exit(2);
  }

  const dir = mkdtempSync(join(tmpdir(), 'soveryn-web-probe-'));
  const htmlPath = join(dir, 'probe.html');
  try {
    writeFileSync(htmlPath, buildProbeHtml(opts.apis));
    const fileUrl = pathToFileURL(htmlPath).href;
    const args = [
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--disable-dev-shm-usage',
      '--dump-dom',
      fileUrl,
    ];
    const r = spawnSync('timeout', [String(CHROME_TIMEOUT_SEC) + 's', chrome, ...args], {
      encoding: 'utf8',
      maxBuffer: 8 * 1024 * 1024,
    });
    const dom = `${r.stdout || ''}`;
    const parsed = extractJson(dom);
    if (!parsed) {
      const fail = {
        ok: false,
        engine: chrome,
        error: `Chrome probe failed (status=${r.status}, signal=${r.signal}). stderr=${(r.stderr || '').slice(0, 500)}`,
        apis: {},
      };
      console.log(JSON.stringify(fail, null, 2));
      process.exit(1);
    }
    parsed.chrome = chrome;
    parsed.timeoutSec = CHROME_TIMEOUT_SEC;
    if (opts.json) {
      console.log(JSON.stringify(parsed, null, 2));
    } else {
      for (const [k, v] of Object.entries(parsed.apis || {})) {
        console.log(`${k}\t${v.exists}\t${v.typeof}${v.webgl2 != null ? `\twebgl2=${v.webgl2}\twebgl=${v.webgl}\t2d=${v.canvas2d}` : ''}`);
      }
    }
    process.exit(0);
  } finally {
    try { rmSync(dir, { recursive: true, force: true }); } catch (_) {}
  }
}

main();
