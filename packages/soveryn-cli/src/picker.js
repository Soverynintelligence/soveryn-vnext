'use strict';

const { spawnSync } = require('child_process');
const readline = require('readline');
const { listProfileIds } = require('./profiles');
const { probe } = require('./health');
const {
  colorBrand,
  colorOk,
  colorDown,
  colorParked,
  colorAccent,
  colorMuted,
  shortEndpoint,
  wantsColor,
} = require('./chrome');

async function buildRows(data) {
  const ids = listProfileIds(data);
  const rows = [];
  for (const id of ids) {
    const p = data.profiles[id];
    let health = '—';
    if (p.enabled) {
      const r = await probe(p, 1000);
      health = r.ok ? '✓' : '✗';
    } else {
      health = 'parked';
    }
    const c = wantsColor(process.stderr);
    const ep = shortEndpoint(p.baseUrl);
    const labelPlain = `${id.padEnd(10)} ${String(p.displayName).padEnd(16)} ${health.padEnd(7)} ${p.modelId}  ${ep}`;
    let hCol = health;
    if (health === '✓') hCol = colorOk('✓', c);
    else if (health === '✗') hCol = colorDown('✗', c);
    else if (health === 'parked') hCol = colorParked('parked', c);
    const label = `${colorAccent(id.padEnd(10), c)} ${String(p.displayName).padEnd(16)} ${hCol.padEnd(7)} ${p.modelId}  ${colorMuted(ep, c)}`;
    rows.push({
      id,
      displayName: p.displayName,
      enabled: p.enabled !== false,
      disabledReason: p.disabledReason || '',
      modelId: p.modelId,
      baseUrl: p.baseUrl,
      health,
      label: c ? label : labelPlain,
      labelPlain,
    });
  }
  return rows;
}

function fzfAvailable() {
  const r = spawnSync('bash', ['-lc', 'command -v fzf'], { encoding: 'utf8' });
  return r.status === 0 && r.stdout.trim().length > 0;
}

function pickWithFzf(rows) {
  const input = rows.map((r) => r.label).join('\n');
  const r = spawnSync(
    'fzf',
    ['--prompt=SOVERYN › ', '--height=40%', '--reverse', '--ansi'],
    { input, encoding: 'utf8' }
  );
  if (r.status !== 0 || !r.stdout.trim()) return null;
  const line = r.stdout.trim();
  return (
    rows.find((row) => row.label === line || row.labelPlain === line) ||
    rows.find((row) => line.includes(row.id)) ||
    null
  );
}

function pickWithMenu(rows) {
  return new Promise((resolve) => {
    console.error(`${colorBrand('SOVERYN')} model picker\n`);
    rows.forEach((r, i) => {
      const tag = r.enabled ? '' : ' [PARKED]';
      console.error(`  ${i + 1}) ${r.label}${tag}`);
    });
    console.error('\nEnter number (or q to cancel):');
    const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
    rl.question('> ', (answer) => {
      rl.close();
      const a = String(answer || '').trim().toLowerCase();
      if (!a || a === 'q' || a === 'quit') {
        resolve(null);
        return;
      }
      const n = parseInt(a, 10);
      if (!Number.isFinite(n) || n < 1 || n > rows.length) {
        console.error('Invalid selection.');
        resolve(null);
        return;
      }
      resolve(rows[n - 1]);
    });
  });
}

async function pickProfile(data) {
  const rows = await buildRows(data);
  if (fzfAvailable() && process.stdin.isTTY) {
    const chosen = pickWithFzf(rows);
    if (chosen) return chosen;
    // fall through if cancelled — still ok
    return null;
  }
  return pickWithMenu(rows);
}

module.exports = { pickProfile, buildRows };
