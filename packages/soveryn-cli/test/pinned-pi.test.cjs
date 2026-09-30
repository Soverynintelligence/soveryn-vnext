'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { spawnSync } = require('child_process');

const SRC = path.join(__dirname, '..', 'src');

// Evaluate pinned-pi in a fresh process so SOVERYN_HARNESS is read at require time.
function probe(env) {
  const code = `
    const p = require(${JSON.stringify(path.join(SRC, 'pinned-pi.js'))});
    let pin = null, err = null, cmd = null;
    try { pin = p.pinnedPi(); cmd = p.piCommand(process.execPath, ['--version']); } catch (e) { err = e.message; }
    const stripped = p.stripPinEnv(process.env);
    process.stdout.write(JSON.stringify({ pin, err, cmd, label: p.piVersionLabel(),
      leaked: p.PIN_ENV_KEYS.filter((k) => k in stripped) }));
  `;
  const clean = { ...process.env };
  for (const k of ['SOVERYN_HARNESS', 'SOVERYN_PI_BIN', 'SOVERYN_PI_NODE', 'SOVERYN_PI_VERSION']) delete clean[k];
  const r = spawnSync(process.execPath, ['-e', code], { env: { ...clean, ...env }, encoding: 'utf8' });
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}

const PIN = {
  SOVERYN_PI_BIN: process.execPath, // any existing file
  SOVERYN_PI_NODE: process.execPath,
  SOVERYN_PI_VERSION: '0.87.1',
};

test('no pin env → legacy PATH pi, label 0.74.2', () => {
  const r = probe({});
  assert.equal(r.pin, null);
  assert.equal(r.label, '0.74.2');
  assert.equal(r.cmd.cmd, process.execPath);
});

test('soveryn-cli honors pin: explicit node + bin, label 0.87.1, stripped from child env', () => {
  const r = probe(PIN);
  assert.equal(r.pin.version, '0.87.1');
  assert.equal(r.label, '0.87.1');
  assert.deepEqual(r.cmd.args, [process.execPath, '--version']);
  assert.deepEqual(r.leaked, []);
});

test('Kernel ignores pin even when inherited', () => {
  const r = probe({ ...PIN, SOVERYN_HARNESS: 'kernel' });
  assert.equal(r.pin, null);
  assert.equal(r.label, '0.74.2');
  assert.deepEqual(r.cmd.args, ['--version']);
});

test('half-set or missing pin fails loudly (no silent fallback)', () => {
  assert.match(probe({ SOVERYN_PI_BIN: process.execPath }).err, /set both/);
  assert.match(
    probe({ ...PIN, SOVERYN_PI_BIN: '/nonexistent/pi/cli.js' }).err,
    /SOVERYN_PI_BIN missing/
  );
});
