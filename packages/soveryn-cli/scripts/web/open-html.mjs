#!/usr/bin/env node
/**
 * open-html — open an HTML file/URL in Chromium with house 20s timeout.
 * Optional screenshot via Chrome --screenshot (still bounded).
 *
 * Usage:
 *   node open-html.mjs path/to/file.html
 *   node open-html.mjs http://127.0.0.1:8765/host.html
 *   node open-html.mjs file.html --screenshot out.png
 *   node open-html.mjs file.html --headless   # dump-dom smoke only
 */
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { findChrome, CHROME_TIMEOUT_SEC } from './find-chrome.mjs';

function parseArgs(argv) {
  const out = { target: null, screenshot: null, headless: false, help: false };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--headless') out.headless = true;
    else if (a === '--screenshot') out.screenshot = resolve(argv[++i]);
    else if (a.startsWith('--screenshot=')) out.screenshot = resolve(a.slice(14));
    else if (a.startsWith('-')) throw new Error(`unknown flag: ${a}`);
    else if (!out.target) out.target = a;
    else throw new Error(`unexpected arg: ${a}`);
  }
  return out;
}

function toUrl(target) {
  if (!target) throw new Error('target required');
  if (/^https?:\/\//i.test(target) || /^file:/i.test(target) || /^data:/i.test(target)) {
    return target;
  }
  const abs = resolve(target);
  if (!existsSync(abs)) throw new Error(`file not found: ${abs}`);
  return pathToFileURL(abs).href;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help || !opts.target) {
    console.log(`Usage: open-html.mjs <file|url> [--screenshot out.png] [--headless]
Wraps Chromium with timeout ${CHROME_TIMEOUT_SEC}s (SOVERYN_CHROME_TIMEOUT). Never unbounded.`);
    process.exit(opts.help ? 0 : 1);
  }

  const chrome = findChrome();
  if (!chrome) {
    console.log(JSON.stringify({
      ok: false,
      error: 'Chrome/Chromium not found. Set CHROME_BIN or install google-chrome.',
    }, null, 2));
    process.exit(2);
  }

  const url = toUrl(opts.target);
  const args = ['--disable-gpu', '--no-sandbox', '--disable-dev-shm-usage'];
  if (opts.screenshot || opts.headless) {
    args.unshift('--headless=new');
  }
  if (opts.screenshot) {
    args.push(`--screenshot=${opts.screenshot}`);
    args.push('--window-size=1280,720');
  }
  if (opts.headless && !opts.screenshot) {
    args.push('--dump-dom');
  }
  args.push(url);

  const r = spawnSync('timeout', [`${CHROME_TIMEOUT_SEC}s`, chrome, ...args], {
    encoding: 'utf8',
    maxBuffer: 8 * 1024 * 1024,
  });

  const report = {
    ok: r.status === 0 || (opts.headless && r.status === 0),
    chrome,
    url,
    timeoutSec: CHROME_TIMEOUT_SEC,
    status: r.status,
    signal: r.signal,
    screenshot: opts.screenshot || null,
    screenshotExists: opts.screenshot ? existsSync(opts.screenshot) : null,
  };

  if (opts.headless && !opts.screenshot) {
    const dom = (r.stdout || '').slice(0, 4000);
    report.domPreview = dom;
  }
  if (r.status !== 0 && r.stderr) {
    report.stderr = String(r.stderr).slice(0, 800);
  }

  // Interactive (non-headless) often exits non-zero when timeout kills — still useful.
  if (!opts.headless && !opts.screenshot && (r.signal === 'SIGTERM' || r.status === 124)) {
    report.ok = true;
    report.note = 'Chrome closed by house timeout (expected for interactive open).';
  }

  console.log(JSON.stringify(report, null, 2));
  process.exit(report.ok || report.screenshotExists ? 0 : (r.status === 2 ? 2 : 1));
}

main();
