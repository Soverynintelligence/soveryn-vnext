'use strict';

const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { CFG_DIR, BRAND, CMD } = require('./paths');
const {
  generatePiConfig,
  piModelSpec,
  banner,
  assertEnabled,
  compactionWarnings,
} = require('./profiles');
const { getPrintTimeoutMs } = require('./policy/limits');
const { printSplash, bannerLine } = require('./chrome');
const { resolvePack, packPiArgs, hasToolsFlag } = require('./presets');

function findPi() {
  if (process.env.PI_BIN && fs.existsSync(process.env.PI_BIN)) {
    return process.env.PI_BIN;
  }
  const r = spawnSync('bash', ['-lc', 'command -v pi'], { encoding: 'utf8' });
  const p = (r.stdout || '').trim();
  if (r.status === 0 && p && fs.existsSync(p)) return p;
  return null;
}

function piVersion(piBin) {
  try {
    const r = spawnSync(piBin, ['--version'], {
      encoding: 'utf8',
      timeout: 5000,
    });
    const t = `${r.stdout || ''}${r.stderr || ''}`.trim();
    return t || 'unknown';
  } catch (_) {
    return 'unknown';
  }
}

function launchPi({ data, profile, thinking, passthroughArgs, presetOverride, packOverride, codeMode, showme }) {
  assertEnabled(profile);
  generatePiConfig(data, profile);

  const piBin = findPi();
  if (!piBin) {
    console.error(
      'pi not found. Install: npm install -g --ignore-scripts @mariozechner/pi-coding-agent (or @earendil-works/pi-coding-agent)'
    );
    process.exit(1);
  }

  const think =
    thinking !== undefined && thinking !== null
      ? thinking
      : profile.defaultThinkingLevel || 'medium';

  // Resolve cwd from first non-flag directory arg (needed before pack auto-detect)
  const rest = [];
  let cwd = process.cwd();
  let sawDir = false;
  for (const arg of passthroughArgs || []) {
    if (!sawDir && !arg.startsWith('-') && fs.existsSync(arg) && fs.statSync(arg).isDirectory()) {
      cwd = path.resolve(arg);
      sawDir = true;
    } else {
      rest.push(arg);
    }
  }

  const pack = resolvePack({
    data,
    profile,
    override: packOverride || presetOverride,
    cwd,
  });
  const preset = pack; // alias

  let hasModel = false;
  for (const a of rest) {
    if (a === '--model' || a.startsWith('--model=')) hasModel = true;
  }

  const printMode = isPrintMode(rest);

  // Default ONLINE. Opt into Pi --offline via --offline arg, SOVERYN_OFFLINE=1, or PI_OFFLINE=1.
  const offline = wantsOffline(rest, process.env);
  const restSansOffline = rest.filter((a) => a !== '--offline' && a !== '--online');

  // Health warn (non-fatal) — sink: curl_health (see policy/sinks.json)
  try {
    const checkUrl = `${profile.baseUrl.replace(/\/$/, '')}/models`;
    const curl = spawnSync(
      'curl',
      ['-sf', '--max-time', '2', checkUrl],
      { encoding: 'utf8' }
    );
    if (curl.status !== 0) {
      console.error(`${CMD}: WARN — ${checkUrl} not answering; warm the brain first`);
    }
  } catch (_) {
    /* ignore */
  }

  for (const w of compactionWarnings(profile)) {
    console.error(`${CMD}: WARN — ${w}`);
  }

  // Option 2 dark-lab splash (SOVERYN_NO_SPLASH=1 to skip)
  const splashed = printSplash(profile, think, { online: !offline });
  if (!splashed) {
    console.error(banner(profile, think, { online: !offline }));
  } else {
    console.error(bannerLine(profile, think, { online: !offline }));
  }
  console.error(`${CMD}: PI_CODING_AGENT_DIR=${CFG_DIR}  pi=${piBin}`);
  console.error(`${CMD}: pack=${pack.id} (${pack.note})`);
  if (pack.id === 'web' && pack.scriptsDir) {
    console.error(`${CMD}: web scripts: ${pack.scriptsDir}`);
  }
  if (codeMode) {
    console.error(`${CMD}: code-mode ON (append anti-roundtrip hint)`);
  }
  const showmeOn = !!(showme || ['1','true','yes','on'].includes(String(process.env.SOVERYN_SHOWME||'').trim().toLowerCase()));
  if (showmeOn) {
    process.env.SOVERYN_SHOWME = '1';
    console.error(`${CMD}: showme ON (visual done needs screenshot/file:// evidence)`);
  }

  const env = {
    ...process.env,
    PI_CODING_AGENT_DIR: CFG_DIR,
    PI_TELEMETRY: '0',
    PI_SKIP_VERSION_CHECK: '1',
    OPENAI_API_KEY: process.env.OPENAI_API_KEY || 'local',
  };

  const piArgs = [];
  if (offline) {
    piArgs.push('--offline');
  }
  if (!hasModel) {
    piArgs.push('--model', piModelSpec(profile));
  }
  if (think !== null && think !== undefined && think !== '') {
    piArgs.push('--thinking', String(think));
  }
  // Tool pack → Pi --tools + --extension (skip pieces caller already set)
  const fromPack = packPiArgs(pack, restSansOffline);
  if (fromPack.length) {
    piArgs.push(...fromPack);
  }
  // Code-mode spirit: append stronger anti-roundtrip hint for this session
  if (codeMode) {
    const codeModePath = path.join(__dirname, '..', 'prompts', 'CODE-MODE.append.md');
    if (fs.existsSync(codeModePath)) {
      piArgs.push('--append-system-prompt', codeModePath);
    } else {
      console.error(`${CMD}: WARN — code-mode append missing: ${codeModePath}`);
    }
  }
  // Print/one-shot: avoid session resume noise; pi still accepts explicit --session*.
  if (printMode && !hasSessionFlag(restSansOffline)) {
    piArgs.push('--no-session');
  }
  piArgs.push(...restSansOffline);

  console.error(
    offline
      ? `${CMD}: OFFLINE (Pi --offline / PI_OFFLINE — startup network disabled)`
      : `${CMD}: ONLINE (default; pass --offline or SOVERYN_OFFLINE=1 to disable startup net)`
  );

  // Pi 0.74.2 -p/--print still reads stdin for more messages when stdin is a
  // pipe (non-TTY). Under agents/CI/redirects that pipe never EOFs → ~60s hang
  // after the banner. Close stdin for print mode only; keep inherit for TUI.
  const stdio = printMode
    ? ['ignore', 'inherit', 'inherit']
    : 'inherit';

  const { spawn } = require('child_process');
  const child = spawn(piBin, piArgs, {
    env,
    cwd,
    stdio,
  });

  // Bounded execution (policy): kill -p spawn if exceeded.
  // Default 120s; profiles.limits.maxPrintSeconds or SOVERYN_PRINT_TIMEOUT_MS.
  let printTimer = null;
  if (printMode) {
    const timeoutMs = getPrintTimeoutMs(data);
    if (timeoutMs > 0) {
      console.error(`${CMD}: print timeout ${timeoutMs}ms (SOVERYN_PRINT_TIMEOUT_MS / limits.maxPrintSeconds)`);
      printTimer = setTimeout(() => {
        console.error(
          `${CMD}: FAIL — print mode exceeded ${timeoutMs}ms; killing pi (bounded exec)`
        );
        try {
          child.kill('SIGTERM');
        } catch (_) {
          /* ignore */
        }
        setTimeout(() => {
          try {
            if (!child.killed) child.kill('SIGKILL');
          } catch (_) {
            /* ignore */
          }
        }, 2000).unref();
      }, timeoutMs);
      if (typeof printTimer.unref === 'function') printTimer.unref();
    }
  }

  child.on('error', (err) => {
    if (printTimer) clearTimeout(printTimer);
    console.error(`${CMD}: failed to spawn pi: ${err.message}`);
    process.exit(1);
  });
  child.on('exit', (code, signal) => {
    if (printTimer) clearTimeout(printTimer);
    if (signal) {
      // If we killed for timeout, exit 124 (timeout convention)
      if (printMode && (signal === 'SIGTERM' || signal === 'SIGKILL')) {
        process.exit(124);
      }
      process.kill(process.pid, signal);
    }
    process.exit(code == null ? 1 : code);
  });
}

function isPrintMode(args) {
  for (const a of args || []) {
    if (a === '-p' || a === '--print') return true;
  }
  return false;
}

function hasSessionFlag(args) {
  for (const a of args || []) {
    if (
      a === '--no-session' ||
      a === '--session' ||
      a === '--continue' ||
      a === '-c' ||
      a === '--resume' ||
      a === '-r' ||
      a === '--fork' ||
      a.startsWith('--session=') ||
      a.startsWith('--fork=') ||
      a.startsWith('--session-dir')
    ) {
      return true;
    }
  }
  return false;
}

function envTruthy(v) {
  if (v == null || v === '') return false;
  const s = String(v).trim().toLowerCase();
  return s === '1' || s === 'true' || s === 'yes' || s === 'on';
}

/** Default online. --online wins over env; --offline or SOVERYN_OFFLINE/PI_OFFLINE opts in. */
function wantsOffline(args, env) {
  let offline = envTruthy(env.SOVERYN_OFFLINE) || envTruthy(env.PI_OFFLINE);
  for (const a of args || []) {
    if (a === '--offline') offline = true;
    if (a === '--online') offline = false;
  }
  return offline;
}

module.exports = { findPi, piVersion, launchPi, wantsOffline, hasSessionFlag, isPrintMode };

