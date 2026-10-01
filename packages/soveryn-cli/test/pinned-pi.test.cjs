'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const SRC = path.join(__dirname, '..', 'src');
const PKG = path.join(__dirname, '..');

// Evaluate pinned-pi in a fresh process so SOVERYN_HARNESS is read at require time.
function probe(env) {
  const code = `
    const p = require(${JSON.stringify(path.join(SRC, 'pinned-pi.js'))});
    let pin = null, err = null, cmd = null;
    try { pin = p.pinnedPi(); cmd = p.piCommand(process.execPath, ['--version']); } catch (e) { err = e.message; }
    const stripped = p.stripPinEnv(process.env);
    process.stdout.write(JSON.stringify({ pin, err, cmd, label: p.piVersionLabel(),
      extensions: p.pinnedSettingsExtensions(), mismatch: p.pinVersionMismatch(pin),
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
  SOVERYN_PI_VERSION: '0.99.1',
};

/** Fake <prefix>/node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js at `version`. */
function fakePiInstall(version) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'pin-pkg-'));
  const pkgDir = path.join(root, 'pi-coding-agent');
  fs.mkdirSync(path.join(pkgDir, 'dist', 'bundle'), { recursive: true });
  fs.writeFileSync(
    path.join(pkgDir, 'package.json'),
    JSON.stringify({ name: '@earendil-works/pi-coding-agent', version })
  );
  const bin = path.join(pkgDir, 'dist', 'bundle', 'cli.js');
  fs.writeFileSync(bin, '');
  return { root, bin };
}

test('no pin env → legacy PATH pi, label 0.74.2, no extensions key', () => {
  const r = probe({});
  assert.equal(r.pin, null);
  assert.equal(r.label, '0.74.2');
  assert.equal(r.cmd.cmd, process.execPath);
  assert.equal(r.extensions, null);
});

test('soveryn-cli honors pin: explicit node + bin, label 0.99.1, stripped from child env', () => {
  const r = probe(PIN);
  assert.equal(r.pin.version, '0.99.1');
  assert.equal(r.label, '0.99.1');
  assert.deepEqual(r.cmd.args, [process.execPath, '--version']);
  assert.deepEqual(r.leaked, []);
});

test('Pi >=0.99 pin disables builtin:mcp (and only mcp)', () => {
  assert.deepEqual(probe(PIN).extensions, ['-builtin:mcp']);
  assert.deepEqual(probe({ ...PIN, SOVERYN_PI_VERSION: '0.100.0' }).extensions, ['-builtin:mcp']);
});

test('rollback pin 0.87.1 writes no extensions key (settings as before)', () => {
  const r = probe({ ...PIN, SOVERYN_PI_VERSION: '0.87.1' });
  assert.equal(r.label, '0.87.1');
  assert.equal(r.extensions, null);
});

test('Kernel ignores pin even when inherited', () => {
  const r = probe({ ...PIN, SOVERYN_HARNESS: 'kernel' });
  assert.equal(r.pin, null);
  assert.equal(r.label, '0.74.2');
  assert.deepEqual(r.cmd.args, ['--version']);
  assert.equal(r.extensions, null);
});

test('half-set or missing pin fails loudly (no silent fallback)', () => {
  assert.match(probe({ SOVERYN_PI_BIN: process.execPath }).err, /set both/);
  assert.match(
    probe({ ...PIN, SOVERYN_PI_BIN: '/nonexistent/pi/cli.js' }).err,
    /SOVERYN_PI_BIN missing/
  );
});

test('version falls back to the installed package; mismatch is reported', () => {
  const { root, bin } = fakePiInstall('0.99.1');
  try {
    const noVer = probe({ SOVERYN_PI_BIN: bin, SOVERYN_PI_NODE: process.execPath });
    assert.equal(noVer.label, '0.99.1');
    assert.equal(noVer.mismatch, null);
    const bad = probe({ SOVERYN_PI_BIN: bin, SOVERYN_PI_NODE: process.execPath, SOVERYN_PI_VERSION: '0.87.1' });
    assert.match(bad.mismatch, /SOVERYN_PI_VERSION=0\.87\.1 .* Pi 0\.99\.1/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('compareVersions orders numerically', () => {
  const { compareVersions } = require('../src/pinned-pi');
  assert.equal(compareVersions('0.99.1', '0.99.0'), 1);
  assert.equal(compareVersions('0.87.1', '0.99.0'), -1);
  assert.equal(compareVersions('0.100.0', '0.99.0'), 1);
  assert.equal(compareVersions('0.99.0', '0.99.0'), 0);
});

test('package.json + bin/soveryn-pi099 declare the same pin', () => {
  const pkg = JSON.parse(fs.readFileSync(path.join(PKG, 'package.json'), 'utf8'));
  const launcher = fs.readFileSync(path.join(PKG, 'bin', 'soveryn-pi099'), 'utf8');
  assert.equal(pkg.soverynPi.version, '0.99.1');
  assert.equal(pkg.bin.soveryn, './bin/soveryn-pi099');
  assert.match(launcher, /^PI_PIN_VERSION="0\.99\.1"$/m);
  assert.match(launcher, new RegExp(`^NODE_PIN_VERSION="${pkg.soverynPi.node}"$`, 'm'));
  // rollback launcher still present and still pinned to 0.87.1
  const rollback = fs.readFileSync(path.join(PKG, 'bin', 'soveryn-pi087'), 'utf8');
  assert.match(rollback, /^PI_PIN_VERSION="0\.87\.1"$/m);
});
