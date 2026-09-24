'use strict';

/**
 * GLM park / unpark — Lab-verified 2026-09-10.
 *
 * CRITICAL: GLM EXL3 TP=2 is NOT hot-standby beside Flash-Next.
 * Both Sparks are required. spark2 runs Flash-Next live; starting GLM
 * requires stopping Flash-Next first. Owner-gated (--confirm) only.
 * No ABLIT / no weight reseat — bring existing EXL3 recipe back.
 */

const { spawnSync } = require('child_process');
const path = require('path');
const {
  loadProfiles,
  getProfile,
  markParked,
  markUnparked,
  writeActiveId,
  generatePiConfig,
  readActiveId,
  banner,
} = require('./profiles');
const { probe } = require('./health');
const { REPO, CMD, BRAND } = require('./paths');

const GLM_ID = 'glm';
const FLASH_ID = 'flash';
const GLM_URL = 'http://10.10.10.2:8001/v1';
const GLM_MODEL = 'glm-5.3-flash';

const SPARK1 = process.env.SOVERYN_SPARK1_HOST || 'spark';
const SPARK2 = process.env.SOVERYN_SPARK2_HOST || 'spark2';

const FLASH_DIR = '~/Qwen3.8-Flash-Next-Single-DGX-Spark';
const GLM_DIR = '/home/soverynspark/src/GLM-5.3-Flash-EXL3-2x-DGX-Sparks';
const SWITCH_BRAIN = path.join(REPO, 'scripts', 'switch_kernel_brain.sh');

function warnBanner() {
  return [
    `WARNING: Unparking GLM is NOT hot standby beside Flash-Next.`,
    `  • Needs BOTH Sparks (EXL3 TP=2). spark2 is live Flash-Next today.`,
    `  • Starting GLM requires STOPPING Flash-Next first.`,
    `  • Owner-gated only. No ABLIT / no weight reseat.`,
    `  • Endpoint remains ${GLM_URL} model ${GLM_MODEL}.`,
  ].join('\n');
}

function unparkStepsText() {
  return [
    'UNPARK sequence (Lab 2026-09-10) — prefer EXL3 over legacy NVFP4 glm53-serve:',
    `  1. Stop Flash-Next on spark2 (from spark1 or tower via ProxyJump):`,
    `       ssh ${SPARK1} "ssh soverynspark2@10.10.11.2 'cd ${FLASH_DIR} && ./stop.sh'"`,
    `     # or:  ssh ${SPARK2} 'cd ${FLASH_DIR} && ./stop.sh'`,
    `  2. Start GLM EXL3 on spark1:`,
    `       ssh ${SPARK1} 'cd ${GLM_DIR} && ./start.sh'`,
    `  3. Wait until healthy:`,
    `       curl -fsS ${GLM_URL}/models   # must list ${GLM_MODEL}`,
    `  4. On tower — enable profile + switch:`,
    `       ${CMD} unpark glm --confirm          # enables if :8001 already serves ${GLM_MODEL}`,
    `       # or after Lab start: ${CMD} unpark glm --if-healthy`,
    `       ${CMD} use glm`,
    `       # optional: bash ${SWITCH_BRAIN} glm`,
    '',
    `Dry / safe options (do NOT stop Flash):`,
    `  ${CMD} unpark glm                 # print this warning + steps; exit 2`,
    `  ${CMD} unpark glm --if-healthy     # probe only; enable if ${GLM_MODEL} live`,
    `  ${CMD} unpark glm --confirm        # if already healthy → enable; else run full swap`,
  ].join('\n');
}

