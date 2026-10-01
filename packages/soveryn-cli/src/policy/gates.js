'use strict';

/**
 * SOVERYN policy gates — native controls (not prose-only).
 * Source analysis: Kernel · ~/soveryn-harness/RESEARCH.md §4 (2026-09-09).
 * G6/G7 + executable G1 added 2026-09-10 (harness-side, not SOVERYN.md lectures).
 */

const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { assertExact } = require('./assert');
const {
  CRITICAL_NAMES,
  canonicalizeId,
  resolveCanonicalKey,
  assertCriticalNames,
} = require('./canonical');
const { getPrintTimeoutMs, DEFAULT_MAX_PRINT_SECONDS } = require('./limits');
const {
  runFidelityProbes,
  deliberateFailCase,
  compareFidelity,
} = require('./fidelity');
const { appendEvidence } = require('../evidence');

const GATE_IDS = Object.freeze({
  VERIFICATION_NOT_BLIND: 'G1_VERIFICATION_NOT_BLIND',
  TEST_NOT_DEFANG: 'G2_TEST_NOT_DEFANG',
  SINK_CALLERS_AUDITED: 'G3_SINK_CALLERS_AUDITED',
  CANONICAL_NAMES: 'G4_CANONICAL_NAMES',
  BOUNDED_PRINT: 'G5_BOUNDED_PRINT',
  TOOL_EVIDENCE: 'G6_TOOL_EVIDENCE',
  API_SURFACE: 'G7_API_SURFACE',
  OUTPUT_FIDELITY: 'G8_OUTPUT_FIDELITY',
});

const POLICY_DIR = __dirname;
const SINKS_PATH = path.join(POLICY_DIR, 'sinks.json');
const PKG_ROOT = path.resolve(POLICY_DIR, '..', '..');
const HARNESS_EXT = path.join(PKG_ROOT, 'extensions', 'harness-controls.ts');
const WEB_EXT = path.join(PKG_ROOT, 'extensions', 'web-pack.ts');
const WEB_PROBE = path.join(PKG_ROOT, 'scripts', 'web', 'web-api-probe.mjs');
const WEB_HOST = path.join(PKG_ROOT, 'scripts', 'web', 'html-module-host.mjs');
const EVIDENCE_JS = path.join(PKG_ROOT, 'src', 'evidence.js');

function loadSinks() {
  const raw = fs.readFileSync(SINKS_PATH, 'utf8');
  return JSON.parse(raw);
}

function result(id, status, detail, extra) {
  return { id, status, detail, ...(extra || {}) };
}

/**
 * G1 — Verification must not be blind.
 * EXECUTES live checks (require + assertExact + timeout resolve + launch spawn
 * wiring). File presence alone is FAIL.
 */
