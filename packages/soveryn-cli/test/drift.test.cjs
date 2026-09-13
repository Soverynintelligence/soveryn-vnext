'use strict';
/** Drift checks — parked-but-live profiles and generated-config divergence. */
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const createRequire = require('node:module').createRequire;

const req = createRequire(__filename);
const { checkProfileStateDrift, generatedConfigDrift, stableStringify } = req(
  '../src/drift'
);

const DATA = () => ({
  defaultProfile: 'flash',
  profiles: {
    flash: { id: 'flash', enabled: true, baseUrl: 'http://x:1/v1', modelId: 'm-flash' },
    glm: { id: 'glm', enabled: false, baseUrl: 'http://x:2/v1', modelId: 'm-glm' },
  },
});

test('drift: parked profile whose serve is live is flagged', async () => {
  const probeFn = async (p) => ({ ok: p.modelId === 'm-glm', detail: '' });
  const drift = await checkProfileStateDrift(DATA(), probeFn);
  assert.strictEqual(drift.length, 1);
  assert.strictEqual(drift[0].profileId, 'glm');
  assert.match(drift[0].message, /PARKED but http:\/\/x:2\/v1 serves "m-glm"/);
});

test('drift: parked profile that is actually down → no drift', async () => {
  const probeFn = async () => ({ ok: false, detail: 'timeout' });
  const drift = await checkProfileStateDrift(DATA(), probeFn);
  assert.strictEqual(drift.length, 0);
});

test('drift: enabled profiles are never drift-checked', async () => {
  const probed = [];
  const probeFn = async (p) => {
    probed.push(p.id);
    return { ok: true, detail: '' };
  };
  const drift = await checkProfileStateDrift(DATA(), probeFn);
  assert.strictEqual(drift.length, 1); // glm only (parked + live)
  assert.deepStrictEqual(probed, ['glm']); // flash never probed
});

test('drift: probeFn throwing counts as down, not crash', async () => {
  const probeFn = async () => {
    throw new Error('boom');
  };
  const drift = await checkProfileStateDrift(DATA(), probeFn);
  assert.strictEqual(drift.length, 0);
});

test('config drift: matching generated files pass clean', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'svcfg-'));
  const built = {
    models: { providers: { soveryn: { baseUrl: 'http://x/v1' } } },
    settings: { defaultProvider: 'soveryn', compaction: { enabled: true } },
  };
  fs.writeFileSync(path.join(dir, 'models.json'), JSON.stringify(built.models, null, 2));
  fs.writeFileSync(path.join(dir, 'settings.json'), JSON.stringify(built.settings, null, 2));
  assert.deepStrictEqual(generatedConfigDrift(built, dir), []);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('config drift: hand-edited settings.json is flagged', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'svcfg-'));
  const built = {
    models: { providers: {} },
    settings: { defaultProvider: 'soveryn', enableInstallTelemetry: false },
  };
  fs.writeFileSync(path.join(dir, 'models.json'), JSON.stringify(built.models));
  // hand-edit: different value + reordered keys must still be detected
  fs.writeFileSync(
    path.join(dir, 'settings.json'),
    JSON.stringify({ enableInstallTelemetry: false, defaultProvider: 'other' })
  );
  const drift = generatedConfigDrift(built, dir);
  assert.strictEqual(drift.length, 1);
  assert.strictEqual(drift[0].file, 'settings.json');
  assert.match(drift[0].message, /diverged from profiles SSOT/);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('config drift: missing file is flagged', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'svcfg-'));
  const drift = generatedConfigDrift({ models: {}, settings: {} }, dir);
  assert.strictEqual(drift.length, 2);
  assert.match(drift[0].message, /unreadable/); // real error surfaces, not a fake "MISSING"
  fs.rmSync(dir, { recursive: true, force: true });
});

test('stableStringify is key-order independent', () => {
  assert.strictEqual(
    stableStringify({ a: 1, b: { c: 2, d: 3 } }),
    stableStringify({ b: { d: 3, c: 2 }, a: 1 })
  );
});
