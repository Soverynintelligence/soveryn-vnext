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
