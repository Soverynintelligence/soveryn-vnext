'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { providerEntry, overlayContextWindow, loadPinnedRuntimeOverlay } = require('../src/profiles');

const glm = { id: 'glm', piProviderId: 'soveryn-glm', modelId: 'glm-5.3-flash', contextWindow: 32768, maxTokens: 16384 };

test('no overlay (Kernel / soveryn-074): profile contextWindow is used unchanged', () => {
  assert.equal(providerEntry(glm, null).models[0].contextWindow, 32768);
  assert.equal(loadPinnedRuntimeOverlay('/nonexistent', false), null);
});

test('pinned overlay advertises the server context window so Pi does not clamp max_tokens', () => {
  const overlay = { serverContextWindow: { glm: 1000000 } };
  assert.equal(providerEntry(glm, overlay).models[0].contextWindow, 1000000);
  assert.equal(providerEntry({ ...glm, id: 'aetheria' }, overlay).models[0].contextWindow, 32768);
});

test('invalid overlay values are ignored', () => {
  for (const bad of [0, -1, 'big', 1.5, null]) {
    assert.equal(overlayContextWindow({ serverContextWindow: { glm: bad } }, glm), null);
  }
});

test('overlay only loads for the pinned runtime', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'overlay-'));
  fs.writeFileSync(path.join(dir, 'pinned-runtime.json'), JSON.stringify({ serverContextWindow: { glm: 1000000 } }));
  assert.equal(loadPinnedRuntimeOverlay(dir, false), null);
  assert.equal(loadPinnedRuntimeOverlay(dir, true).serverContextWindow.glm, 1000000);
  fs.rmSync(dir, { recursive: true, force: true });
});

test('generated settings: extensions -builtin:mcp only on Pi >=0.99, tuiMode regular only on Pi >=1.0', () => {
  const { buildPiConfig, loadProfiles, readActiveId } = require('../src/profiles');
  const KEYS = ['SOVERYN_PI_BIN', 'SOVERYN_PI_NODE', 'SOVERYN_PI_VERSION'];
  const saved = Object.fromEntries(KEYS.map((k) => [k, process.env[k]]));
  const setPin = (version) => {
    for (const k of KEYS) delete process.env[k];
    if (version) {
      process.env.SOVERYN_PI_BIN = process.execPath;
      process.env.SOVERYN_PI_NODE = process.execPath;
      process.env.SOVERYN_PI_VERSION = version;
    }
  };
  try {
    const data = loadProfiles();
    const active = data.profiles[readActiveId(data)];
    setPin('1.0.3');
    const cur = buildPiConfig(data, active, { overlay: null }).settings;
    assert.deepEqual(cur.extensions, ['-builtin:mcp']);
    assert.equal(cur.tuiMode, 'regular');
    assert.equal(cur.lastChangelogVersion, '1.0.3');
    assert.equal(cur.defaultProjectTrust, 'always');
    setPin('1.0.0');
    const p100 = buildPiConfig(data, active, { overlay: null }).settings;
    assert.deepEqual(p100.extensions, ['-builtin:mcp']);
    assert.equal(p100.tuiMode, 'regular');
    assert.equal(p100.lastChangelogVersion, '1.0.0');
    // 1.0.3 settings = 1.0.0 settings except lastChangelogVersion (no other drift)
    const { lastChangelogVersion: _curVer, ...curRest } = cur;
    const { lastChangelogVersion: _p100Ver, ...p100Rest } = p100;
    assert.deepEqual(curRest, p100Rest);
    setPin('0.99.1');
    const p099 = buildPiConfig(data, active, { overlay: null }).settings;
    assert.deepEqual(p099.extensions, ['-builtin:mcp']);
    assert.equal('tuiMode' in p099, false);
    assert.equal(p099.lastChangelogVersion, '0.99.1');
    // 1.0.x settings = 0.99.1 settings + tuiMode only (no other drift)
    const { tuiMode, ...curNoTui } = curRest;
    const { lastChangelogVersion: _l, ...p099Rest } = p099;
    assert.deepEqual(curNoTui, p099Rest);
    setPin('0.87.1');
    const prev = buildPiConfig(data, active, { overlay: null }).settings;
    assert.equal('extensions' in prev, false);
    assert.equal('tuiMode' in prev, false);
    assert.equal(prev.lastChangelogVersion, '0.87.1');
    setPin(null);
    const legacy = buildPiConfig(data, active, { overlay: null }).settings;
    assert.equal('extensions' in legacy, false);
    assert.equal('tuiMode' in legacy, false);
    assert.equal(legacy.lastChangelogVersion, '0.74.2');
  } finally {
    for (const k of KEYS) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});
