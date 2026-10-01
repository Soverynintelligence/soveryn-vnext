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