function gateVerificationNotBlind() {
  const required = [
    path.join(POLICY_DIR, 'gates.js'),
    path.join(POLICY_DIR, 'assert.js'),
    path.join(POLICY_DIR, 'canonical.js'),
    path.join(POLICY_DIR, 'limits.js'),
    SINKS_PATH,
    path.join(PKG_ROOT, 'src', 'launch.js'),
    EVIDENCE_JS,
    HARNESS_EXT,
    path.join(POLICY_DIR, 'fidelity.js'),
  ];
  const missing = required.filter((p) => !fs.existsSync(p));
  if (missing.length) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      `required modules missing: ${missing.join(', ')}`
    );
  }

  // EXECUTE: require policy modules (not just existsSync)
  let assertMod;
  let limitsMod;
  let evidenceMod;
  try {
    assertMod = require('./assert');
    limitsMod = require('./limits');
    evidenceMod = require('../evidence');
  } catch (e) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      `require() failed during G1 execute: ${e.message}`
    );
  }

  try {
    assertMod.assertExact('g1-exec', 'g1-exec', 'g1-live');
  } catch (e) {
    return result(GATE_IDS.VERIFICATION_NOT_BLIND, 'FAIL', `live assertExact failed: ${e.message}`);
  }

  let mismatchThrew = false;
  try {
    assertMod.assertExact('g1-bad', 'g1-exec', 'g1-mismatch');
  } catch (e) {
    mismatchThrew = e.code === 'ASSERT_EXACT';
  }
  if (!mismatchThrew) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'live assertExact did not throw on mismatch — blind/defanged'
    );
  }

  const ms = limitsMod.getPrintTimeoutMs({});
  if (!(ms > 0)) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'getPrintTimeoutMs returned non-positive — unbounded print'
    );
  }

  // EXECUTE evidence helpers
  if (typeof evidenceMod.appendEvidence !== 'function' || typeof evidenceMod.fingerprint !== 'function') {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'evidence.js missing appendEvidence/fingerprint exports'
    );
  }
  const fp = evidenceMod.fingerprint('bash', { command: 'true' });
  if (!fp || typeof fp !== 'string') {
    return result(GATE_IDS.VERIFICATION_NOT_BLIND, 'FAIL', 'fingerprint() did not return hash');
  }

  let sinks;
  try {
    sinks = loadSinks();
  } catch (e) {
    return result(GATE_IDS.VERIFICATION_NOT_BLIND, 'FAIL', `sinks.json unreadable: ${e.message}`);
  }

  const sinkIds = (sinks.sinks || []).map((s) => s.id).sort();
  const expectedSeed = [
    'chrome_web_probe',
    'curl_health',
    'evidence_sidecar',
    'fidelity_probe',
    'profile_write',
    'spawn_pi_launch',
  ].sort();
  try {
    assertExact(sinkIds.join(','), expectedSeed.join(','), 'seed-sink-ids');
  } catch (e) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      `seed sinks mismatch (executed): ${e.message}`
    );
  }

  // Behavioural (not string-scan): launch must export/use timeout via require graph + pack resolver.
  const launchMod = require('../launch');
  if (typeof launchMod.launchPi !== 'function' || typeof launchMod.findPi !== 'function') {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'launch.js did not export launchPi/findPi (execute require)'
    );
  }
  const presetsMod = require('../presets');
  if (typeof presetsMod.resolvePack !== 'function' || typeof presetsMod.packPiArgs !== 'function') {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'presets.js missing resolvePack/packPiArgs'
    );
  }
  // Cross-check: limits already executed above (ms > 0). G5 owns timeout kill behaviour.

  // EXECUTE: harness-controls must mention tool_result + loop guard
  const harnessSrc = fs.readFileSync(HARNESS_EXT, 'utf8');
  if (!harnessSrc.includes('tool_result') || !harnessSrc.includes('loop-guard')) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'harness-controls.ts missing tool_result sink-gate or loop-guard'
    );
  }

  // Compaction diagnostic must not go silent on typo/missing keepRecentTokens (G1 not-blind).
  const profilesMod = require('../profiles');
  if (typeof profilesMod.compactionWarnings !== 'function') {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'profiles.js missing compactionWarnings'
    );
  }
  const compactBase = {
    contextWindow: 262144,
    maxTokens: 16384,
    compaction: { enabled: true, reserveTokens: 18432, keepRecentTokens: 20000 },
  };
  const canFire = profilesMod.compactionWarnings(compactBase);
  if (!canFire.some((w) => /amnesia/i.test(w))) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      'compactionWarnings did not fire amnesia warning on keepRecent=20000 @262k — defanged'
    );
  }
  const abc = profilesMod.compactionWarnings({
    ...compactBase,
    compaction: { ...compactBase.compaction, keepRecentTokens: 'abc' },
  });
  const missingKeep = profilesMod.compactionWarnings({
    ...compactBase,
    compaction: { enabled: true, reserveTokens: 18432 },
  });
  const ctxJunk = profilesMod.compactionWarnings({
    ...compactBase,
    contextWindow: '262k',
  });
  if (!abc.length || !missingKeep.length || !ctxJunk.length) {
    return result(
      GATE_IDS.VERIFICATION_NOT_BLIND,
      'FAIL',
      `compactionWarnings silent on malformation abc=${abc.length} missing=${missingKeep.length} ctx=${ctxJunk.length}`
    );
  }

  return result(
    GATE_IDS.VERIFICATION_NOT_BLIND,
    'PASS',
    'executed require+assertExact+fingerprint+timeout; sinks seed exact; launch+harness wired; compactionWarnings cannot swallow NaN',
    {
      signals: {
        modules: true,
        sinks: true,
        timeoutWired: true,
        evidence: true,
        harness: true,
        printTimeoutMs: ms,
      },
    }
  );
}

