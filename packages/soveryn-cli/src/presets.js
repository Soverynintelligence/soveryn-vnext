'use strict';

/**
 * Tool packs / presets (DeepSeek Harness spirit → Pi --tools + extensions).
 * Pi 0.74.2: --tools <csv> allowlists built-in/extension tools.
 * Defaults (no flag): read, bash, edit, write.
 *
 * Packs: minimal | standard | web
 * --pack and --preset are aliases. SOVERYN_PACK=web forces web.
 * Every pack also loads harness-controls (evidence / loop-guard / showme / G6)
 * and kernel-lattice (house Lattice memory: remember_fact / memory_search /
 * memory_get + per-turn recall inject). Lattice tools are appended to every
 * --tools allowlist so web/minimal packs cannot hide them.
 */

const fs = require('fs');
const path = require('path');
const { autoDetectPack } = require('./detect');

const PKG_ROOT = path.resolve(__dirname, '..');
const WEB_EXTENSION = path.join(PKG_ROOT, 'extensions', 'web-pack.ts');
const WEB_SCRIPTS = path.join(PKG_ROOT, 'scripts', 'web');
const HARNESS_EXTENSION = path.join(PKG_ROOT, 'extensions', 'harness-controls.ts');
const LATTICE_EXTENSION = path.join(PKG_ROOT, 'extensions', 'kernel-lattice.ts');
const LATTICE_TOOLS = Object.freeze(['remember_fact', 'memory_search', 'memory_get']);

/** Tools allowlist + lattice memory tools (deduped, order kept). */
function withLatticeTools(tools) {
  const out = [...tools];
  for (const t of LATTICE_TOOLS) {
    if (!out.includes(t)) out.push(t);
  }
  return out;
}

/**
 * True when the Pi agent dir already auto-discovers a kernel-lattice extension
 * (kernel: config/pi/extensions symlink). Pi dedupes by realpath, but skipping
 * here also avoids a double load if that copy is ever not a symlink.
 */
function agentDirHasLattice(cfgDir) {
  if (!cfgDir) return false;
  return ['kernel-lattice.ts', 'kernel-lattice.js'].some((f) =>
    fs.existsSync(path.join(cfgDir, 'extensions', f))
  );
}

function defaultCfgDir() {
  try {
    return require('./paths').CFG_DIR;
  } catch (_) {
    return null;
  }
}

/** Extensions every pack loads: harness-controls + kernel-lattice. */
function baseExtensions(cfgDir = defaultCfgDir()) {
  const exts = [];
  if (fs.existsSync(HARNESS_EXTENSION)) exts.push(HARNESS_EXTENSION);
  if (fs.existsSync(LATTICE_EXTENSION) && !agentDirHasLattice(cfgDir)) {
    exts.push(LATTICE_EXTENSION);
  }
  return exts;
}

const WEB_TOOLS = [
  'read',
  'bash',
  'edit',
  'write',
  'web-api-probe',
  'html-module-host',
  'open-html',
];

const PACKS = Object.freeze({
  minimal: {
    id: 'minimal',
    label: 'minimal',
    tools: ['bash', 'edit'],
    note: 'bash+edit only (no read/write as first-class tools)',
  },
  standard: {
    id: 'standard',
    label: 'standard',
    tools: null,
    note: 'full built-ins (read, bash, edit, write) + harness-controls',
  },
  web: {
    id: 'web',
    label: 'web',
    tools: WEB_TOOLS,
    extension: WEB_EXTENSION,
    scriptsDir: WEB_SCRIPTS,
    note: 'built-ins + web-api-probe, html-module-host, open-html (live Chromium)',
  },
});

const PRESETS = PACKS;

const PACK_ALIASES = Object.freeze({
  min: 'minimal',
  full: 'standard',
  default: 'standard',
  browser: 'web',
  html: 'web',
  canvas: 'web',
  cathedral: 'web',
});

const PRESET_ALIASES = PACK_ALIASES;

