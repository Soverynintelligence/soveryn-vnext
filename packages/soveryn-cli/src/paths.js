'use strict';

const path = require('path');
const os = require('os');

const HOME = process.env.HOME || os.homedir();
const REPO = process.env.SOVERYN_VNEXT || path.join(HOME, 'soveryn_vnext');

/** kernel | soveryn-cli — Kernel writes config/pi; CLI writes config/soveryn-cli */
const HARNESS = String(process.env.SOVERYN_HARNESS || 'soveryn-cli').toLowerCase();
const IS_KERNEL = HARNESS === 'kernel' || HARNESS === 'pi' || HARNESS === 'soveryn-pi';

const DEFAULT_CFG = IS_KERNEL
  ? path.join(REPO, 'config', 'pi')
  : path.join(REPO, 'config', 'soveryn-cli');

/**
 * Kernel: SOVERYN_KERNEL_DIR > SOVERYN_CLI_DIR (only if set by soveryn-pi) > DEFAULT.
 * soveryn-cli: SOVERYN_CLI_DIR > DEFAULT.
 * PI_CODING_AGENT_DIR is aligned by the launcher; do not let a stale CLI dir
 * steal Kernel writes.
 */
let CFG_DIR;
if (IS_KERNEL) {
  CFG_DIR =
    process.env.SOVERYN_KERNEL_DIR ||
    process.env.SOVERYN_CLI_DIR ||
    process.env.PI_CODING_AGENT_DIR ||
    DEFAULT_CFG;
  // Guard: if ambient SOVERYN_CLI_DIR still points at soveryn-cli, force pi.
  if (CFG_DIR.replace(/\/+$/, '').endsWith(`${path.sep}soveryn-cli`)) {
    CFG_DIR = DEFAULT_CFG;
  }
} else {
  CFG_DIR = process.env.SOVERYN_CLI_DIR || DEFAULT_CFG;
}

/** Shared SSOT — Kernel may symlink config/pi/profiles.json → soveryn-cli */
const PROFILES_PATH =
  process.env.SOVERYN_PROFILES_PATH ||
  path.join(
    IS_KERNEL ? path.join(REPO, 'config', 'soveryn-cli') : CFG_DIR,
    'profiles.json'
  );

const ACTIVE_PROFILE_PATH =
  process.env.SOVERYN_CLI_PROFILE_FILE ||
  (IS_KERNEL
    ? path.join(HOME, '.soveryn', 'kernel_brain')
    : path.join(HOME, '.soveryn', 'soveryn-cli-profile'));

/** Sibling active-file kept in sync so Kernel and soveryn CLI share one brain */
const SIBLING_ACTIVE_PROFILE_PATH = IS_KERNEL
  ? path.join(HOME, '.soveryn', 'soveryn-cli-profile')
  : path.join(HOME, '.soveryn', 'kernel_brain');

const BRAND = IS_KERNEL ? 'Kernel' : 'SOVERYN';
const CMD = IS_KERNEL ? 'kernel' : 'soveryn';

module.exports = {
  HOME,
  REPO,
  HARNESS,
  IS_KERNEL,
  CFG_DIR,
  PROFILES_PATH,
  ACTIVE_PROFILE_PATH,
  SIBLING_ACTIVE_PROFILE_PATH,
  BRAND,
  CMD,
};
