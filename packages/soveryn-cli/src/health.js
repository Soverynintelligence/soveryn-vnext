'use strict';

const http = require('http');
const https = require('https');
const { URL } = require('url');

/**
 * Probe profile health endpoint.
 * @param {object} profile
 * @param {number} [timeoutMs=1000]
 * @param {{ requireModel?: boolean }} [opts]
 *   requireModel: if true, also require profile.modelId present in /models JSON
 */
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
          try {
            const j = JSON.parse(body);
            ids = (j.data || []).map((m) => m && m.id).filter(Boolean);
          } catch (_) {
            done(false, `HTTP ${res.statusCode} but body not JSON models list`);
            return;
          }
          if (ids.includes(profile.modelId)) {
            done(true, `HTTP ${res.statusCode}; model ${profile.modelId} present`, {
              modelIds: ids,
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

module.exports = { probe };
