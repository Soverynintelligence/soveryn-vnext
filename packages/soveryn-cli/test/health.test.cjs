'use strict';
/** Health probe against real local HTTP servers + assertExact semantics. */
const { test } = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const createRequire = require('node:module').createRequire;

const req = createRequire(__filename);
const { probe, probeStable, findModel } = req('../src/health');
const { assertExact, codePoints } = req('../src/policy/assert');
const { canonicalizeId, resolveCanonicalKey } = req('../src/policy/canonical');

function serve(status, body) {
  const srv = http.createServer((_, res) => {
    res.writeHead(status, { 'content-type': 'application/json' });
    res.end(body);
  });
  return new Promise((resolve) => srv.listen(0, '127.0.0.1', () => resolve(srv)));
}

const portOf = (srv) => srv.address().port;

test('probe: 200 + model present', async () => {
  const srv = await serve(200, '{"data":[{"id":"m1"}]}');
  const p = { baseUrl: `http://127.0.0.1:${portOf(srv)}/v1`, modelId: 'm1' };
  const r = await probe(p, 1000, { requireModel: true });
  assert.strictEqual(r.ok, true);
  srv.close();
});

test('probe: 200 but model missing → fail with ids listed', async () => {
  const srv = await serve(200, '{"data":[{"id":"other"}]}');
  const p = { baseUrl: `http://127.0.0.1:${portOf(srv)}/v1`, modelId: 'm1' };
  const r = await probe(p, 1000, { requireModel: true });
  assert.strictEqual(r.ok, false);
  assert.match(r.detail, /model "m1" missing/);
  srv.close();
});

test('probe: model served as llama.cpp router alias → ok, reports matchedId', async () => {
  const srv = await serve(
    200,
    '{"data":[{"id":"cognition","aliases":["cognition"]},{"id":"qwen38","aliases":["Qwen3.8-27B","aetheria","qwen38"]}]}'
  );
  const p = { baseUrl: `http://127.0.0.1:${portOf(srv)}/v1`, modelId: 'aetheria' };
  const r = await probe(p, 1000, { requireModel: true });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(r.matchedId, 'qwen38');
  assert.match(r.detail, /alias of qwen38/);
  srv.close();
});

test('probe: 200 from a server that does not serve the name → fail (vLLM :8090 case)', async () => {
  const srv = await serve(
    200,
    '{"data":[{"id":"qwen38-nvfp4"},{"id":"eve"},{"id":"qwen38"},{"id":"bench-flash"}]}'
  );
  const p = { baseUrl: `http://127.0.0.1:${portOf(srv)}/v1`, modelId: 'aetheria' };
  const r = await probe(p, 1000, { requireModel: true });
  assert.strictEqual(r.ok, false);
  assert.match(r.detail, /model "aetheria" missing/);
  srv.close();
});

test('findModel: id beats alias; unknown → null', () => {
  const models = [
    { id: 'a', aliases: ['x'] },
    { id: 'x', aliases: [] },
  ];
  assert.strictEqual(findModel(models, 'x').id, 'x');
  assert.strictEqual(findModel(models, 'a').id, 'a');
  assert.strictEqual(findModel(models, 'nope'), null);
  assert.strictEqual(findModel([{ id: 'm' }], 'm').id, 'm'); // no aliases field
});

test('probe: 503 → fail', async () => {
  const srv = await serve(503, '');
  const p = { baseUrl: `http://127.0.0.1:${portOf(srv)}/v1`, modelId: 'm1' };
  const r = await probe(p, 1000);
  assert.strictEqual(r.ok, false);
  assert.match(r.detail, /HTTP 503/);
  srv.close();
});

test('probeStable: succeeds after first failure when retries available', async () => {
  let hits = 0;
  const srv = http.createServer((_, res) => {
    hits += 1;
    res.writeHead(hits === 1 ? 503 : 200, { 'content-type': 'application/json' });
    res.end('{"data":[{"id":"m1"}]}');
  });
  await new Promise((r) => srv.listen(0, '127.0.0.1', r));
  const p = { baseUrl: `http://127.0.0.1:${srv.address().port}/v1`, modelId: 'm1' };
  const r = await probeStable(p, 500, { retries: 1 });
  assert.strictEqual(r.ok, true);
  assert.strictEqual(hits, 2);
  srv.close();
});

test('assertExact: passes on equal, fails on single-char corruption', () => {
  assert.strictEqual(assertExact('setAttribute', 'setAttribute'), true);
  assert.throws(() => assertExact('setAttribute', 'setAttributeX'), /ASSERT_EXACT|failed/);
  assert.throws(() => assertExact('setAttribute', 'setattrIbute'), /U\+41 !== U\+61/); // case corruption is real
});

test('codePoints: surrogate pairs compare as one character', () => {
  assert.strictEqual(codePoints('\u{1F600}').length, 1);
});

test('canonical names: case corruption resolves, garbage does not', () => {
  const map = { setAttribute: { id: 'setAttribute' } };
  assert.strictEqual(resolveCanonicalKey(map, canonicalizeId('SETATTRIBUTE')), 'setAttribute');
  assert.strictEqual(resolveCanonicalKey(map, canonicalizeId('totally-unknown')), null);
});
