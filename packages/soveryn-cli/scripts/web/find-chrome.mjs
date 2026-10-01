'use strict';
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';

const CANDIDATES = [
  process.env.CHROME_BIN,
  process.env.GOOGLE_CHROME_BIN,
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/snap/bin/chromium',
].filter(Boolean);

export function findChrome() {
  for (const p of CANDIDATES) {
    if (p && existsSync(p)) return p;
  }
  const r = spawnSync('bash', ['-lc', 'command -v google-chrome || command -v chromium || command -v chromium-browser'], {
    encoding: 'utf8',
  });
  const hit = (r.stdout || '').trim().split('\n')[0];
  if (hit && existsSync(hit)) return hit;
  return null;
}

export const CHROME_TIMEOUT_SEC = Number(process.env.SOVERYN_CHROME_TIMEOUT || 20);
