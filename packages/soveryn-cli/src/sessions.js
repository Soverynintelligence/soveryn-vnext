'use strict';

/**
 * House session index — Kernel/soveryn resume across cwd + harness dirs.
 * Pi --continue is cwd-scoped; cathedral work launched from $HOME would miss it.
 */

const fs = require('fs');
const path = require('path');
const { REPO } = require('./paths');

const SESSION_ROOTS = [
  { harness: 'soveryn-cli', dir: path.join(REPO, 'config', 'soveryn-cli', 'sessions') },
  { harness: 'kernel', dir: path.join(REPO, 'config', 'pi', 'sessions') },
];

function sessionRoots() {
  return SESSION_ROOTS.map((r) => ({ ...r }));
}

function readHeader(file) {
  let fd;
  try {
    fd = fs.openSync(file, 'r');
    const buf = Buffer.alloc(8192);
    const n = fs.readSync(fd, buf, 0, buf.length, 0);
    const line = buf.slice(0, n).toString('utf8').split(/\r?\n/)[0] || '';
    const j = JSON.parse(line);
    if (!j || j.type !== 'session' || !j.id) return null;
    return { id: String(j.id), cwd: j.cwd ? String(j.cwd) : '', timestamp: j.timestamp || '' };
  } catch (_) {
    return null;
  } finally {
    if (fd != null) {
      try {
        fs.closeSync(fd);
      } catch (_) {
        /* ignore */
      }
    }
  }
}

function listJsonl(dir, harness, out) {
  let names;
  try {
    names = fs.readdirSync(dir);
  } catch (_) {
    return;
  }
  for (const name of names) {
    if (name.startsWith('.')) continue;
    const p = path.join(dir, name);
    let st;
    try {
      st = fs.statSync(p);
    } catch (_) {
      continue;
    }
    if (st.isDirectory()) {
      listJsonl(p, harness, out);
      continue;
    }
    if (!name.endsWith('.jsonl') || !st.isFile() || st.size < 32) continue;
    const header = readHeader(p);
    if (!header) continue;
    out.push({
      id: header.id,
      cwd: header.cwd,
      timestamp: header.timestamp,
      file: p,
      mtimeMs: st.mtimeMs,
      size: st.size,
      harness,
    });
  }
}

function listSessions({ limit = 40 } = {}) {
  const out = [];
  for (const root of SESSION_ROOTS) {
    listJsonl(root.dir, root.harness, out);
  }
  out.sort((a, b) => b.mtimeMs - a.mtimeMs);
  if (limit > 0) return out.slice(0, limit);
  return out;
}

function matchSession(query, sessions) {
  const all = sessions || listSessions({ limit: 0 });
  if (!query || query === 'latest' || query === '-') {
    return all[0] || null;
  }
  const q = String(query).trim();
  if (!q) return all[0] || null;
  if (fs.existsSync(q) && q.endsWith('.jsonl')) {
    const st = fs.statSync(q);
    const header = readHeader(q);
    if (header) {
      return {
        id: header.id,
        cwd: header.cwd,
        timestamp: header.timestamp,
        file: path.resolve(q),
        mtimeMs: st.mtimeMs,
        size: st.size,
        harness: q.includes(`${path.sep}config${path.sep}pi${path.sep}`) ? 'kernel' : 'soveryn-cli',
      };
    }
  }
  const lower = q.toLowerCase();
  const hits = all.filter(
    (s) =>
      s.id === q ||
      s.id.startsWith(q) ||
      s.id.toLowerCase().startsWith(lower) ||
      s.file.endsWith(q) ||
      path.basename(s.file).includes(q),
  );
  if (hits.length === 1) return hits[0];
  if (hits.length > 1) {
    const exact = hits.find((s) => s.id === q);
    if (exact) return exact;
    return hits[0];
  }
  return null;
}

function formatSessionLine(s) {
  const when = s.timestamp ? String(s.timestamp).replace('T', ' ').replace(/\.\d+Z$/, 'Z') : '';
  const mb = (s.size / (1024 * 1024)).toFixed(s.size >= 1024 * 1024 ? 1 : 2);
  const short = s.id.slice(0, 8);
  return `${short}  ${when.padEnd(20)}  ${String(s.harness).padEnd(11)}  ${mb}M  ${s.cwd || '-'}`;
}

function latestSession() {
  return listSessions({ limit: 1 })[0] || null;
}

const STALE_MS = 4 * 60 * 60 * 1000;
const STALE_BYTES = 8 * 1024 * 1024;

/** Long compacted threads must not be the default after a kill. */
function sessionIsStale(s) {
  if (!s) return false;
  if (s.size > STALE_BYTES) return true;
  const t = Date.parse(s.timestamp);
  if (Number.isFinite(t) && Date.now() - t > STALE_MS) return true;
  return false;
}

/**
 * Sign-in resume: TTY asks Y/n (default Y). Non-TTY skips unless SOVERYN_RESUME=always.
 * --new / SOVERYN_RESUME=never starts fresh. Explicit --session/--continue skips.
 */
function resumeModeFromEnv(env = process.env) {
  const v = String(env.SOVERYN_RESUME || 'ask').trim().toLowerCase();
  if (['0', 'never', 'no', 'new', 'fresh', 'off'].includes(v)) return 'never';
  if (['1', 'always', 'yes', 'on'].includes(v)) return 'always';
  return 'ask';
}

function decideSignInResume({
  mode = 'ask',
  isTty = false,
  fresh = false,
  printMode = false,
  hasSession = false,
} = {}) {
  if (fresh || printMode || hasSession) return 'skip';
  if (mode === 'never') return 'skip';
  if (mode === 'always') return 'auto';
  if (!isTty) return 'skip';
  return 'ask';
}

function findLiveHarness() {
  const out = [];
  let pids;
  try {
    pids = fs.readdirSync('/proc').filter((n) => /^\d+$/.test(n));
  } catch (_) {
    return out;
  }
  const self = String(process.pid);
  for (const pid of pids) {
    if (pid === self) continue;
    let cmd = '';
    try {
      cmd = fs.readFileSync(`/proc/${pid}/cmdline`, 'utf8').replace(/\0/g, ' ').trim();
    } catch (_) {
      continue;
    }
    if (!cmd) continue;
    if (/\bGROK_AGENT=|\bextglob\b/.test(cmd)) continue;
    const hit =
      /\/bin\/soveryn\b/.test(cmd) ||
      /\/bin\/kernel\b/.test(cmd) ||
      /packages\/soveryn-cli\/src\/cli\.js/.test(cmd) ||
      /scripts\/soveryn-pi/.test(cmd) ||
      /^pi(\s|$)/.test(cmd);
    if (!hit) continue;
    if (/\bsoveryn doctor\b|\bsoveryn status\b|\bsoveryn sessions\b|\bresume --list\b/.test(cmd)) continue;
    let tty = '';
    try {
      const fd0 = fs.readlinkSync(`/proc/${pid}/fd/0`);
      tty = fd0.startsWith('/dev/') ? fd0.replace(/^\/dev\//, '') : fd0;
    } catch (_) {
      tty = '';
    }
    // Skip headless leftovers (Cursor `pi --version` hangs, grok wrappers).
    if (!/^pts\//.test(tty) && !/^tty/.test(tty)) continue;
    out.push({ pid, cmd: cmd.slice(0, 120), tty });
  }
  return out;
}

module.exports = {
  sessionRoots,
  listSessions,
  latestSession,
  matchSession,
  formatSessionLine,
  findLiveHarness,
  readHeader,
  resumeModeFromEnv,
  decideSignInResume,
  sessionIsStale,
};
