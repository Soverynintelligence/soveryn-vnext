'use strict';

const http = require('http');
const https = require('https');
const { URL } = require('url');

/**
 * Probe profile health endpoint.
 * @param {object} profile
 * @param {number} [timeoutMs=1000]
 * @param {{ requireModel?: boolean }} [opts]
 *   requireModel: if true, also require profile.modelId present in /models JSON,
 *   either as a model `id` or in that model's `aliases` (llama.cpp router lists
 *   e.g. id "qwen38" with aliases ["aetheria", ...]). A bare HTTP 200 from a
 *   server that does not serve the name is NOT healthy.
 */
/**
 * Find the /models entry serving `name`: exact `id`, else listed in `aliases`.
 * @param {Array<{id: string, aliases?: string[]}>} models
 * @param {string} name
 * @returns {object|null}
 */
function findModel(models, name) {
  if (!name) return null;
  const byId = models.find((m) => m.id === name);
  if (byId) return byId;
  return (
    models.find((m) => Array.isArray(m.aliases) && m.aliases.includes(name)) || null
  );
}

function probe(profile, timeoutMs = 1000, opts = {}) {
  const requireModel = !!opts.requireModel;
  const base = profile.baseUrl.replace(/\/$/, '');
  const healthPath = profile.healthPath || '/models';
  // baseUrl already ends with /v1; healthPath is /models → /v1/models
  const urlStr = healthPath.startsWith('http')
    ? healthPath
    : `${base}${healthPath.startsWith('/') ? '' : '/'}${healthPath}`;

  return new Promise((resolve) => {
    let settled = false;
    const done = (ok, detail, extra = {}) => {
      if (settled) return;
      settled = true;
      resolve({ ok, detail, url: urlStr, ...extra });
    };

    let url;
    try {
      url = new URL(urlStr);
    } catch (e) {
      done(false, `bad url: ${e.message}`);
      return;
    }

    const lib = url.protocol === 'https:' ? https : http;
    const req = lib.get(
      {
        hostname: url.hostname,
        port: url.port || (url.protocol === 'https:' ? 443 : 80),
        path: `${url.pathname}${url.search}`,
        timeout: timeoutMs,
        headers: { Accept: 'application/json' },
      },
      (res) => {
        const chunks = [];
        res.on('data', (c) => chunks.push(c));
        res.on('end', () => {
          const httpOk = res.statusCode >= 200 && res.statusCode < 300;
          if (!httpOk) {
            done(false, `HTTP ${res.statusCode}`);
            return;
          }
          if (!requireModel || !profile.modelId) {
            done(true, `HTTP ${res.statusCode}`);
            return;
          }
          const body = Buffer.concat(chunks).toString('utf8');
          let ids = [];
          let match = null;
          try {
            const j = JSON.parse(body);
            const models = (j.data || []).filter((m) => m && m.id);
            ids = models.map((m) => m.id);
            match = findModel(models, profile.modelId);
          } catch (_) {
            done(false, `HTTP ${res.statusCode} but body not JSON models list`);
            return;
          }
          if (match) {
            const via = match.id === profile.modelId ? '' : ` (alias of ${match.id})`;
            done(true, `HTTP ${res.statusCode}; model ${profile.modelId} present${via}`, {
              modelIds: ids,
              matchedId: match.id,
            });
          } else {
            done(
              false,
              `HTTP ${res.statusCode} but model "${profile.modelId}" missing (have: ${ids.join(',') || 'none'})`,
              { modelIds: ids }
            );
          }
        });
      }
    );
    req.on('timeout', () => {
      req.destroy();
      done(false, 'timeout');
    });
    req.on('error', (e) => done(false, e.message));
  });
}

/**
 * probe with retries — one flaky timeout/reset over the house network should
 * not read as DOWN. `retries` = extra attempts (default 0 = single shot).
 */
async function probeStable(profile, timeoutMs = 1000, opts = {}) {
  const retries = Math.max(0, Number(opts.retries) || 0);
  let last;
  for (let attempt = 0; attempt <= retries; attempt++) {
    last = await probe(profile, timeoutMs, opts);
    if (last.ok) return last;
    if (attempt < retries) {
      await new Promise((r) => setTimeout(r, 250));
    }
  }
  return last;
}

module.exports = { probe, probeStable, findModel };