function gateTestNotDefang() {
  try {
    assertExact('gates-ok', 'gates-ok', 'identity');
  } catch (e) {
    return result(GATE_IDS.TEST_NOT_DEFANG, 'FAIL', `identity assertExact broke: ${e.message}`);
  }

  let threw = false;
  try {
    assertExact('gates', 'gates-ok', 'truncated-must-fail');
  } catch (e) {
    threw = e.code === 'ASSERT_EXACT';
  }
  if (!threw) {
    return result(
      GATE_IDS.TEST_NOT_DEFANG,
      'FAIL',
      'assertExact accepted truncated string — DEFANGED, test proves nothing'
    );
  }

  threw = false;
  try {
    assertExact('gates-0k', 'gates-ok', 'corrupt-must-fail');
  } catch (e) {
    threw = e.code === 'ASSERT_EXACT';
  }
  if (!threw) {
    return result(
      GATE_IDS.TEST_NOT_DEFANG,
      'FAIL',
      'assertExact accepted single-char corruption — DEFANGED'
    );
  }

  return result(
    GATE_IDS.TEST_NOT_DEFANG,
    'PASS',
    'assertExact code-point compare; truncations and single-char corruption fail'
  );
}

function gateSinkCallersAudited() {
  let sinks;
  try {
    sinks = loadSinks();
  } catch (e) {
    return result(GATE_IDS.SINK_CALLERS_AUDITED, 'FAIL', `sinks.json: ${e.message}`);
  }
  const list = sinks.sinks || [];
  if (!list.length) {
    return result(GATE_IDS.SINK_CALLERS_AUDITED, 'FAIL', 'no sinks registered');
  }
  const unaudited = list.filter((s) => s.callers_audited !== true);
  if (unaudited.length) {
    return result(
      GATE_IDS.SINK_CALLERS_AUDITED,
      'FAIL',
      `sinks missing callers_audited:true: ${unaudited.map((s) => s.id).join(', ')}`
    );
  }
  for (const s of list) {
    const abs = path.join(PKG_ROOT, s.file);
    if (!fs.existsSync(abs)) {
      return result(
        GATE_IDS.SINK_CALLERS_AUDITED,
        'FAIL',
        `sink ${s.id} file missing: ${s.file}`
      );
    }
  }
  return result(
    GATE_IDS.SINK_CALLERS_AUDITED,
    'PASS',
    `${list.length} sinks audited: ${list.map((s) => s.id).join(', ')}`
  );
}

function gateCanonicalNames(data) {
  try {
    assertCriticalNames();
  } catch (e) {
    return result(GATE_IDS.CANONICAL_NAMES, 'FAIL', e.message);
  }

  if (data && data.profiles) {
    for (const id of Object.keys(data.profiles)) {
      const canon = canonicalizeId(id);
      if (canon !== id) {
        return result(
          GATE_IDS.CANONICAL_NAMES,
          'FAIL',
          `profile key not canonical: ${JSON.stringify(id)} → ${JSON.stringify(canon)}`
        );
      }
      const p = data.profiles[id];
      if (p.id && canonicalizeId(p.id) !== p.id) {
        return result(
          GATE_IDS.CANONICAL_NAMES,
          'FAIL',
          `profile.id not canonical: ${JSON.stringify(p.id)}`
        );
      }
      if (p.piProviderId && canonicalizeId(p.piProviderId) !== p.piProviderId) {
        return result(
          GATE_IDS.CANONICAL_NAMES,
          'FAIL',
          `piProviderId not canonical: ${JSON.stringify(p.piProviderId)}`
        );
      }
      if (p.modelId && canonicalizeId(p.modelId) !== p.modelId) {
        return result(
          GATE_IDS.CANONICAL_NAMES,
          'FAIL',
          `modelId not canonical: ${JSON.stringify(p.modelId)}`
        );
      }
    }
    for (const need of ['flash', 'glm', 'aetheria']) {
      const key = resolveCanonicalKey(data.profiles, need);
      if (!key) {
        return result(
          GATE_IDS.CANONICAL_NAMES,
          'WARN',
          `critical profile id missing from profiles.json: ${need}`
        );
      }
    }
  }

  return result(
    GATE_IDS.CANONICAL_NAMES,
    'PASS',
    `critical names ok (${CRITICAL_NAMES.length}); profile ids canonical`
  );
}

