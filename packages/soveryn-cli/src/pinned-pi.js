'use strict';

/**
 * Pinned Pi runtime for the SOVERYN CLI (2026-09-28: Pi 0.87.1 on Node 22).
 *
 * bin/soveryn-pi087 exports SOVERYN_PI_BIN + SOVERYN_PI_NODE (+ SOVERYN_PI_VERSION).
 * Only the soveryn-cli harness honors them. Kernel (SOVERYN_HARNESS=kernel via
 * scripts/soveryn-pi) ignores them and keeps resolving `pi` from PATH
 * (Pi 0.74.2 / Node 20). The vars are stripped from the pi child env so a
 * nested kernel / soveryn-074 launched from inside a SOVERYN session never
 * inherits the pin.
 */

const fs = require('fs');
const { IS_KERNEL } = require('./paths');

const PIN_ENV_KEYS = Object.freeze(['SOVERYN_PI_BIN', 'SOVERYN_PI_NODE', 'SOVERYN_PI_VERSION']);
const LEGACY_PI_VERSION = '0.74.2';

/** Returns { bin, node, version } when a pin is active for this harness, else null. */
function pinnedPi(env = process.env) {
  if (IS_KERNEL) return null;
  const bin = env.SOVERYN_PI_BIN;
  const node = env.SOVERYN_PI_NODE;
  if (!bin && !node) return null;
  // Half-set or missing pin must FAIL, never silently fall back to PATH pi.
  if (!bin || !node) {
    throw new Error('SOVERYN pinned Pi: set both SOVERYN_PI_BIN and SOVERYN_PI_NODE (or neither)');
  }
  if (!fs.existsSync(bin)) throw new Error(`SOVERYN pinned Pi: SOVERYN_PI_BIN missing: ${bin}`);
  if (!fs.existsSync(node)) throw new Error(`SOVERYN pinned Pi: SOVERYN_PI_NODE missing: ${node}`);
  return { bin, node, version: env.SOVERYN_PI_VERSION || null };
}

/** Command + argv to run piBin (pinned → explicit node; legacy → shebang/PATH node). */
function piCommand(piBin, args, env = process.env) {
  const pin = pinnedPi(env);
  if (pin && pin.bin === piBin) return { cmd: pin.node, args: [pin.bin, ...(args || [])] };
  return { cmd: piBin, args: [...(args || [])] };
}

/** Pi version label for chrome/settings (no spawn). */
function piVersionLabel(env = process.env) {
  try {
    const pin = pinnedPi(env);
    if (pin && pin.version) return pin.version;
  } catch (_) {
    /* fall through */
  }
  return LEGACY_PI_VERSION;
}

/** True when the soveryn-cli pinned runtime (Pi >=0.80) is active. Never throws. */
function isPinnedRuntime(env = process.env) {
  try {
    return !!pinnedPi(env);
  } catch (_) {
    return false;
  }
}

function stripPinEnv(env) {
  const out = { ...env };
  for (const k of PIN_ENV_KEYS) delete out[k];
  return out;
}

module.exports = {
  PIN_ENV_KEYS,
  LEGACY_PI_VERSION,
  pinnedPi,
  piCommand,
  piVersionLabel,
  isPinnedRuntime,
  stripPinEnv,
};
