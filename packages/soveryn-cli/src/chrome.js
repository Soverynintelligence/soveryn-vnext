'use strict';

/**
 * SOVERYN Option 2 chrome — 1985 Commodore 64 / PETSCII-ish lab HUD.
 * Chunkier +-=| / block bezels; large monospace SOVERYN in CRT lab gold
 * on maroon-black panels. Skip: SOVERYN_NO_SPLASH=1
 */

const fs = require('fs');
const path = require('path');
const { BRAND, CMD, IS_KERNEL } = require('./paths');

const RESET = '\x1b[0m';
const BOLD = '\x1b[1m';
const DIM = '\x1b[2m';
const CYAN = '\x1b[36m';
const BRIGHT_CYAN = '\x1b[96m';
const AMBER = '\x1b[33m';
const BRIGHT_AMBER = '\x1b[93m';
/** CRT lab gold #e8bc2a (truecolor) — slightly more saturated than #d4af37 */
const GOLD = '\x1b[38;2;232;188;42m';
const GREEN = '\x1b[32m';
const BRIGHT_GREEN = '\x1b[92m';
const RED = '\x1b[31m';
const GRAY = '\x1b[90m';
const WHITE = '\x1b[97m';

const PKG_ROOT = path.resolve(__dirname, '..');
const THEME_NAME = 'soveryn-lab';
const THEME_SRC = path.join(PKG_ROOT, 'themes', `${THEME_NAME}.json`);


/** Maroon-black lab terminal colors (OSC) — deep burgundy panels + CRT gold cursor. */
const LAB_BG = '#10080c';
const LAB_FG = '#e8e8e8';
const LAB_CURSOR = '#e8bc2a';

function applyLabTerminalColors(stream) {
  try {
    const s = stream || process.stderr;
    if (!s || !s.isTTY) return false;
    // OSC 11 = background, OSC 10 = foreground, OSC 12 = cursor
    s.write(`\x1b]11;${LAB_BG}\x07`);
    s.write(`\x1b]10;${LAB_FG}\x07`);
    s.write(`\x1b]12;${LAB_CURSOR}\x07`);
    return true;
  } catch (_) {
    return false;
  }
}


/** Coarse solid-block SOVERYN — no thin modern box-drawing corners */
const WORDMARK = [
  '███████  ██████  ██    ██ ███████ ██████  ██    ██ ███    ██',
  '██      ██    ██ ██    ██ ██      ██   ██  ██  ██  ████   ██',
  '███████ ██    ██ ██    ██ █████   ██████    ████   ██ ██  ██',
  '     ██ ██    ██  ██  ██  ██      ██   ██    ██    ██  ██ ██',
  '███████  ██████    ████   ███████ ██   ██    ██    ██   ████',
];

function envTruthy(v) {
  if (v == null || v === '') return false;
  const s = String(v).trim().toLowerCase();
  return s === '1' || s === 'true' || s === 'yes' || s === 'on';
}

function wantsColor(stream) {
  // Node convention: FORCE_COLOR wins over NO_COLOR
  if (envTruthy(process.env.FORCE_COLOR)) return true;
  if (envTruthy(process.env.NO_COLOR)) return false;
  const s = stream || process.stderr;
  return !!(s && typeof s.isTTY === 'boolean' ? s.isTTY : process.stderr.isTTY);
}

function paint(enabled, code, text) {
  if (!enabled) return text;
  return `${code}${text}${RESET}`;
}

