'use strict';

/**
 * Durable tool-evidence sidecar — survives Pi compaction.
 * Path: <cwd>/.soveryn/evidence/tools.jsonl  (+ optional session id file)
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

function evidenceDir(cwd) {
  return path.join(path.resolve(cwd || process.cwd()), '.soveryn', 'evidence');
}

function evidencePath(cwd) {
  return path.join(evidenceDir(cwd), 'tools.jsonl');
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  const keys = Object.keys(value).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`).join(',')}}`;
}

function bashCommand(input) {
  if (!input || typeof input !== 'object') return '';
  const o = input;
  return String(o.command || o.cmd || o.script || '');
}

function isChromeBash(cmd) {
  return (
    /\b(google-chrome(?:-stable)?|chromium(?:-browser)?|chrome)\b/i.test(cmd) ||
    /\bCHROME_BIN\b/.test(cmd)
  );
}

function chromeKind(cmd) {
  if (/--dump-dom/i.test(cmd) || /\bdump-dom\b/i.test(cmd)) return 'dump-dom';
  if (/--screenshot/i.test(cmd)) return 'screenshot';
  if (/--print-to-pdf/i.test(cmd)) return 'print-to-pdf';
  if (/--virtual-time-budget/i.test(cmd)) return 'virtual-time';
  if (/\bRuntime\.evaluate\b|\b--eval\b/i.test(cmd)) return 'eval';
  return 'chrome';
}

function chromeTarget(cmd) {
  const fileUrl = String(cmd).match(/file:\/\/[^\s'"]+/i);
  if (fileUrl) return fileUrl[0].replace(/^file:\/\//i, '');
  const html = String(cmd).match(/(?:^|[\s'"=])(\/?[^\s'"]+\.html)\b/i);
  if (html) return html[1];
  return '';
}

/**
 * Chrome dump-dom / screenshot flag nits still collide on kind + target file.
 * Other tools keep exact-input fingerprints.
 */
function fingerprint(toolName, input) {
  let raw = `${toolName || ''}::${stableStringify(input || {})}`;
  if (String(toolName || '') === 'bash') {
    const cmd = bashCommand(input);
    if (isChromeBash(cmd)) {
      raw = `bash::chrome::${chromeKind(cmd)}::${chromeTarget(cmd)}`;
    }
  }
  return crypto.createHash('sha256').update(raw).digest('hex').slice(0, 16);
}

/**
 * stdout-shaped failures that still return tool isError=false
 * (Chrome DT_FAIL dumps, Python tracebacks, Error: lines).
 */
const DEFAULT_LOOP_LIMIT = 3;
const MAX_LOOP_LIMIT = 32;

/** Invalid/NaN/Infinity/0/huge env must not silently disable the loop guard. */
function parseLoopLimit(raw, fallback = DEFAULT_LOOP_LIMIT) {
  const s = raw == null ? '' : String(raw).trim();
  const n = s === '' ? fallback : Number(s);
  if (!Number.isInteger(n) || n < 1 || n > MAX_LOOP_LIMIT) return fallback;
  return n;
}

function looksLikeSoftFail(summary) {
  const text = String(summary || '');
  if (!text) return false;
  return (
    /\bDT_FAIL\b/i.test(text) ||
    /\bDT_ERROR\b/i.test(text) ||
    /verdict\s*=\s*\S*FAIL/i.test(text) ||
    /\bTIMEOUT\b/i.test(text) ||
    /Traceback \(most recent call last\)/.test(text) ||
    /^Error:/m.test(text) ||
    /\b(?:TypeError|ReferenceError|SyntaxError|RangeError):\s/i.test(text)
  );
}

function summarizeContent(content) {
  if (content == null) return '';
  if (typeof content === 'string') return content.slice(0, 2000);
  if (Array.isArray(content)) {
    return content
      .map((c) => {
        if (!c) return '';
        if (typeof c === 'string') return c;
        if (c.type === 'text') return String(c.text || '');
        return JSON.stringify(c).slice(0, 400);
      })
      .join('\n')
      .slice(0, 2000);
  }
  try {
    return JSON.stringify(content).slice(0, 2000);
  } catch (_) {
    return String(content).slice(0, 2000);
  }
}

function appendEvidence(cwd, entry) {
  const dir = evidenceDir(cwd);
  ensureDir(dir);
  const file = evidencePath(cwd);
  const row = {
    ts: new Date().toISOString(),
    ...entry,
  };
  fs.appendFileSync(file, `${JSON.stringify(row)}\n`, 'utf8');
  // Pointer for Kernel after compaction
  fs.writeFileSync(
    path.join(dir, 'LATEST'),
    `${file}\n${row.ts}\t${row.toolName || ''}\t${row.isError ? 'ERR' : 'OK'}\n`,
    'utf8'
  );
  return file;
}

function readRecentEvidence(cwd, { limit = 40 } = {}) {
  const file = evidencePath(cwd);
  if (!fs.existsSync(file)) return [];
  const lines = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean);
  const slice = lines.slice(-limit);
  const out = [];
  for (const line of slice) {
    try {
      out.push(JSON.parse(line));
    } catch (_) {
      /* skip corrupt */
    }
  }
  return out;
}

function hasSuccessfulToolSince(cwd, { names, maxLookback = 30 } = {}) {
  const rows = readRecentEvidence(cwd, { limit: maxLookback });
  const want = names && names.length ? new Set(names) : null;
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    if (r.isError) continue;
    if (!want || want.has(r.toolName)) return r;
  }
  return null;
}

function hasShowmeArtifact(cwd, { maxLookback = 40 } = {}) {
  const rows = readRecentEvidence(cwd, { limit: maxLookback });
  for (let i = rows.length - 1; i >= 0; i--) {
    const r = rows[i];
    if (r.isError) continue;
    const blob = `${r.summary || ''} ${stableStringify(r.details || {})} ${stableStringify(r.input || {})}`;
    if (
      r.toolName === 'open-html' ||
      /\.png\b/i.test(blob) ||
      /screenshot/i.test(blob) ||
      /file:\/\//i.test(blob) ||
      /"screenshotExists"\s*:\s*true/.test(blob)
    ) {
      return r;
    }
  }
  return null;
}

const CLAIM_RE =
  /\b(done|fixed|passed|pass\b|verified|complete[d]?|shipped|works now|all green|visual(?:ly)? (?:ok|done|good|ready))\b/i;

function textLooksLikeProgressClaim(text) {
  if (!text) return false;
  return CLAIM_RE.test(String(text));
}

function recentSuccessCount(cwd, { maxLookback = 20 } = {}) {
  const rows = readRecentEvidence(cwd, { limit: maxLookback });
  return rows.filter((r) => !r.isError).length;
}

module.exports = {
  evidenceDir,
  evidencePath,
  fingerprint,
  bashCommand,
  isChromeBash,
  chromeKind,
  chromeTarget,
  looksLikeSoftFail,
  parseLoopLimit,
  DEFAULT_LOOP_LIMIT,
  MAX_LOOP_LIMIT,
  stableStringify,
  summarizeContent,
  appendEvidence,
  readRecentEvidence,
  hasSuccessfulToolSince,
  hasShowmeArtifact,
  textLooksLikeProgressClaim,
  recentSuccessCount,
  CLAIM_RE,
};