function canonicalizePack(id) {
  if (id == null || id === '') return null;
  const raw = String(id).trim().toLowerCase();
  const mapped = PACK_ALIASES[raw] || raw;
  if (!PACKS[mapped]) {
    const known = Object.keys(PACKS).join(', ');
    throw new Error(`Unknown pack/preset "${id}". Known: ${known}`);
  }
  return mapped;
}

const canonicalizePreset = canonicalizePack;

function materialize(pack, { cfgDir } = {}) {
  const out = {
    id: pack.id,
    label: pack.label,
    tools: pack.tools ? withLatticeTools(pack.tools) : null,
    note: pack.note,
    extension: pack.extension || null,
    scriptsDir: pack.scriptsDir || null,
    extensions: [],
    piArgs: [],
  };
  out.extensions.push(...baseExtensions(cfgDir === undefined ? defaultCfgDir() : cfgDir));
  if (!fs.existsSync(HARNESS_EXTENSION)) {
    out.note = `${pack.note} [WARN harness-controls missing]`;
  }
  if (!fs.existsSync(LATTICE_EXTENSION)) {
    out.note = `${out.note} [WARN kernel-lattice missing]`;
  }
  if (pack.extension) {
    if (!fs.existsSync(pack.extension)) {
      out.note = `${pack.note} [WARN extension missing: ${pack.extension}]`;
    } else {
      out.extensions.push(pack.extension);
    }
  }
  for (const ext of out.extensions) {
    out.piArgs.push('--extension', ext);
  }
  if (out.tools && out.tools.length) {
    out.piArgs.push('--tools', out.tools.join(','));
  }
  return out;
}

function getPack(id) {
  const key = canonicalizePack(id);
  if (!key) return materialize(PACKS.standard);
  return materialize(PACKS[key]);
}

const getPreset = getPack;

function resolvePack({ data, profile, override, cwd } = {}) {
  if (override) return getPack(override);
  const detected = autoDetectPack(cwd || process.cwd());
  if (detected) return getPack(detected);
  if (profile && profile.preset) return getPack(profile.preset);
  if (profile && profile.pack) return getPack(profile.pack);
  if (data && data.defaultPack) return getPack(data.defaultPack);
  if (data && data.defaultPreset) return getPack(data.defaultPreset);
  return getPack('standard');
}

function resolvePreset(opts) {
  return resolvePack(opts);
}

function hasToolsFlag(args) {
  for (const a of args || []) {
    if (
      a === '--tools' ||
      a === '-t' ||
      a === '--no-tools' ||
      a === '-nt' ||
      a === '--no-builtin-tools' ||
      a === '-nbt' ||
      a.startsWith('--tools=') ||
      a.startsWith('-t=')
    ) {
      return true;
    }
  }
  return false;
}

function hasExtensionFlag(args) {
  for (const a of args || []) {
    if (a === '--extension' || a === '-e' || a.startsWith('--extension=') || a.startsWith('-e=')) {
      return true;
    }
  }
  return false;
}

function packPiArgs(pack, passthroughArgs) {
  const args = [];
  const rest = passthroughArgs || [];
  if (!hasExtensionFlag(rest)) {
    const exts =
      pack.extensions && pack.extensions.length
        ? pack.extensions
        : [
            ...baseExtensions(),
            ...(pack.extension && fs.existsSync(pack.extension) ? [pack.extension] : []),
          ];
    for (const ext of exts) {
      args.push('--extension', ext);
    }
  }
  if (pack.tools && pack.tools.length && !hasToolsFlag(rest)) {
    args.push('--tools', withLatticeTools(pack.tools).join(','));
  }
  return args;
}

module.exports = {
  PACKS,
  PRESETS,
  PACK_ALIASES,
  PRESET_ALIASES,
  WEB_EXTENSION,
  WEB_SCRIPTS,
  WEB_TOOLS,
  HARNESS_EXTENSION,
  LATTICE_EXTENSION,
  LATTICE_TOOLS,
  withLatticeTools,
  agentDirHasLattice,
  baseExtensions,
  materialize,
  canonicalizePack,
  canonicalizePreset,
  getPack,
  getPreset,
  resolvePack,
  resolvePreset,
  hasToolsFlag,
  hasExtensionFlag,
  packPiArgs,
};
