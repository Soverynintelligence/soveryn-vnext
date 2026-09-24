'use strict';

/**
 * Tool packs / presets (DeepSeek Harness spirit → Pi --tools + extensions).
 * Pi 0.74.2: --tools <csv> allowlists built-in/extension tools.
 * Defaults (no flag): read, bash, edit, write.
 *
 * Packs: minimal | standard | web
 * --pack and --preset are aliases. SOVERYN_PACK=web forces web.
 * Every pack also loads harness-controls (evidence / loop-guard / showme / G6).
 */

const fs = require('fs');
const path = require('path');
const { autoDetectPack } = require('./detect');

const PKG_ROOT = path.resolve(__dirname, '..');
const WEB_EXTENSION = path.join(PKG_ROOT, 'extensions', 'web-pack.ts');
const WEB_SCRIPTS = path.join(PKG_ROOT, 'scripts', 'web');
const HARNESS_EXTENSION = path.join(PKG_ROOT, 'extensions', 'harness-controls.ts');

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

function materialize(pack) {
  const out = {
    id: pack.id,
    label: pack.label,
    tools: pack.tools ? [...pack.tools] : null,
    note: pack.note,
    extension: pack.extension || null,
    scriptsDir: pack.scriptsDir || null,
    extensions: [],
    piArgs: [],
  };
  if (fs.existsSync(HARNESS_EXTENSION)) {
    out.extensions.push(HARNESS_EXTENSION);
  } else {
    out.note = `${pack.note} [WARN harness-controls missing]`;
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
  if (pack.tools && pack.tools.length) {
    out.piArgs.push('--tools', pack.tools.join(','));
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
            ...(fs.existsSync(HARNESS_EXTENSION) ? [HARNESS_EXTENSION] : []),
            ...(pack.extension && fs.existsSync(pack.extension) ? [pack.extension] : []),
          ];
    for (const ext of exts) {
      args.push('--extension', ext);
    }
  }
  if (pack.tools && pack.tools.length && !hasToolsFlag(rest)) {
    args.push('--tools', pack.tools.join(','));
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