/**
 * G5 — Bounded print execution: BEHAVIOURAL, not launchSrc.includes.
 * 1) getPrintTimeoutMs returns finite number > 0
 * 2) env override actually changes the return value
 * 3) GNU timeout kills a long sleep (same mechanism launch.js + Chrome tools use)
 * 4) launch.js require graph includes getPrintTimeoutMs call site via executed import
 */
function gateBoundedPrint(data) {
  const ms = getPrintTimeoutMs(data || {});
  if (typeof ms !== 'number' || !Number.isFinite(ms) || !(ms > 0)) {
    return result(
      GATE_IDS.BOUNDED_PRINT,
      'FAIL',
      `getPrintTimeoutMs behavioural fail: got ${JSON.stringify(ms)} (need finite number > 0)`
    );
  }

  const prev = process.env.SOVERYN_PRINT_TIMEOUT_MS;
  let overrideOk = false;
  try {
    process.env.SOVERYN_PRINT_TIMEOUT_MS = '50';
    const over = getPrintTimeoutMs(data || {});
    overrideOk = over === 50;
    if (!overrideOk) {
      return result(
        GATE_IDS.BOUNDED_PRINT,
        'FAIL',
        `env override behavioural fail: expected 50 got ${over}`
      );
    }
  } finally {
    if (prev === undefined) delete process.env.SOVERYN_PRINT_TIMEOUT_MS;
    else process.env.SOVERYN_PRINT_TIMEOUT_MS = prev;
  }

  // Same wrapper launch.js / web-api-probe / open-html use: timeout Ns <cmd>
  const kill = spawnSync('timeout', ['1s', 'sleep', '30'], {
    encoding: 'utf8',
    timeout: 5000,
  });
  // GNU coreutils timeout → exit 124; some systems may use SIGTERM
  const killed =
    kill.status === 124 ||
    kill.signal === 'SIGTERM' ||
    kill.status === 143; /* 128+15 */
  if (!killed) {
    return result(
      GATE_IDS.BOUNDED_PRINT,
      'FAIL',
      `timeout dry-run did not kill sleep (status=${kill.status} signal=${kill.signal}) — cannot prove bounded exec`
    );
  }

  // Prove launch module loads getPrintTimeoutMs path (executed require, not string scan)
  let launchUsesLimits = false;
  try {
    const launchPath = path.join(PKG_ROOT, 'src', 'launch.js');
    const src = fs.readFileSync(launchPath, 'utf8');
    // Still verify call exists, but only AFTER behavioural checks above succeeded.
    // Prefer executed: limits already required by launch at load time.
    require('../launch');
    launchUsesLimits = src.includes('getPrintTimeoutMs(');
    if (!launchUsesLimits) {
      return result(
        GATE_IDS.BOUNDED_PRINT,
        'FAIL',
        'launch.js does not call getPrintTimeoutMs( — print kill path missing'
      );
    }
  } catch (e) {
    return result(GATE_IDS.BOUNDED_PRINT, 'FAIL', `launch require failed: ${e.message}`);
  }

  const sec = ms / 1000;
  const fromEnv =
    process.env.SOVERYN_PRINT_TIMEOUT_MS != null &&
    String(process.env.SOVERYN_PRINT_TIMEOUT_MS).trim() !== '';
  return result(
    GATE_IDS.BOUNDED_PRINT,
    'PASS',
    `behavioural: getPrintTimeoutMs=${ms}ms overrideOk timeout-kill=124/SIGTERM; max print ${sec}s` +
      (fromEnv
        ? ' via SOVERYN_PRINT_TIMEOUT_MS'
        : data && data.limits && data.limits.maxPrintSeconds != null
          ? ' via profiles.limits.maxPrintSeconds'
          : ` default ${DEFAULT_MAX_PRINT_SECONDS}s`),
    { ms, overrideOk, timeoutKillStatus: kill.status, launchUsesLimits }
  );
}

