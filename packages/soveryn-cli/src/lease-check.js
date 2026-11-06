'use strict';
/**
 * Lease check for resume paths (revamp phase 1, 2026-11-05).
 * bin/soveryn-pi150 only checks the lease when --session is in raw argv;
 * `resume`, `-c/--continue` and the sign-in resume prompt inject --session
 * inside cli.js, so they call this before launching Pi.
 * Uses soveryn/kernel_desk/lease.py (exit 0 acquired, 3 held). This pid is
 * the wrapper's pid (exec), so a lease the wrapper already took is ours.
 */
const path = require('path');
const { spawnSync } = require('child_process');

function leaseRoot(repo) {
  const cli = process.env.SOVERYN_CLI_DIR || path.join(repo, 'config', 'soveryn-cli');
  return path.join(cli, 'sessions');
}

/** Returns {ok:true} or {ok:false, code, message}. Never throws. */
function acquireLease(repo, sessionFile, opts = {}) {
  if (process.env.SOVERYN_LEASE_SKIP === '1') return { ok: true, skipped: true };
  const leasePy = path.join(repo, 'soveryn', 'kernel_desk', 'lease.py');
  const py = opts.python || '/usr/bin/python3';
  const r = spawnSync(py, [leasePy, 'acquire', '--root', opts.root || leaseRoot(repo),
    '--session', String(sessionFile), '--owner', 'cli', '--pid', String(opts.pid || process.pid),
    '--token', process.env.SOVERYN_LEASE_TOKEN || ''], { encoding: 'utf8' });
  if (r.error) return { ok: true, skipped: true, message: `lease check skipped (${r.error.message})` };
  if (r.status === 0) return { ok: true };
  return { ok: false, code: r.status, message: (r.stderr || '').trim() || `lease held (exit ${r.status})` };
}

const fs = require('fs');

function pidStart(pid) {
  try {
    const stat = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
    const rest = stat.slice(stat.lastIndexOf(')') + 1).trim().split(/\s+/);
    return rest.length > 19 ? rest[19] : null;
  } catch (_) {
    return null;
  }
}

/** Live leases held by some other pid (same liveness rule as lease.py). */
function otherLiveLeases(root, selfPid = process.pid) {
  const dir = path.join(root, '.leases');
  let names = [];
  try { names = fs.readdirSync(dir).filter((n) => n.endsWith('.json')); } catch (_) { return []; }
  const out = [];
  for (const n of names) {
    try {
      const l = JSON.parse(fs.readFileSync(path.join(dir, n), 'utf8'));
      const pid = Number(l.pid || 0);
      if (pid > 0 && pid !== selfPid && pidStart(pid) !== null && pidStart(pid) === String(l.pid_start)) out.push(l);
    } catch (_) { /* unreadable lease: ignore */ }
  }
  return out;
}

/** Pi's own --resume/-r picker can't be lease-checked per pick: refuse while any other writer holds a thread. */
function hasPiPickerFlag(args) {
  return (args || []).some((a) => a === '--resume' || a === '-r');
}

module.exports = { acquireLease, leaseRoot, otherLiveLeases, hasPiPickerFlag };
