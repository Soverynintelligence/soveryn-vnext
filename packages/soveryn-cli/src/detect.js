'use strict';

/**
 * Phase router signals — auto-select tool pack from cwd / env.
 * Prefer real tools (web pack) over prompt lectures when cathedral/canvas work is detected.
 *
 * Conservative: do NOT trip on incidental *.html demos in soveryn_vnext root.
 * Home dir is not a project — scan ~/sandbox for cathedral/phosphor/canvas work
 * so `soveryn` launched from $HOME still arms the web pack.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const WEB_NAME_RE = /cathedral|phosphor|canvas/i;
const HOME_SANDBOX_SCAN_LIMIT = 40;

function envPack() {
  const raw = process.env.SOVERYN_PACK || process.env.SOVERYN_PRESET || '';
  const v = String(raw).trim().toLowerCase();
  return v || null;
}

function readTextSafe(p, max = 64 * 1024) {
  try {
    const st = fs.statSync(p);
    if (!st.isFile() || st.size > max) return '';
    return fs.readFileSync(p, 'utf8');
  } catch (_) {
    return '';
  }
}

function listTopFiles(cwd, limit = 120) {
  try {
    return fs.readdirSync(cwd).slice(0, limit);
  } catch (_) {
    return [];
  }
}

function readPackagePack(cwd) {
  try {
    const raw = fs.readFileSync(path.join(cwd, 'package.json'), 'utf8');
    const pkg = JSON.parse(raw);
    const v = pkg.soverynPack || pkg.soverynPreset || (pkg.soveryn && pkg.soveryn.pack);
    if (v) return String(v).trim().toLowerCase();
  } catch (_) {
    /* no package.json / invalid */
  }
  // Optional marker file
  for (const name of ['.soveryn-pack', 'SOVERYN_PACK']) {
    const p = path.join(cwd, name);
    if (!fs.existsSync(p)) continue;
    const t = readTextSafe(p, 64).trim().toLowerCase();
    if (t) return t.split(/\s+/)[0];
  }
  return null;
}

function hasCathedralModules(lowerSet) {
  return (
    lowerSet.has('core.mjs') &&
    lowerSet.has('kit.mjs') &&
    lowerSet.has('world.mjs') &&
    lowerSet.has('render.mjs')
  );
}

function htmlHasCanvasOrWebgl(cwd, htmlFiles) {
  for (const f of htmlFiles.slice(0, 8)) {
    const text = readTextSafe(path.join(cwd, f));
    if (!text) continue;
    if (
      /<\s*canvas\b/i.test(text) ||
      /\bgetContext\s*\(\s*['"]webgl/i.test(text) ||
      /type\s*=\s*["']module["']/i.test(text)
    ) {
      return true;
    }
  }
  return false;
}

function scriptsHaveWebglSignals(cwd, scriptFiles) {
  for (const f of scriptFiles.slice(0, 16)) {
    const text = readTextSafe(path.join(cwd, f));
    if (!text) continue;
    if (
      /\bgetContext\s*\(\s*['"]webgl/i.test(text) ||
      /\bWebGL(?:2)?RenderingContext\b/.test(text) ||
      /\bOffscreenCanvas\b/.test(text) ||
      /\bAudioContext\b/.test(text) ||
      /\battachCanvas\b/.test(text)
    ) {
      return true;
    }
  }
  return false;
}

function homeDir() {
  try {
    return path.resolve(process.env.HOME || os.homedir() || '');
  } catch (_) {
    return '';
  }
}

function isHomeDir(abs) {
  const home = homeDir();
  return !!home && path.resolve(abs) === home;
}

function isDir(p) {
  try {
    return fs.statSync(p).isDirectory();
  } catch (_) {
    return false;
  }
}

/**
 * $HOME itself is never a web project. If Kernel launches from home, look at
 * ~/sandbox only — never soveryn_vnext (incidental HTML demos).
 */
function sandboxLooksLikeWeb() {
  const sandbox = path.join(homeDir(), 'sandbox');
  if (!isDir(sandbox)) return false;
  const entries = listTopFiles(sandbox, HOME_SANDBOX_SCAN_LIMIT);
  for (const name of entries) {
    if (!name || name.startsWith('.')) continue;
    if (WEB_NAME_RE.test(name)) return true;
    const child = path.join(sandbox, name);
    if (!isDir(child)) continue;
    if (looksLikeWebProject(child, { skipHomeScan: true })) return true;
    const childEntries = listTopFiles(child);
    const htmlFiles = childEntries.filter((e) => e.toLowerCase().endsWith('.html'));
    if (htmlFiles.length && htmlHasCanvasOrWebgl(child, htmlFiles)) return true;
  }
  return false;
}

/**
 * True when cwd looks like cathedral / HTML-canvas / WebGL work.
 */
function looksLikeWebProject(cwd, opts = {}) {
  if (!cwd) return false;
  const abs = path.resolve(cwd);
  const base = path.basename(abs);

  if (!opts.skipHomeScan && isHomeDir(abs)) {
    return sandboxLooksLikeWeb();
  }

  if (WEB_NAME_RE.test(base)) return true;
  // Path segment e.g. .../sandbox/cathedral81
  const parts = abs.split(path.sep);
  if (parts.some((seg) => WEB_NAME_RE.test(seg))) return true;

  const marker = readPackagePack(abs);
  if (marker === 'web' || marker === 'browser' || marker === 'html' || marker === 'canvas') {
    return true;
  }

  const entries = listTopFiles(abs);
  const lower = new Set(entries.map((e) => e.toLowerCase()));

  if (hasCathedralModules(lower)) return true;

  const htmlFiles = entries.filter((e) => e.toLowerCase().endsWith('.html'));
  const mjsFiles = entries.filter((e) => e.toLowerCase().endsWith('.mjs'));
  const scriptFiles = entries.filter((e) => /\.(mjs|js)$/i.test(e));

  // Strong: ES modules + canvas/webgl HTML host (Exit A shape)
  if (mjsFiles.length >= 2 && htmlHasCanvasOrWebgl(abs, htmlFiles)) return true;

  // Strong: multiple mjs with webgl/audio API usage (cathedral-like sources)
  if (mjsFiles.length >= 2 && scriptsHaveWebglSignals(abs, mjsFiles)) return true;

  // Medium: single html named host.html / index with canvas AND at least one mjs
  if (
    mjsFiles.length >= 1 &&
    (lower.has('host.html') || lower.has('index.html')) &&
    htmlHasCanvasOrWebgl(abs, htmlFiles)
  ) {
    return true;
  }

  return false;
}

/**
 * Resolve pack id from env + cwd auto-detect (no CLI override).
 * Returns null when nothing special — caller falls through to profile/default.
 */
function autoDetectPack(cwd) {
  const fromEnv = envPack();
  if (fromEnv) return fromEnv;
  const abs = path.resolve(cwd || process.cwd());
  const marker = readPackagePack(abs);
  if (marker) return marker;
  if (looksLikeWebProject(abs)) return 'web';
  return null;
}

module.exports = {
  envPack,
  looksLikeWebProject,
  autoDetectPack,
  readPackagePack,
  sandboxLooksLikeWeb,
  WEB_NAME_RE,
};