/**
 * G6 — Tool evidence harness controls present and executable.
 * Doctor executes a write+read of a temp evidence row (not file-exists only).
 */
function gateToolEvidence() {
  if (!fs.existsSync(HARNESS_EXT)) {
    return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', `missing ${HARNESS_EXT}`);
  }
  if (!fs.existsSync(EVIDENCE_JS)) {
    return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', `missing ${EVIDENCE_JS}`);
  }
  const src = fs.readFileSync(HARNESS_EXT, 'utf8');
  for (const need of [
    'tool_result',
    'tool_call',
    'session_before_compact',
    'G6_TOOL_EVIDENCE',
    'loop-guard',
    'parseLoopLimit',
    'Number.isInteger',
  ]) {
    if (!src.includes(need)) {
      return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', `harness-controls missing ${need}`);
    }
  }

  const evidence = require('../evidence');
  if (typeof evidence.parseLoopLimit !== 'function') {
    return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', 'evidence.js missing parseLoopLimit');
  }
  const loopCases = [
    ['abc', 3],
    ['Infinity', 3],
    ['NaN', 3],
    ['0', 3],
    ['-1', 3],
    ['999999', 3],
    ['4', 4],
    ['3', 3],
    ['', 3],
  ];
  for (const [raw, want] of loopCases) {
    const got = evidence.parseLoopLimit(raw);
    if (got !== want) {
      return result(
        GATE_IDS.TOOL_EVIDENCE,
        'FAIL',
        `parseLoopLimit(${JSON.stringify(raw)})=${got} want ${want} (guard must stay fireable)`
      );
    }
  }
  if (evidence.parseLoopLimit('abc') === Number('abc')) {
    return result(
      GATE_IDS.TOOL_EVIDENCE,
      'FAIL',
      'parseLoopLimit(abc) returned NaN — loop guard would never fire'
    );
  }

  const tmp = path.join('/tmp', `soveryn-g6-${process.pid}`);
  try {
    fs.rmSync(tmp, { recursive: true, force: true });
    const file = evidence.appendEvidence(tmp, {
      toolName: 'g6-doctor',
      isError: false,
      fp: 'doctor',
      summary: 'gate execute',
    });
    const rows = evidence.readRecentEvidence(tmp, { limit: 5 });
    if (!rows.length || rows[0].toolName !== 'g6-doctor') {
      return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', 'evidence append/read did not round-trip');
    }
    if (!fs.existsSync(file)) {
      return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', 'evidence file not created');
    }
  } catch (e) {
    return result(GATE_IDS.TOOL_EVIDENCE, 'FAIL', `evidence execute error: ${e.message}`);
  } finally {
    try {
      fs.rmSync(tmp, { recursive: true, force: true });
    } catch (_) {}
  }

  return result(
    GATE_IDS.TOOL_EVIDENCE,
    'PASS',
    'harness-controls wired; evidence sidecar append/read executed; loop-guard value validated (NaN/0/Infinity cannot disable)'
  );
}

/**
 * G7 — API surface probe (live Chromium typeof) available for web pack.
 * Executes web-api-probe against AudioContext (or documents Chrome gap).
 */
