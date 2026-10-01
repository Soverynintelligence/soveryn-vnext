'use strict';
/** Sessions + profiles: pure logic paths. */
const { test } = require('node:test');
const assert = require('node:assert');
const createRequire = require('node:module').createRequire;

const req = createRequire(__filename);
const {
  matchSession,
  sessionIsStale,
  decideSignInResume,
  resumeModeFromEnv,
} = req('../src/sessions');
const { buildPiConfig } = req('../src/profiles');
const { stableStringify } = req('../src/drift');
const { loadProfiles, readActiveId, listProfileIds } = req('../src/profiles');

const SESSIONS = [
  {
    id: '01a0898b-1111-2222-3333-444455556666',
    file: '/tmp/s/01a0898b-1111-2222-3333-444455556666.jsonl',
    timestamp: '2026-09-13T10:00:00.000Z',
    size: 1024,
    cwd: '/tmp',
    harness: 'kernel',
  },
  {
    id: 'ffeeddcc-aaaabbbb-cccc-ddddeeeeffff',
    file: '/tmp/s/ffeeddcc-aaaabbbb-cccc-ddddeeeeffff.jsonl',
    timestamp: '2026-09-12T10:00:00.000Z',
    size: 1024,
    cwd: '/tmp',
    harness: 'soveryn-cli',
  },
];

test('matchSession: null/latest returns newest', () => {
  assert.strictEqual(matchSession(null, SESSIONS), SESSIONS[0]);
  assert.strictEqual(matchSession('latest', SESSIONS), SESSIONS[0]);
});

test('matchSession: full id and unique prefix', () => {
  assert.strictEqual(matchSession(SESSIONS[1].id, SESSIONS), SESSIONS[1]);
  assert.strictEqual(matchSession('ffeeddcc', SESSIONS), SESSIONS[1]);
});

test('matchSession: ambiguous prefix resolves to exact id first', () => {
  const dupes = [SESSIONS[0], { ...SESSIONS[0], file: '/tmp/s/other.jsonl' }];
  assert.strictEqual(matchSession(SESSIONS[0].id, dupes), SESSIONS[0]);
});

test('matchSession: unknown query returns null', () => {
  assert.strictEqual(matchSession('nope-not-here', SESSIONS), null);
});

test('sessionIsStale: fresh small session is not stale', () => {
  const s = { size: 1024, timestamp: new Date().toISOString() };
  assert.strictEqual(sessionIsStale(s), false);
});

test('sessionIsStale: oversized or old session is stale', () => {
  assert.strictEqual(sessionIsStale({ size: 9 * 1024 * 1024, timestamp: new Date().toISOString() }), true);
  assert.strictEqual(
    sessionIsStale({ size: 1024, timestamp: new Date(Date.now() - 5 * 60 * 60 * 1000).toISOString() }),
    true
  );
  assert.strictEqual(sessionIsStale(null), false);
});

test('resume decision matrix', () => {
  const D = decideSignInResume;
  assert.strictEqual(D({ fresh: true, isTty: true }), 'skip');
  assert.strictEqual(D({ printMode: true, isTty: true }), 'skip');
  assert.strictEqual(D({ hasSession: true, isTty: true }), 'skip');
  assert.strictEqual(D({ isTty: true, mode: 'never' }), 'skip');
  assert.strictEqual(D({ isTty: true, mode: 'always' }), 'auto');
  assert.strictEqual(D({ isTty: false, mode: 'ask' }), 'skip');
  assert.strictEqual(D({ isTty: true, mode: 'ask' }), 'ask');
});

test('resume env parsing', () => {
  assert.strictEqual(resumeModeFromEnv({ SOVERYN_RESUME: 'never' }), 'never');
  assert.strictEqual(resumeModeFromEnv({ SOVERYN_RESUME: '1' }), 'always');
  assert.strictEqual(resumeModeFromEnv({}), 'ask');
  assert.strictEqual(resumeModeFromEnv({ SOVERYN_RESUME: 'garbage' }), 'ask');
});

test('buildPiConfig is deterministic across calls (SSOT → same bytes)', () => {
  const data = loadProfiles();
  const active = data.profiles[readActiveId(data)];
  const a = buildPiConfig(data, active);
  const b = buildPiConfig(data, active);
  assert.strictEqual(stableStringify(a), stableStringify(b));
  // shape sanity
  assert.ok(a.models.providers, 'models.providers present');
  assert.strictEqual(a.settings.defaultProvider, active.piProviderId);
  assert.strictEqual(a.settings.defaultModel, active.modelId);
  assert.ok(a.settings.compaction, 'compaction block present');
});

test('profiles SSOT: every profile has required provider fields', () => {
  const data = loadProfiles();
  for (const id of listProfileIds(data)) {
    const p = data.profiles[id];
    assert.ok(p.baseUrl && p.modelId && p.piProviderId, `profile ${id} complete`);
    assert.match(p.baseUrl, /\/v1$/, `profile ${id} baseUrl ends /v1`);
  }
});
