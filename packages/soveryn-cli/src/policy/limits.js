'use strict';

/**
 * Bounded execution for print-mode (-p/--print) spawns.
 * Default 120s; override via env SOVERYN_PRINT_TIMEOUT_MS or profiles.limits.maxPrintSeconds.
 */

const DEFAULT_MAX_PRINT_SECONDS = 120;

function getPrintTimeoutMs(data) {
  const envRaw = process.env.SOVERYN_PRINT_TIMEOUT_MS;
  if (envRaw != null && String(envRaw).trim() !== '') {
    const n = Number(envRaw);
    if (Number.isFinite(n) && n >= 0) return Math.floor(n);
  }
  const limits = (data && data.limits) || {};
  if (limits.maxPrintSeconds != null) {
    const sec = Number(limits.maxPrintSeconds);
    if (Number.isFinite(sec) && sec >= 0) return Math.floor(sec * 1000);
  }
  if (limits.maxPrintMs != null) {
    const ms = Number(limits.maxPrintMs);
    if (Number.isFinite(ms) && ms >= 0) return Math.floor(ms);
  }
  return DEFAULT_MAX_PRINT_SECONDS * 1000;
}

module.exports = {
  DEFAULT_MAX_PRINT_SECONDS,
  getPrintTimeoutMs,
};