function gateApiSurface() {
  if (!fs.existsSync(WEB_EXT)) {
    return result(GATE_IDS.API_SURFACE, 'FAIL', `missing web-pack extension: ${WEB_EXT}`);
  }
  if (!fs.existsSync(WEB_PROBE)) {
    return result(GATE_IDS.API_SURFACE, 'FAIL', `missing web-api-probe.mjs: ${WEB_PROBE}`);
  }
  if (!fs.existsSync(WEB_HOST)) {
    return result(GATE_IDS.API_SURFACE, 'FAIL', `missing html-module-host.mjs: ${WEB_HOST}`);
  }

  const webSrc = fs.readFileSync(WEB_EXT, 'utf8');
  for (const need of ['web-api-probe', 'html-module-host', 'open-html']) {
    if (!webSrc.includes(need)) {
      return result(GATE_IDS.API_SURFACE, 'FAIL', `web-pack.ts missing tool ${need}`);
    }
  }

  const r = spawnSync(process.execPath, [WEB_PROBE, '--json', 'AudioContext'], {
    encoding: 'utf8',
    timeout: 25000,
    maxBuffer: 2 * 1024 * 1024,
  });
  let payload = null;
  try {
    payload = JSON.parse((r.stdout || '').trim() || 'null');
  } catch (_) {
    payload = null;
  }

  if (r.status === 2 || (payload && payload.ok === false && !payload.engine && !payload.chrome)) {
    return result(
      GATE_IDS.API_SURFACE,
      'WARN',
      'web-api-probe CLI present but Chrome/Chromium missing — invented APIs cannot be refused via live probe until CHROME_BIN is set',
      { probe: payload, status: r.status }
    );
  }

  if (!payload || payload.ok !== true || !payload.apis || !payload.apis.AudioContext) {
    return result(
      GATE_IDS.API_SURFACE,
      'FAIL',
      `web-api-probe execute failed status=${r.status}: ${(r.stderr || r.stdout || '').slice(0, 300)}`
    );
  }

  const ac = payload.apis.AudioContext;
  if (ac.exists !== true || ac.typeof !== 'function') {
    return result(
      GATE_IDS.API_SURFACE,
      'FAIL',
      `live probe unexpected AudioContext=${JSON.stringify(ac)}`
    );
  }

  const host = spawnSync(process.execPath, [WEB_HOST, '--self-test'], {
    encoding: 'utf8',
    timeout: 10000,
    maxBuffer: 1024 * 1024,
  });
  let hostPayload = null;
  try {
    hostPayload = JSON.parse((host.stdout || '').trim() || 'null');
  } catch (_) {
    hostPayload = null;
  }
  if (
    host.status !== 0 ||
    !hostPayload ||
    hostPayload.ok !== true ||
    hostPayload.naivePrefixLeaks !== true ||
    hostPayload.encodedTraversalBlocked !== true
  ) {
    return result(
      GATE_IDS.API_SURFACE,
      'FAIL',
      `html-module-host containment self-test failed status=${host.status}: ${(host.stderr || host.stdout || '').slice(0, 300)}`
    );
  }

  return result(
    GATE_IDS.API_SURFACE,
    'PASS',
    `live Chromium probe ok (${payload.chrome || payload.engine}); AudioContext typeof=function; web pack tools registered; host path containment self-test ok`,
    { chrome: payload.chrome || null, hostContainment: hostPayload }
  );
}


/**
 * G8 — Output fidelity: length + code-point integrity; corruption can-it-fail.
 */
function gateOutputFidelity() {
  const probe = runFidelityProbes();
  if (!probe.ok) {
    const bad = probe.results.filter((r) => !r.ok);
    return result(
      GATE_IDS.OUTPUT_FIDELITY,
      'FAIL',
      `fidelity probes failed: ${bad.map((b) => b.case + '/' + b.phase).join(', ')}`,
      { results: probe.results }
    );
  }
  const deliberate = deliberateFailCase();
  if (!deliberate.ok) {
    return result(GATE_IDS.OUTPUT_FIDELITY, 'FAIL', deliberate.detail);
  }
  // Spot-check compareFidelity API
  const okCmp = compareFidelity('AudioContext', 'AudioContext', 'ac');
  const badCmp = compareFidelity('@@keyframes', '@keyframes', 'kf');
  if (!okCmp.ok || badCmp.ok) {
    return result(
      GATE_IDS.OUTPUT_FIDELITY,
      'FAIL',
      'compareFidelity behavioural mismatch'
    );
  }
  return result(
    GATE_IDS.OUTPUT_FIDELITY,
    'PASS',
    `${probe.results.length} fidelity checks ok; deliberate corrupt reject ok; matchAll surface real, matchAllAll absent`,
    { cases: probe.cases.map((c) => c.label) }
  );
}