function parkStepsText() {
  return [
    'RE-PARK / park glm sequence (Lab 2026-09-10):',
    `  1. Stop GLM on spark1:`,
    `       ssh ${SPARK1} 'cd ${GLM_DIR} && ./stop.sh'`,
    `  2. Start Flash-Next on spark2:`,
    `       ssh ${SPARK1} "ssh soverynspark2@10.10.11.2 'cd ${FLASH_DIR} && ./start.sh'"`,
    `     # or:  ssh ${SPARK2} 'cd ${FLASH_DIR} && ./start.sh'`,
    `  3. On tower:`,
    `       systemctl --user start soveryn-spark2-flashnext-8888.service`,
    `       ${CMD} use flash`,
    `       ${CMD} park glm --confirm     # marks profile parked after serve swap`,
    `       # optional: bash ${SWITCH_BRAIN} flashnext`,
    '',
    `Without --confirm this command only prints steps and exits non-zero.`,
    `Never kills Flash :8888 unless --confirm runs the Lab re-park path.`,
  ].join('\n');
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout: opts.timeoutMs || 120000,
    env: process.env,
  });
  return {
    ok: r.status === 0,
    status: r.status,
    stdout: (r.stdout || '').trim(),
    stderr: (r.stderr || '').trim(),
    error: r.error,
  };
}

function ssh(host, remoteCmd, timeoutMs = 180000) {
  console.log(`  $ ssh ${host} ${JSON.stringify(remoteCmd)}`);
  const r = run('ssh', [
    '-o', 'BatchMode=yes',
    '-o', 'ConnectTimeout=15',
    host,
    remoteCmd,
  ], { timeoutMs });
  if (r.stdout) console.log(r.stdout);
  if (r.stderr) console.error(r.stderr);
  if (r.error) {
    console.error(`  ssh error: ${r.error.message}`);
    return false;
  }
  if (!r.ok) {
    console.error(`  ssh exit ${r.status}`);
    return false;
  }
  return true;
}

