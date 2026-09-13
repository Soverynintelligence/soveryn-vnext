'use strict';

const fs = require('fs');
const path = require('path');
const {
  CFG_DIR,
  PROFILES_PATH,
  ACTIVE_PROFILE_PATH,
  SIBLING_ACTIVE_PROFILE_PATH,
  CMD,
} = require('./paths');
const { canonicalizeId, resolveCanonicalKey } = require('./policy/canonical');
const { ensureLabTheme, bannerLine } = require('./chrome');

/** Legacy kernel_brain / flag aliases → profile ids */
const PROFILE_ALIASES = Object.freeze({
  flashnext: 'flash',
  'flash-next': 'flash',
  qwen: 'aetheria',
  'qwen38': 'aetheria',
  'kernel-glm': 'flash', // old provider id pointed at Flash-Next live path
  'kernel-qwen': 'aetheria',
});

function resolveProfileAlias(id) {
  const c = canonicalizeId(id);
  if (!c) return c;
  return PROFILE_ALIASES[c] || c;
}

function loadProfiles() {
  const raw = fs.readFileSync(PROFILES_PATH, 'utf8');
  const data = JSON.parse(raw);
  if (!data.profiles || typeof data.profiles !== 'object') {
    throw new Error(`Invalid profiles.json at ${PROFILES_PATH}`);
  }
  return data;
}