function shortEndpoint(baseUrl) {
  if (!baseUrl) return '—';
  return String(baseUrl)
    .replace(/^https?:\/\//, '')
    .replace(/\/v1\/?$/, '')
    .replace(/\/$/, '');
}

function pkgVersion() {
  try {
    const raw = fs.readFileSync(path.join(PKG_ROOT, 'package.json'), 'utf8');
    return JSON.parse(raw).version || '0.1.0';
  } catch (_) {
    return '0.1.0';
  }
}

function harnessTag() {
  return IS_KERNEL ? 'kernel' : 'soveryn-cli';
}

/**
 * Ensure soveryn-lab theme is present under CFG_DIR/themes and return theme id.
 */
function ensureLabTheme(cfgDir) {
  try {
    if (!fs.existsSync(THEME_SRC)) return 'dark';
    const destDir = path.join(cfgDir, 'themes');
    fs.mkdirSync(destDir, { recursive: true });
    const dest = path.join(destDir, `${THEME_NAME}.json`);
    const src = fs.readFileSync(THEME_SRC);
    let write = true;
    try {
      if (fs.existsSync(dest) && Buffer.compare(src, fs.readFileSync(dest)) === 0) {
        write = false;
      }
    } catch (_) {
      /* rewrite */
    }
    if (write) fs.writeFileSync(dest, src);
    return THEME_NAME;
  } catch (_) {
    return 'dark';
  }
}

/** PETSCII-ish chunky frame helpers (+ = - |), not thin Unicode boxes */
function petsciiBox(W) {
  return {
    top: `+${'='.repeat(W)}+`,
    bot: `+${'='.repeat(W)}+`,
    mid: `+${'-'.repeat(W)}+`,
    empty: `|${' '.repeat(W)}|`,
    row(inner) {
      const plain = String(inner).replace(/\x1b\[[0-9;]*m/g, '');
      const pad = Math.max(0, W - plain.length);
      return `|${inner}${' '.repeat(pad)}|`;
    },
    center(text, styleFn) {
      const pad = Math.max(0, W - text.length);
      const left = Math.floor(pad / 2);
      const right = pad - left;
      if (!styleFn) return `|${' '.repeat(left)}${text}${' '.repeat(right)}|`;
      return `|${' '.repeat(left)}${styleFn(text)}${' '.repeat(right)}|`;
    },
  };
}

function splashLines(profile, thinking, { online, version, color } = {}) {
  const c = color !== false;
  const think =
    thinking !== undefined && thinking !== null
      ? thinking
      : (profile && profile.defaultThinkingLevel) || 'medium';
  const onlineFlag = online !== false;
  const ver = version || pkgVersion();
  const brain = (profile && (profile.id || profile.displayName)) || '—';
  const model = (profile && profile.modelId) || '—';
  const endpoint = shortEndpoint(profile && profile.baseUrl);
  const statusTxt = onlineFlag ? '* ONLINE' : 'o OFFLINE';
  const statusCol = onlineFlag ? BRIGHT_GREEN : RED;
  const parked = profile && profile.enabled === false;

  const W = Math.max(62, ...WORDMARK.map((l) => l.length));
  const box = petsciiBox(W);

  const lines = [];
  lines.push(paint(c, GRAY, box.top));
  lines.push(paint(c, GRAY, box.empty));
  for (const wm of WORDMARK) {
    lines.push(box.center(wm, (t) => paint(c, BOLD + GOLD, t)));
  }
  lines.push(paint(c, GRAY, box.empty));
  lines.push(
    box.center('LOAD "SOVERYN",8,1', (t) => paint(c, DIM + GOLD, t))
  );
  lines.push(
    box.center('DARK LAB · C64 CHROME · OPTION 2', (t) =>
      paint(c, DIM + AMBER, t)
    )
  );
  lines.push(
    box.center(
      `${harnessTag()} · v${ver} · Pi 0.74.2`,
      (t) => paint(c, GRAY, t)
    )
  );
  lines.push(paint(c, GRAY, box.mid));

  const label = (k) => paint(c, AMBER, k.padEnd(10));
  const val = (v) => paint(c, WHITE, v);

  lines.push(
    box.row(
      ` ${label('BRAIN')}${val(brain)}${parked ? paint(c, RED, ' [PARKED]') : ''} ${paint(c, DIM + GRAY, '·')} ${paint(c, GRAY, model)}`
    )
  );
  lines.push(box.row(` ${label('ENDPOINT')}${val(endpoint)}`));
  lines.push(box.row(` ${label('THINKING')}${val(String(think))}`));
  lines.push(
    box.row(
      ` ${label('STATUS')}${paint(c, BOLD + statusCol, statusTxt)}${paint(c, GOLD, ` · ${String(BRAND || 'SOVERYN').toUpperCase()}`)}`
    )
  );
  lines.push(paint(c, GRAY, box.bot));
  lines.push(paint(c, DIM + GOLD, 'READY.'));
  return lines;
}

/**
 * Full dark-lab splash (stderr by default). Fast, no I/O beyond package.json.
 */
function printSplash(profile, thinking, opts = {}) {
  if (envTruthy(process.env.SOVERYN_NO_SPLASH)) return false;
  const stream = opts.stream || process.stderr;
  const color = opts.color != null ? opts.color : wantsColor(stream);
  if (color && !envTruthy(process.env.SOVERYN_NO_OSC)) {
    applyLabTerminalColors(stream);
  }
  const lines = splashLines(profile, thinking, {
    online: opts.online,
    version: opts.version,
    color,
  });
  stream.write(`${lines.join('\n')}\n`);
  return true;
}

/**
 * Compact one-line banner — coarser C64-ish, no thin boxes.
 */
function bannerLine(profile, thinking, { online, color } = {}) {
  const c = color != null ? color : wantsColor(process.stderr);
  const think =
    thinking !== undefined && thinking !== null
      ? thinking
      : (profile && profile.defaultThinkingLevel) || 'medium';
  const net =
    online === undefined || online === null
      ? ''
      : online
        ? paint(c, BRIGHT_GREEN, ' ONLINE')
        : paint(c, RED, ' OFFLINE');
  const name = paint(c, BOLD + GOLD, 'SOVERYN');
  const brain = paint(c, WHITE, (profile && profile.id) || '?');
  const model = paint(c, GRAY, (profile && profile.modelId) || '?');
  const ep = paint(c, GRAY, shortEndpoint(profile && profile.baseUrl));
  const th = paint(c, AMBER, `THINKING ${think}`);
  const harness = IS_KERNEL ? paint(c, DIM + GRAY, ' · KERNEL') : '';
  const bezel = paint(c, GRAY, '[#]');
  return `${bezel} ${name}${harness} · ${brain} · ${model} · ${ep} · ${th}${net ? ` ·${net}` : ''}`;
}

/**
 * Status / doctor HUD block (stdout) — chunky +-=| bezel.
 */
function statusHud(profile, meta = {}) {
  const c = meta.color != null ? meta.color : wantsColor(process.stdout);
  const online = meta.online;
  const lines = [];
  const W = 58;
  const box = petsciiBox(W);

  lines.push(paint(c, GRAY, box.top));
  for (const wm of WORDMARK) {
    // Wordmark may exceed W — print unbound accent lines
    lines.push(paint(c, BOLD + GOLD, `  ${wm}`));
  }
  lines.push(
    paint(
      c,
      DIM + AMBER,
      `  DARK LAB STATUS · ${harnessTag().toUpperCase()} · v${pkgVersion()}`
    )
  );
  lines.push(paint(c, GRAY, box.mid));

  const L = (k) => paint(c, AMBER, `  ${k.padEnd(12)}`);
  const V = (v) => paint(c, WHITE, v);
  const activeId = meta.activeId || (profile && profile.id) || '—';
  const parked = profile && profile.enabled === false;
  lines.push(
    `${L('ACTIVE')}${V(activeId)}${parked ? paint(c, RED, ' [PARKED]') : ''}`
  );
  lines.push(`${L('MODEL')}${V((profile && profile.modelId) || '—')}`);
  lines.push(`${L('PROVIDER')}${V((profile && profile.piProviderId) || '—')}`);
  lines.push(`${L('ENDPOINT')}${V(shortEndpoint(profile && profile.baseUrl))}`);
  lines.push(
    `${L('THINKING')}${V((profile && profile.defaultThinkingLevel) || 'medium')} ${paint(c, GRAY, '(default)')}`
  );
  if (meta.compactLine) {
    lines.push(`${L('COMPACT')}${V(meta.compactLine)}`);
  }
  if (meta.piLine) {
    lines.push(`${L('PI')}${V(meta.piLine)}`);
  }
  if (online !== undefined && online !== null) {
    lines.push(
      `${L('NET')}${online ? paint(c, BRIGHT_GREEN, '* ONLINE') : paint(c, RED, 'o OFFLINE')}`
    );
  } else {
    lines.push(`${L('NET')}${paint(c, BRIGHT_GREEN, '* ONLINE')} ${paint(c, GRAY, '(default)')}`);
  }
  if (meta.profileFile) {
    lines.push(`${L('PROFILE')}${paint(c, GRAY, meta.profileFile)}`);
  }
  if (meta.syncedFile) {
    lines.push(`${L('SYNCED')}${paint(c, GRAY, meta.syncedFile)}`);
  }
  lines.push(paint(c, GRAY, box.bot));
  lines.push(paint(c, DIM + GOLD, 'READY.'));
  return lines.join('\n');
}

function colorOk(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  return paint(c, BRIGHT_GREEN, text);
}
function colorDown(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  return paint(c, RED, text);
}
function colorParked(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  return paint(c, AMBER, text);
}
function colorMuted(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  return paint(c, GRAY, text);
}
function colorAccent(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  // Prefer gold over cyan for CRT / C64 feel
  return paint(c, GOLD, text);
}
function colorLabel(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  return paint(c, AMBER, text);
}
function colorBrand(text, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  return paint(c, BOLD + GOLD, text || 'SOVERYN');
}

function profileRow(id, activeId, health, detail, color) {
  const c = color != null ? color : wantsColor(process.stdout);
  const mark = id === activeId ? paint(c, GOLD, '*') : ' ';
  const name = paint(c, id === activeId ? BOLD + WHITE : WHITE, id.padEnd(10));
  let h;
  if (health === 'PARKED') h = colorParked('PARKED', c);
  else if (health === 'OK') h = colorOk('OK   ', c);
  else h = colorDown('DOWN ', c);
  return `   ${mark} ${name} ${h}  ${paint(c, GRAY, detail)}`;
}

module.exports = {
  RESET,
  BOLD,
  DIM,
  CYAN,
  BRIGHT_CYAN,
  AMBER,
  GOLD,
  GREEN,
  BRIGHT_GREEN,
  RED,
  GRAY,
  WHITE,
  THEME_NAME,
  THEME_SRC,
  WORDMARK,
  wantsColor,
  paint,
  shortEndpoint,
  pkgVersion,
  ensureLabTheme,
  applyLabTerminalColors,
  LAB_BG,
  LAB_FG,
  LAB_CURSOR,
  splashLines,
  printSplash,
  bannerLine,
  statusHud,
  colorOk,
  colorDown,
  colorParked,
  colorMuted,
  colorAccent,
  colorLabel,
  colorBrand,
  profileRow,
  envTruthy,
};
