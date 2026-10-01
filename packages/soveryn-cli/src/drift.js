'use strict';

const fs = require('fs');
const path = require('path');

/**
 * State-drift checks — recorded state vs observable reality.
 *
 * 1. checkProfileStateDrift: a profile marked PARKED (enabled:false) whose
 *    endpoint actually serves its model → recorded state is stale.
 *    probeFn is injected so this stays unit-testable.
 *
 * 2. generatedConfigDrift: the harness promises "models.json/settings.json
 *    are generated from profiles.json". Hand-edits silently diverge.
 *    Compares the exact objects buildPiConfig() would write against disk.
 */

function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(',')}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys
    .map((k) => `${JSON.stringify(k)}:${stableStringify(value[k])}`)
    .join(',')}}`;
}

/**
 * @param {object} data profiles data (loadProfiles())
 * @param {(profile: object, opts?: object) => Promise<{ok: boolean, detail: string}>} probeFn
 * @returns {Promise<Array<{profileId: string, message: string}>>}
 */
async function checkProfileStateDrift(data, probeFn) {
  const drift = [];
  const ids = Object.keys(data.profiles || {});
  for (const id of ids) {
    const p = data.profiles[id];
    if (p.enabled !== false) continue; // only parked profiles can drift this way
    let res;
    try {
      res = await probeFn(p, { requireModel: true });
    } catch (e) {
      res = { ok: false, detail: e.message };
    }
    if (res && res.ok) {
      drift.push({
        profileId: id,
        message:
          `profile "${id}" is PARKED but ${p.baseUrl} serves "${p.modelId}" — recorded state is stale.`,
      });
    }
  }
  return drift;
}

/**
 * @param {{models: object, settings: object}} built  output of buildPiConfig()
 * @param {string} cfgDir  config dir containing models.json / settings.json
 * @returns {Array<{file: string, message: string}>}
 */
function generatedConfigDrift(built, cfgDir) {
  const drift = [];
  for (const file of ['models.json', 'settings.json']) {
    const diskPath = path.join(cfgDir, file);
    let diskRaw;
    try {
      diskRaw = fs.readFileSync(diskPath, 'utf8');
    } catch (e) {
      drift.push({
        file,
        message: `${file} unreadable from ${cfgDir} (${e.code || e.message}) — regenerate via \`${'soveryn use'} <active>\`.`,
      });
      continue;
    }
    let disk;
    try {
      disk = JSON.parse(diskRaw);
    } catch (e) {
      drift.push({ file, message: `${file} is not valid JSON: ${e.message}` });
      continue;
    }
    const want = built[file.replace('.json', '')];
    if (stableStringify(want) !== stableStringify(disk)) {
      drift.push({
        file,
        message: `${file} diverged from profiles SSOT (hand-edited?) — regenerate via \`${'soveryn use'} <active>\`.`,
      });
    }
  }
  return drift;
}

module.exports = { checkProfileStateDrift, generatedConfigDrift, stableStringify };