async function waitForGlm(timeoutMs = 600000, intervalMs = 5000) {
  const data = loadProfiles();
  const profile = getProfile(data, GLM_ID);
  const deadline = Date.now() + timeoutMs;
  let n = 0;
  while (Date.now() < deadline) {
    n += 1;
    const h = await probe(profile, 5000, { requireModel: true });
    console.log(`  poll #${n}: ${h.ok ? 'OK' : 'WAIT'} — ${h.detail}`);
    if (h.ok) return h;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return { ok: false, detail: `timeout after ${timeoutMs}ms waiting for ${GLM_MODEL}` };
}

function parseParkFlags(args) {
  const out = {
    confirm: false,
    ifHealthy: false,
    dryRun: false,
    useAfter: true,
    rest: [],
  };
  for (const a of args) {
    if (a === '--confirm') out.confirm = true;
    else if (a === '--if-healthy') out.ifHealthy = true;
    else if (a === '--dry-run' || a === '--dry') out.dryRun = true;
    else if (a === '--no-use') out.useAfter = false;
    else out.rest.push(a);
  }
  return out;
}

async function enableGlmAndMaybeUse({ useAfter }) {
  const data = loadProfiles();
  const profile = markUnparked(data, GLM_ID);
  if (useAfter) {
    writeActiveId(GLM_ID);
    generatePiConfig(loadProfiles(), profile);
    console.log(`Active brain → ${GLM_ID}`);
    console.log(banner(profile));
  } else {
    console.log(`Profile ${GLM_ID} enabled (active unchanged: ${readActiveId(loadProfiles())})`);
  }
  console.log(`Wrote ${require('./paths').PROFILES_PATH}`);
  return profile;
}

/**
 * unpark glm
 *  - no flags: warn + steps, exit 2
 *  - --if-healthy: probe only; enable if glm-5.3-flash live (never stop Flash)
 *  - --confirm: if already healthy → enable; else run Lab swap (stops Flash!)
 *  - --dry-run: print steps only (even with --confirm), exit 0
 */
async function cmdUnpark(id, args) {
  const want = String(id || '').toLowerCase();
  if (want !== 'glm') {
    console.error(`${CMD} unpark: only "glm" is supported today (got "${id}")`);
    process.exit(1);
  }
  const flags = parseParkFlags(args || []);
  const data = loadProfiles();
  const profile = getProfile(data, GLM_ID);

  console.log(warnBanner());
  console.log('');

  if (flags.dryRun) {
    console.log(unparkStepsText());
    console.log('');
    console.log('DRY-RUN: no SSH, no profile writes, Flash untouched.');
    process.exit(0);
  }

  // Always probe first
  const health = await probe(profile, 4000, { requireModel: true });
  console.log(`Probe ${profile.baseUrl}${profile.healthPath || '/models'}: ${health.ok ? 'HEALTHY' : 'DOWN'} (${health.detail})`);

  if (flags.ifHealthy) {
    if (!health.ok) {
      console.error('');
      console.error(`REFUSED: --if-healthy but endpoint not serving ${GLM_MODEL}.`);
      console.error(`  ${health.detail}`);
      console.error(`  Flash-Next left running. Ask Lab to start GLM, or use:`);
      console.error(`    ${CMD} unpark glm --confirm   # OWNER: stops Flash, starts EXL3`);
      console.error('');
      console.error(unparkStepsText());
      process.exit(2);
    }
    await enableGlmAndMaybeUse({ useAfter: flags.useAfter });
    console.log('Unparked via --if-healthy (no serve swap).');
    return;
  }

  if (!flags.confirm) {
    console.error('');
    console.error(`REFUSED: ${CMD} unpark glm requires --confirm (or --if-healthy).`);
    console.error('  Full unpark STOPS Flash-Next on spark2 and starts GLM EXL3 on both Sparks.');
    console.error('');
    console.error(unparkStepsText());
    process.exit(2);
  }

  // --confirm
  if (health.ok) {
    console.log(`:8001 already serves ${GLM_MODEL} — enabling profile only (no restart).`);
    await enableGlmAndMaybeUse({ useAfter: flags.useAfter });
    console.log('Unparked (already healthy).');
    return;
  }

  console.log('');
  console.log('Owner --confirm: running Lab UNPARK swap (will STOP Flash-Next on spark2)…');

  // 1. Stop Flash-Next on spark2
  const stopFlash =
    `ssh -o BatchMode=yes -o ConnectTimeout=15 soverynspark2@10.10.11.2 ` +
    `'cd ${FLASH_DIR} && ./stop.sh'`;
  if (!ssh(SPARK1, stopFlash, 180000)) {
    // fallback via ProxyJump host alias
    console.log('  retry via spark2 host alias…');
    if (!ssh(SPARK2, `cd ${FLASH_DIR} && ./stop.sh`, 180000)) {
      console.error('FAILED to stop Flash-Next on spark2. Aborting before GLM start.');
      process.exit(3);
    }
  }

  // 2. Start GLM EXL3 on spark1
  if (!ssh(SPARK1, `cd ${GLM_DIR} && ./start.sh`, 300000)) {
    console.error('FAILED to start GLM EXL3. Flash may be down — restore with:');
    console.error(parkStepsText());
    process.exit(3);
  }

  // 3. Wait for model
  console.log(`Waiting for ${GLM_MODEL} on ${GLM_URL} (up to ~10 min)…`);
  const ready = await waitForGlm(600000, 5000);
  if (!ready.ok) {
    console.error(`GLM did not become healthy: ${ready.detail}`);
    console.error('Profile left parked. Restore Flash with park steps if needed.');
    process.exit(3);
  }

  // 4. Enable + use
  await enableGlmAndMaybeUse({ useAfter: flags.useAfter });
  const sw = run('bash', [SWITCH_BRAIN, 'glm'], { timeoutMs: 60000 });
  if (!sw.ok) {
    console.log(`Note: switch_kernel_brain.sh glm exited ${sw.status} (profile already enabled; vnext restart optional)`);
    if (sw.stderr) console.log(sw.stderr);
  }
  console.log('Unpark complete. Flash-Next is down; GLM is active.');
}

/**
 * park glm
 *  - no --confirm: warn + steps, exit 2 (or --dry-run exit 0)
 *  - --confirm: Lab re-park (stop GLM, start Flash, mark parked, use flash)
 *  - --profile-only with --confirm: mark parked + use flash, do not SSH
 */
async function cmdPark(id, args) {
  const want = String(id || '').toLowerCase();
  if (want !== 'glm') {
    console.error(`${CMD} park: only "glm" is supported today (got "${id}")`);
    process.exit(1);
  }
  const flags = parseParkFlags(args || []);
  const profileOnly = (args || []).includes('--profile-only');

  console.log(warnBanner());
  console.log('');

  if (flags.dryRun) {
    console.log(parkStepsText());
    console.log('');
    console.log('DRY-RUN: no SSH, no profile writes.');
    process.exit(0);
  }

  if (!flags.confirm) {
    console.error(`REFUSED: ${CMD} park glm requires --confirm (owner-gated).`);
    console.error('  Full park STOPS GLM EXL3 and restarts Flash-Next on spark2.');
    console.error(`  Profile-only (no SSH): ${CMD} park glm --confirm --profile-only`);
    console.error('');
    console.error(parkStepsText());
    process.exit(2);
  }

  if (!profileOnly) {
    console.log('Owner --confirm: running Lab RE-PARK swap…');

    // 1. Stop GLM
    if (!ssh(SPARK1, `cd ${GLM_DIR} && ./stop.sh`, 300000)) {
      console.error('FAILED to stop GLM. Aborting before Flash restart.');
      process.exit(3);
    }

    // 2. Start Flash-Next on spark2
    const startFlash =
      `ssh -o BatchMode=yes -o ConnectTimeout=15 soverynspark2@10.10.11.2 ` +
      `'cd ${FLASH_DIR} && ./start.sh'`;
    if (!ssh(SPARK1, startFlash, 300000)) {
      console.log('  retry via spark2 host alias…');
      if (!ssh(SPARK2, `cd ${FLASH_DIR} && ./start.sh`, 300000)) {
        console.error('FAILED to start Flash-Next on spark2.');
        process.exit(3);
      }
    }

    // 3. Tunnel on tower
    console.log('  $ systemctl --user start soveryn-spark2-flashnext-8888.service');
    const tun = run('systemctl', ['--user', 'start', 'soveryn-spark2-flashnext-8888.service'], {
      timeoutMs: 30000,
    });
    if (!tun.ok) {
      console.error(`tunnel start failed: ${tun.stderr || tun.stdout || tun.status}`);
    }
  } else {
    console.log('Profile-only park: skipping SSH serve swap.');
  }

  const data = loadProfiles();
  const reason =
    `GLM :8001 parked — needs both Sparks; stops Flash-Next. ` +
    `Unpark: ${CMD} unpark glm --confirm (Lab EXL3 @ ${GLM_URL} / ${GLM_MODEL})`;
  markParked(data, GLM_ID, reason);

  // Always land on flash after park
  writeActiveId(FLASH_ID);
  const fresh = loadProfiles();
  const flash = getProfile(fresh, FLASH_ID);
  generatePiConfig(fresh, flash);
  console.log(`Active brain → ${FLASH_ID}`);
  console.log(banner(flash));

  if (!profileOnly) {
    const sw = run('bash', [SWITCH_BRAIN, 'flashnext'], { timeoutMs: 60000 });
    if (!sw.ok) {
      console.log(`Note: switch_kernel_brain.sh flashnext exited ${sw.status}`);
    }
  }

  console.log(`Parked ${GLM_ID}. Flash is default.`);
}

module.exports = {
  cmdPark,
  cmdUnpark,
  warnBanner,
  unparkStepsText,
  parkStepsText,
  parseParkFlags,
  GLM_ID,
  FLASH_ID,
  GLM_URL,
  GLM_MODEL,
};