function saveProfiles(data) {
  if (!data || !data.profiles || typeof data.profiles !== 'object') {
    throw new Error('saveProfiles: invalid profiles data');
  }
  const dir = path.dirname(PROFILES_PATH);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = `${PROFILES_PATH}.tmp.${process.pid}`;
  fs.writeFileSync(tmp, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
  fs.renameSync(tmp, PROFILES_PATH);
  return PROFILES_PATH;
}

/**
 * Mark profile parked (enabled:false). Does not stop Flash :8888.
 * Optional stopCommand on the profile may be run by the caller — never here.
 */
function markParked(data, profileId, reason) {
  const profile = getProfile(data, profileId);
  profile.enabled = false;
  profile.disabledReason =
    reason ||
    `${profile.displayName || profile.id} parked — ${CMD} unpark ${profile.id} when Lab has serve up`;
  saveProfiles(data);
  return profile;
}

/**
 * Clear parked flag after a successful health probe (caller verifies).
 */
function markUnparked(data, profileId) {
  const profile = getProfile(data, profileId);
  profile.enabled = true;
  if (Object.prototype.hasOwnProperty.call(profile, 'disabledReason')) {
    delete profile.disabledReason;
  }
  saveProfiles(data);
  return profile;
}

function listProfileIds(data) {
  return Object.keys(data.profiles);
}

function getProfile(data, id) {
  const want = resolveProfileAlias(id);
  const key = resolveCanonicalKey(data.profiles, want) || canonicalizeId(want);
  const p = data.profiles[key];
  if (!p) {
    const known = listProfileIds(data).join(', ');
    throw new Error(`Unknown profile "${id}". Known: ${known}`);
  }
  return p;
}

function readActiveId(data) {
  try {
    const raw = fs.readFileSync(ACTIVE_PROFILE_PATH, 'utf8').trim();
    const id = resolveProfileAlias(canonicalizeId(raw));
    const key = resolveCanonicalKey(data.profiles, id);
    if (key) return key;
  } catch (_) {
    /* fall through */
  }
  return resolveProfileAlias(canonicalizeId(data.defaultProfile || 'flash'));
}

function writeActiveFile(filePath, canon) {
  const dir = path.dirname(filePath);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(filePath, `${canon}\n`, 'utf8');
}

function writeActiveId(id) {
  const canon = resolveProfileAlias(canonicalizeId(id));
  writeActiveFile(ACTIVE_PROFILE_PATH, canon);
  // Keep Kernel + soveryn-cli active brains in sync (one SSOT pair)
  try {
    if (
      SIBLING_ACTIVE_PROFILE_PATH &&
      SIBLING_ACTIVE_PROFILE_PATH !== ACTIVE_PROFILE_PATH
    ) {
      writeActiveFile(SIBLING_ACTIVE_PROFILE_PATH, canon);
    }
  } catch (_) {
    /* non-fatal */
  }
  return canon;
}

function assertEnabled(profile) {
  if (profile.enabled === false) {
    const reason = profile.disabledReason || 'profile is parked / disabled';
    const err = new Error(
      `REFUSED: profile "${profile.id}" is parked.\n  ${reason}\n  Unpark when ready: ${CMD} unpark ${profile.id}\n  Or pick a live profile: ${CMD} use flash | ${CMD} use aetheria | ${CMD} model`
    );
    err.code = 'PROFILE_PARKED';
    throw err;
  }
}

function providerEntry(profile) {
  const model = {
    id: profile.modelId,
    name: profile.modelName,
    reasoning: !!profile.reasoning,
    input: profile.input || ['text'],
    contextWindow: profile.contextWindow,
    maxTokens: profile.maxTokens,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
  if (profile.thinkingLevelMap) {
    model.thinkingLevelMap = profile.thinkingLevelMap;
  }
  return {
    baseUrl: profile.baseUrl,
    api: profile.api || 'openai-completions',
    apiKey: profile.apiKey || 'local',
    compat: profile.compat || {
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
    },
    models: [model],
  };
}

function generatePiConfig(data, activeProfile) {
  const providers = {};
  for (const id of listProfileIds(data)) {
    const p = data.profiles[id];
    providers[p.piProviderId] = providerEntry(p);
  }

  const models = { providers };
  const compaction = activeProfile.compaction || {
    // Flash-Next 256k defaults: fire late, keep plenty (see NOTES-failure-modes.md)
    enabled: true,
    reserveTokens: 18432,
    keepRecentTokens: 65536,
  };
  const themeName = ensureLabTheme(CFG_DIR);
  const settings = {
    defaultProvider: activeProfile.piProviderId,
    defaultModel: activeProfile.modelId,
    defaultThinkingLevel: activeProfile.defaultThinkingLevel || 'medium',
    theme: themeName,
    quietStartup: false,
    defaultProjectTrust: 'always',
    enableInstallTelemetry: false,
    compaction,
    retry: {
      enabled: true,
      maxRetries: 3,
      baseDelayMs: 2000,
      provider: { timeoutMs: 3600000, maxRetries: 0 },
    },
    httpIdleTimeoutMs: 600000,
    lastChangelogVersion: '0.74.2',
  };

  fs.mkdirSync(CFG_DIR, { recursive: true });
  fs.writeFileSync(
    path.join(CFG_DIR, 'models.json'),
    `${JSON.stringify(models, null, 2)}\n`,
    'utf8'
  );
  fs.writeFileSync(
    path.join(CFG_DIR, 'settings.json'),
    `${JSON.stringify(settings, null, 2)}\n`,
    'utf8'
  );
}

function piModelSpec(profile) {
  return `${profile.piProviderId}/${profile.modelId}`;
}

function banner(profile, thinking, opts = {}) {
  return bannerLine(profile, thinking, opts);
}

/**
 * Flag compaction shapes that tend to mid-tool-loop amnesia / compact-chase.
 * Returns human-readable warning strings (empty if fine).
 */
function compactionFieldBad(raw) {
  if (raw == null) return true;
  if (String(raw).trim() === '') return true;
  return !Number.isFinite(Number(raw));
}

function compactionWarnings(profile) {
  const c = profile.compaction;
  if (!c || c.enabled === false) return [];
  const warnings = [];
  const ctxRaw = profile.contextWindow;
  const reserveRaw = c.reserveTokens;
  const keepRaw = c.keepRecentTokens;
  const ctx = Number(ctxRaw);
  const maxTok = Number(profile.maxTokens) || 0;
  const reserve = Number(reserveRaw);
  const keep = Number(keepRaw);

  // Non-numeric/missing must SPEAK — isFinite-gated checks used to skip and look clean.
  if (compactionFieldBad(ctxRaw)) {
    warnings.push(
      `contextWindow is not a number (${JSON.stringify(ctxRaw)}) — amnesia/fit checks cannot run`
    );
  }
  if (compactionFieldBad(reserveRaw)) {
    warnings.push(
      `compaction.reserveTokens is not a number (${JSON.stringify(reserveRaw)}) — amnesia/fit checks cannot run`
    );
  }
  if (compactionFieldBad(keepRaw)) {
    warnings.push(
      `compaction.keepRecentTokens is not a number (${JSON.stringify(keepRaw)}) — amnesia/fit checks cannot run`
    );
  }

  if (!compactionFieldBad(reserveRaw) && Number.isFinite(reserve) && maxTok > 0 && reserve < maxTok) {
    warnings.push(
      `compaction.reserveTokens (${reserve}) < maxTokens (${maxTok}) — response may not fit`
    );
  }
  if (
    !compactionFieldBad(reserveRaw) &&
    !compactionFieldBad(ctxRaw) &&
    Number.isFinite(reserve) &&
    Number.isFinite(ctx) &&
    ctx > 0 &&
    reserve > ctx * 0.15
  ) {
    const pct = ((reserve / ctx) * 100).toFixed(1);
    warnings.push(
      `compaction.reserveTokens ${reserve} is ${pct}% of contextWindow ${ctx} — fires early (aggressive)`
    );
  }
  if (
    !compactionFieldBad(keepRaw) &&
    !compactionFieldBad(ctxRaw) &&
    Number.isFinite(keep) &&
    Number.isFinite(ctx) &&
    ctx >= 100000 &&
    keep < 32000
  ) {
    warnings.push(
      `compaction.keepRecentTokens (${keep}) < 32000 on large context — mid-tool-loop amnesia risk`
    );
  }
  if (
    !compactionFieldBad(keepRaw) &&
    !compactionFieldBad(reserveRaw) &&
    Number.isFinite(keep) &&
    Number.isFinite(reserve) &&
    keep > 0 &&
    reserve > 0 &&
    keep < reserve
  ) {
    warnings.push(
      `compaction.keepRecentTokens (${keep}) < reserveTokens (${reserve}) — unusual; may over-summarize`
    );
  }
  return warnings;
}

module.exports = {
  loadProfiles,
  saveProfiles,
  markParked,
  markUnparked,
  listProfileIds,
  getProfile,
  readActiveId,
  writeActiveId,
  assertEnabled,
  generatePiConfig,
  piModelSpec,
  banner,
  compactionWarnings,
  canonicalizeId,
  resolveCanonicalKey,
  resolveProfileAlias,
  PROFILE_ALIASES,
};
