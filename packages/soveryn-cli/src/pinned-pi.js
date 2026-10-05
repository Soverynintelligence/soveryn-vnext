'use strict';

/**
 * Pinned Pi runtime for the SOVERYN CLI.
 *   2026-09-28: Pi 0.87.1 on Node 22 (bin/soveryn-pi087 — kept as rollback)
 *   2026-09-30: Pi 0.99.1 on Node 22 (bin/soveryn-pi099 — kept as rollback)
 *   2026-10-02: Pi 1.0.0 on Node 22 (bin/soveryn-pi100 — kept as first rollback)
 *   2026-10-05: Pi 1.0.3 on Node 22 (bin/soveryn-pi103 — current)
 *
 * bin/soveryn-piNNN exports SOVERYN_PI_BIN + SOVERYN_PI_NODE (+ SOVERYN_PI_VERSION).
 * Only the soveryn-cli harness honors them. Kernel (SOVERYN_HARNESS=kernel via
 * scripts/soveryn-pi) ignores them and keeps resolving `pi` from PATH
 * (Pi 0.74.2 / Node 20). The vars are stripped from the pi child env so a
 * nested kernel / soveryn-074 launched from inside a SOVERYN session never
 * inherits the pin.
 *
 * Version-gated behavior lives here (not in the launchers) so rolling the
 * symlink back to an older pin also rolls the generated settings back.
 */

const fs = require('fs');
const path = require('path');
const { IS_KERNEL } = require('./paths');

const PIN_ENV_KEYS = Object.freeze(['SOVERYN_PI_BIN', 'SOVERYN_PI_NODE', 'SOVERYN_PI_VERSION']);
const LEGACY_PI_VERSION = '0.74.2';

/** First Pi release with builtin:<name> extensions (mcp, codemode, tool-search, llama.cpp). */
const BUILTIN_EXTENSIONS_SINCE = '0.99.0';

/**
 * Built-ins the SOVERYN CLI turns off on Pi >=0.99. defaultProjectTrust is
 * "always", so builtin:mcp would auto-connect any project .pi/mcp.json.
 * llama.cpp stays on; codemode / tool_search stay loaded but their tools are
 * off by default and only MCP would switch them on.
 */
const DISABLED_BUILTINS = Object.freeze(['mcp']);

/** First Pi release whose interactive TUI defaults to fullscreen (alt screen). */
const TUI_MODE_SINCE = '1.0.0';

/**
 * TUI mode the SOVERYN CLI pins on Pi >=1.0: "regular" keeps the terminal's
 * normal scrollback (the locked C64/PETSCII look as on 0.99.1 and earlier).
 */
const PINNED_TUI_MODE = 'regular';

/** The pin package.json declares (bin/soveryn → current launcher). */
function declaredPin() {
  try {
    const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf8'));
    return pkg.soverynPi || null;
  } catch (_) {
    return null;
  }
}

/** Version from <bin>/../../package.json for dist/bundle/cli.js layouts, else null. */
function piPackageVersion(bin) {
  if (!bin) return null;
  try {
    const pkg = JSON.parse(
      fs.readFileSync(path.join(path.dirname(bin), '..', '..', 'package.json'), 'utf8')
    );
    if (pkg && /pi-coding-agent$/.test(String(pkg.name || '')) && pkg.version) return String(pkg.version);
  } catch (_) {
    /* not a Pi package layout */
  }
  return null;
}

/** Numeric x.y.z compare (pre-release tags ignored). */
function compareVersions(a, b) {
  const pa = String(a || '0').split(/[.-]/).slice(0, 3).map((n) => parseInt(n, 10) || 0);
  const pb = String(b || '0').split(/[.-]/).slice(0, 3).map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < 3; i++) {
    if (pa[i] !== pb[i]) return pa[i] < pb[i] ? -1 : 1;
  }
  return 0;
}

/** Returns { bin, node, version, installedVersion } when a pin is active for this harness, else null. */
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
  const installedVersion = piPackageVersion(bin);
  return { bin, node, version: env.SOVERYN_PI_VERSION || installedVersion || null, installedVersion };
}

/** Warning text when the launcher's SOVERYN_PI_VERSION disagrees with the installed package, else null. */
function pinVersionMismatch(pin) {
  if (!pin || !pin.version || !pin.installedVersion) return null;
  if (pin.version === pin.installedVersion) return null;
  return `SOVERYN_PI_VERSION=${pin.version} but ${pin.bin} is Pi ${pin.installedVersion}`;
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

/**
 * `extensions` setting for the generated settings.json, or null to omit the key.
 * Only the pinned runtime on Pi >=0.99 (older Pi would read "-builtin:mcp" as a
 * path exclusion; Kernel / soveryn-074 settings stay byte-identical).
 */
function pinnedSettingsExtensions(env = process.env) {
  if (!isPinnedRuntime(env)) return null;
  if (compareVersions(piVersionLabel(env), BUILTIN_EXTENSIONS_SINCE) < 0) return null;
  return DISABLED_BUILTINS.map((n) => `-builtin:${n}`);
}

/**
 * `tuiMode` setting for the generated settings.json, or null to omit the key.
 * Only the pinned runtime on Pi >=1.0.0 (fullscreen became the default there);
 * older pins / Kernel / soveryn-074 settings stay byte-identical.
 */
function pinnedSettingsTuiMode(env = process.env) {
  if (!isPinnedRuntime(env)) return null;
  if (compareVersions(piVersionLabel(env), TUI_MODE_SINCE) < 0) return null;
  return PINNED_TUI_MODE;
}

function stripPinEnv(env) {
  const out = { ...env };
  for (const k of PIN_ENV_KEYS) delete out[k];
  return out;
}

module.exports = {
  PIN_ENV_KEYS,
  LEGACY_PI_VERSION,
  BUILTIN_EXTENSIONS_SINCE,
  DISABLED_BUILTINS,
  TUI_MODE_SINCE,
  PINNED_TUI_MODE,
  declaredPin,
  piPackageVersion,
  compareVersions,
  pinnedPi,
  pinVersionMismatch,
  piCommand,
  piVersionLabel,
  isPinnedRuntime,
  pinnedSettingsExtensions,
  pinnedSettingsTuiMode,
  stripPinEnv,
};
