'use strict';
// revamp phase 1: danger-gate extension loads under pinned Pi and is wired only for the Desk.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { pathToFileURL } = require('url');

const EXT = path.join(__dirname, '..', 'extensions', 'danger-gate.ts');
const PIN = require('../package.json').soverynPi.version;
const LOADER = path.join(os.homedir(), '.soveryn', 'pi', PIN, 'node_modules', '@earendil-works',
  'pi-coding-agent', 'dist', 'core', 'extensions', 'loader.js');

test('loads cleanly through pinned Pi extension loader (gate ON)', { skip: fs.existsSync(LOADER) ? false : 'pinned pi missing' }, async () => {
  process.env.SOVERYN_DESK_GATE = '1';
  try {
    const { loadExtensions } = await import(pathToFileURL(LOADER).href);
    const res = await loadExtensions([EXT], process.cwd());
    assert.deepStrictEqual(res.errors, [], JSON.stringify(res.errors));
    assert.strictEqual(res.extensions.length, 1);
  } finally {
    delete process.env.SOVERYN_DESK_GATE;
  }
});

test('presets add danger-gate only when SOVERYN_DESK_GATE=1', () => {
  const key = require.resolve('../src/presets');
  delete process.env.SOVERYN_DESK_GATE;
  delete require.cache[key];
  let presets = require('../src/presets');
  assert.ok(!presets.packPiArgs(presets.getPack('standard'), []).includes(EXT));
  process.env.SOVERYN_DESK_GATE = '1';
  try {
    const args = presets.packPiArgs(presets.getPack('standard'), []);
    assert.ok(args.includes(EXT), JSON.stringify(args));
  } finally {
    delete process.env.SOVERYN_DESK_GATE;
  }
});