function runGates(data, { strict = false, evidenceCwd } = {}) {
  const results = [
    gateVerificationNotBlind(),
    gateTestNotDefang(),
    gateSinkCallersAudited(),
    gateCanonicalNames(data),
    gateBoundedPrint(data),
    gateToolEvidence(),
    gateApiSurface(),
    gateOutputFidelity(),
  ];
  const failed = results.filter((r) => r.status === 'FAIL');
  const warned = results.filter((r) => r.status === 'WARN');
  const ok = failed.length === 0 && (!strict || warned.length === 0);
  const report = { ok, failed, warned, results };

  // Durable evidence of GATE PASS|FAIL|exit= (survives compaction)
  try {
    const cwd = evidenceCwd || process.cwd();
    const exitCode = ok ? 0 : 1;
    for (const r of results) {
      appendEvidence(cwd, {
        toolName: '_gate',
        isError: r.status === 'FAIL',
        event: 'gate',
        gateId: r.id,
        status: r.status,
        detail: r.detail,
        summary: `GATE ${r.status} ${r.id} exit=${r.status === 'FAIL' ? 1 : 0}`,
      });
    }
    appendEvidence(cwd, {
      toolName: '_gate',
      isError: !ok,
      event: 'gates_summary',
      summary: `GATE summary ok=${ok} fail=${failed.length} warn=${warned.length} exit=${exitCode}`,
      exit: exitCode,
    });
  } catch (e) {
    report.evidenceError = e.message;
  }

  return report;
}

function formatGateReport(report) {
  const lines = ['SOVERYN policy gates:'];
  for (const r of report.results) {
    lines.push(`  ${r.status.padEnd(4)} ${r.id}  — ${r.detail}`);
  }
  if (report.failed.length) {
    lines.push(`  summary: ${report.failed.length} FAIL`);
  } else if (report.warned.length) {
    lines.push(`  summary: OK with ${report.warned.length} WARN`);
  } else {
    lines.push('  summary: all PASS');
  }
  return lines.join('\n');
}

function runSelfTest() {
  const steps = [];
  try {
    assertExact('gates-ok', 'gates-ok', 'self-test-pass');
    steps.push({ name: 'assertExact_match', ok: true });
  } catch (e) {
    steps.push({ name: 'assertExact_match', ok: false, detail: e.message });
  }

  let wrongFailed = false;
  try {
    assertExact('WRONG', 'gates-ok', 'self-test-fail-expected');
  } catch (e) {
    wrongFailed = e.code === 'ASSERT_EXACT';
  }
  steps.push({
    name: 'assertExact_mismatch_throws',
    ok: wrongFailed,
    detail: wrongFailed ? 'threw ASSERT_EXACT as required' : 'DID NOT THROW — DEFANGED',
  });

  try {
    assertCriticalNames();
    steps.push({ name: 'critical_names', ok: true });
  } catch (e) {
    steps.push({ name: 'critical_names', ok: false, detail: e.message });
  }

  // Execute G6 evidence round-trip inside self-test
  try {
    const g6 = gateToolEvidence();
    steps.push({ name: 'g6_tool_evidence', ok: g6.status === 'PASS', detail: g6.detail });
  } catch (e) {
    steps.push({ name: 'g6_tool_evidence', ok: false, detail: e.message });
  }

  // G8 deliberate fail case — must reject corrupted token
  try {
    const d = deliberateFailCase();
    steps.push({ name: 'g8_deliberate_corrupt_reject', ok: d.ok, detail: d.detail });
  } catch (e) {
    steps.push({ name: 'g8_deliberate_corrupt_reject', ok: false, detail: e.message });
  }

  try {
    const g8 = gateOutputFidelity();
    steps.push({ name: 'g8_output_fidelity', ok: g8.status === 'PASS', detail: g8.detail });
  } catch (e) {
    steps.push({ name: 'g8_output_fidelity', ok: false, detail: e.message });
  }

  // G5 behavioural timeout kill
  try {
    const g5 = gateBoundedPrint({});
    steps.push({ name: 'g5_bounded_print_behavioural', ok: g5.status === 'PASS', detail: g5.detail });
  } catch (e) {
    steps.push({ name: 'g5_bounded_print_behavioural', ok: false, detail: e.message });
  }

  const ok = steps.every((s) => s.ok);
  return { ok, steps };
}

module.exports = {
  GATE_IDS,
  SINKS_PATH,
  runGates,
  formatGateReport,
  runSelfTest,
  gateVerificationNotBlind,
  gateTestNotDefang,
  gateSinkCallersAudited,
  gateCanonicalNames,
  gateBoundedPrint,
  gateToolEvidence,
  gateApiSurface,
  gateOutputFidelity,
  assertExact,
  canonicalizeId,
  loadSinks,
};
