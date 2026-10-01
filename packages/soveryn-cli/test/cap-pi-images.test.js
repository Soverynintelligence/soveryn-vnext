'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { capOpenAiImages } = require('../src/cap-pi-images');

test('keeps the newest four pictures', () => {
  const content = [{ type: 'text', text: 'look' }];
  for (let i = 0; i < 6; i++) {
    content.push({ type: 'image_url', image_url: { url: `pic-${i}` } });
  }
  const out = capOpenAiImages([{ role: 'user', content }]);
  const urls = out[0].content.filter((p) => p.type === 'image_url').map((p) => p.image_url.url);
  assert.deepEqual(urls, ['pic-2', 'pic-3', 'pic-4', 'pic-5']);
  assert.match(out[0].content[0].text, /2 earlier picture/);
});

test('patches bundled (Pi >=0.8x) openai-completions chunk once', () => {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const { ensurePiImageCap, MARKER } = require('../src/cap-pi-images');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'cap-bundle-'));
  const bundle = path.join(root, 'dist', 'bundle');
  fs.mkdirSync(path.join(bundle, 'chunks'), { recursive: true });
  fs.writeFileSync(path.join(bundle, 'cli.js'), '');
  const chunk = path.join(bundle, 'chunks', 'openai-completions-ABC123.js');
  fs.writeFileSync(
    chunk,
    'function convertMessages(){let params=[];for(const m of []){params.push(m)}return params}function convertTools(tools,compat){return tools}export{convertMessages};'
  );
  const first = ensurePiImageCap(path.join(bundle, 'cli.js'));
  assert.equal(first.ok, true);
  assert.equal(first.patched, true);
  const src = fs.readFileSync(chunk, 'utf8');
  assert.ok(src.includes(MARKER));
  assert.ok(src.includes('return capOpenAiImages(params)}'));
  const second = ensurePiImageCap(path.join(bundle, 'cli.js'));
  assert.equal(second.already, true);
  fs.rmSync(root, { recursive: true, force: true });
});

test('pinned Pi install (package.json soverynPi.prefix): one openai-completions chunk, needle once or already capped', (t) => {
  const fs = require('fs');
  const os = require('os');
  const path = require('path');
  const { bundledProviderPath, BUNDLE_NEEDLE, MARKER } = require('../src/cap-pi-images');
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
  const prefix = String(pkg.soverynPi.prefix).replace(/^~(?=\/)/, os.homedir());
  const bin = path.join(prefix, 'node_modules', '@earendil-works', 'pi-coding-agent', 'dist', 'bundle', 'cli.js');
  if (!fs.existsSync(bin)) {
    t.skip(`pinned Pi not installed at ${prefix}`);
    return;
  }
  const chunk = bundledProviderPath(bin);
  assert.ok(chunk, 'exactly one openai-completions-*.js chunk');
  const src = fs.readFileSync(chunk, 'utf8');
  if (src.includes(MARKER)) {
    assert.equal(src.split(MARKER).length, 2, 'marker injected once');
    assert.ok(src.includes('}return capOpenAiImages(params)}'));
  } else {
    assert.equal(src.split(BUNDLE_NEEDLE).length, 2, 'BUNDLE_NEEDLE matches exactly once');
  }
});
