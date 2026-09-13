'use strict';

const fs = require('fs');
const {
  loadProfiles,
  listProfileIds,
  getProfile,
  readActiveId,
  writeActiveId,
  assertEnabled,
  generatePiConfig,
  banner,
  compactionWarnings,
} = require('./profiles');
const {
  CFG_DIR,
  PROFILES_PATH,
  ACTIVE_PROFILE_PATH,
  SIBLING_ACTIVE_PROFILE_PATH,
  IS_KERNEL,
  BRAND,
  CMD,
} = require('./paths');
const { probe } = require('./health');
const { pickProfile } = require('./picker');
const { findPi, piVersion, launchPi, hasSessionFlag, isPrintMode } = require('./launch');
const {
  runGates,
  formatGateReport,
  runSelfTest,
} = require('./policy/gates');
const { cmdPark, cmdUnpark } = require('./park');
const {
  listSessions,
  latestSession,
  matchSession,
  formatSessionLine,
  findLiveHarness,
  resumeModeFromEnv,
  decideSignInResume,
  sessionIsStale,
} = require('./sessions');
const {
  statusHud,
  colorMuted,
  colorBrand,
  profileRow,
  shortEndpoint,
} = require('./chrome');

function helpText() {
  if (IS_KERNEL) {
    return `Kernel — Pi coding agent brain switcher (Pi 0.74.2)

Usage:
  kernel                        Launch Pi TUI (new session; stale threads are not auto-resumed)
  kernel use <profile>          Set active brain (flash|glm|aetheria)
  kernel model|models           Interactive picker (fzf or numbered menu)
  kernel status                 Active brain, health, pi version
  kernel resume [id]            Reload last (or named) session transcript
  kernel sessions               List recent sessions (both harness dirs)
  kernel doctor                 Status + config paths + policy gates
  kernel park glm [--confirm]   Re-park GLM (owner-gated; restores Flash-Next)
  kernel unpark glm             Print Lab swap warning/steps (exit 2)
  kernel unpark glm --if-healthy  Enable if :8001 already serves glm-5.3-flash
  kernel unpark glm --confirm   Owner: stop Flash → start EXL3 → enable (or enable-only if healthy)
  soveryn-pi …                  Same as kernel (scripts/soveryn-pi)

Flags (launch):
  --flash                       Use flash brain for this run (persists active)
  --glm                         Use glm (REFUSES loudly if parked — never means flash)
  --aetheria | --qwen           Use aetheria brain for this run (persists active)
  --profile <id>                Use named profile for this run
  --pack|--preset minimal|standard|web   Tool pack (Pi --tools + extensions)
  --minimal / --standard / --web          Shorthand for --pack
  --showme                      Require screenshot/file:// evidence before visual-done claims
  --code-mode                   Append anti-roundtrip "code mode" spirit hint
  --high                        Thinking high this run (default is medium)
  --off|--build                 Thinking off this run
  (in TUI: Shift+Tab cycles thinking off / medium / high)
  --offline / --online          Pi startup net (default ONLINE)
  -c | --continue               Same as resume (house-wide, not cwd-only)
  --new|--fresh|--no-resume     Skip sign-in resume prompt; start a new session
  --                          Passthrough remaining args to pi

Examples:
  kernel use flash
  kernel use aetheria
  kernel model
  kernel resume                 # pick up last thread (any cwd)
  kernel resume 01a0898b
  kernel --flash --build
  kernel --qwen /path/to/repo
  kernel -p "mend X"
  kernel --glm                  # exits non-zero while parked
  kernel unpark glm --dry-run
  kernel park glm --dry-run

Config:  ${CFG_DIR}
Profiles SSOT: ${PROFILES_PATH}
Active:  ${ACTIVE_PROFILE_PATH}
Synced:  ${SIBLING_ACTIVE_PROFILE_PATH}
`;
  }
  return `SOVERYN CLI — branded coding harness (Pi 0.74.2)
Parallel to kernel/soveryn-pi; shares profiles SSOT.

Usage:
  soveryn                     Launch Pi TUI (new session; stale threads are not auto-resumed)
  soveryn code [args]         Same as soveryn (explicit)
  soveryn use <profile>       Set active profile (flash|glm|aetheria)
  soveryn model|models        Interactive picker (fzf or numbered menu)
  soveryn status              Active profile, health, pi version
  soveryn resume [id]         Reload last (or named) session transcript
  soveryn sessions            List recent sessions (soveryn-cli + kernel dirs)
  soveryn doctor              Status + config paths + policy gates
  soveryn doctor --gates      Policy gate status only (native controls)
  soveryn doctor --self-test  Unit self-test (assertExact must fail on mismatch)
  soveryn park glm [--confirm]   Re-park GLM (owner-gated; restores Flash-Next)
  soveryn unpark glm             Print Lab swap warning/steps (exit 2)
  soveryn unpark glm --if-healthy  Enable if :8001 already serves glm-5.3-flash
  soveryn unpark glm --confirm   Owner: stop Flash → start EXL3 → enable
  soveryn --help|-h|help      This help

Flags (launch / code):
  --flash                     Use flash profile for this run
  --glm                       Use glm (REFUSES loudly if parked — never means flash)
  --aetheria | --qwen         Use aetheria profile for this run
  --profile <id>              Use named profile for this run
  --pack|--preset minimal|standard|web  Tool pack (+ harness-controls always)
  --minimal / --standard / --web         Shorthand for --pack
  --showme                    Require screenshot/file:// before visual-done claims
  --code-mode                 Append anti-roundtrip "code mode" spirit hint
  --high                      Thinking high this run (default is medium)
  --off|--build               Thinking off this run
  (in TUI: Shift+Tab cycles thinking off / medium / high)
  -c | --continue             Same as resume (house-wide, not cwd-only)
  --new|--fresh|--no-resume   Skip sign-in resume prompt; start a new session
  --                        Passthrough remaining args to pi

Examples:
  soveryn use flash
  soveryn model
  soveryn resume              # pick up last thread (any cwd)
  soveryn resume 01a0898b --pack web --showme --code-mode
  soveryn --flash --build
  soveryn --minimal -p "fix one file"
  soveryn --code-mode --build
  soveryn code /path/to/repo
  soveryn -p "mend X"
  soveryn doctor --gates
  soveryn unpark glm --dry-run
  soveryn park glm --dry-run

Config:  ${CFG_DIR}
Profiles SSOT: ${PROFILES_PATH}
Active:  ${ACTIVE_PROFILE_PATH}
Policy:  packages/soveryn-cli/src/policy/  (see config/soveryn-cli/POLICY-GATES.md)
`;
}

function printHelp() {
  process.stdout.write(helpText());
}

function parseLaunchFlags(args) {
  const out = {
    profileOverride: null,
    thinkingOverride: null,
    presetOverride: null,
    packOverride: null,
    codeMode: false,
    showme: false,
    fresh: false,
    rest: [],
  };
  let i = 0;
  while (i < args.length) {
    const a = args[i];
    if (a === '--') {
      out.rest.push(...args.slice(i + 1));
      break;
    }
    if (a === '--flash') {
      out.profileOverride = 'flash';
    } else if (a === '--glm') {
      out.profileOverride = 'glm';
    } else if (a === '--aetheria' || a === '--qwen') {
      out.profileOverride = 'aetheria';
    } else if (a === '--profile') {
      i += 1;
      if (i >= args.length) throw new Error('--profile requires an id');
      out.profileOverride = args[i];
    } else if (a.startsWith('--profile=')) {
      out.profileOverride = a.slice('--profile='.length);
    } else if (a === '--pack' || a === '--preset') {
      i += 1;
      if (i >= args.length) throw new Error(`${a} requires minimal|standard|web`);
      out.packOverride = args[i];
      out.presetOverride = args[i];
    } else if (a.startsWith('--pack=')) {
      out.packOverride = a.slice('--pack='.length);
      out.presetOverride = out.packOverride;
    } else if (a.startsWith('--preset=')) {
      out.packOverride = a.slice('--preset='.length);
      out.presetOverride = out.packOverride;
    } else if (a === '--minimal') {
      out.packOverride = 'minimal';
      out.presetOverride = 'minimal';
    } else if (a === '--standard') {
      out.packOverride = 'standard';
      out.presetOverride = 'standard';
    } else if (a === '--web') {
      out.packOverride = 'web';
      out.presetOverride = 'web';
    } else if (a === '--showme') {
      out.showme = true;
    } else if (a === '--code-mode') {
      out.codeMode = true;
    } else if (a === '--medium') {
      out.thinkingOverride = 'medium';
    } else if (a === '--high') {
      out.thinkingOverride = 'high';
    } else if (a === '--thinking') {
      i += 1;
      if (i >= args.length) throw new Error('--thinking requires off|minimal|low|medium|high|xhigh');
      out.thinkingOverride = args[i];
    } else if (a.startsWith('--thinking=')) {
      out.thinkingOverride = a.slice('--thinking='.length);
    } else if (a === '--off' || a === '--build') {
      out.thinkingOverride = 'off';
    } else if (a === '--new' || a === '--fresh' || a === '--no-resume') {
      out.fresh = true;
    } else if (a === '--help' || a === '-h') {
      out.help = true;
    } else {
      out.rest.push(a);
    }
    i += 1;
  }
  return out;
}

/** Peel global launch flags so `soveryn --pack web status` still runs status. */
function peelGlobalFlags(argv) {
  const parsed = parseLaunchFlags(argv);
  return parsed;
}

async function cmdUse(id) {
  const data = loadProfiles();
  const profile = getProfile(data, id);
  assertEnabled(profile);
  writeActiveId(profile.id);
  generatePiConfig(data, profile);
  console.log(`${colorBrand('SOVERYN')} active brain → ${profile.id}`);
  console.log(banner(profile));
  console.log(`Wrote models.json/settings.json → ${CFG_DIR}`);
}

async function cmdModel() {
  const data = loadProfiles();
  const chosen = await pickProfile(data);
  if (!chosen) {
    console.error('Cancelled.');
    process.exit(1);
  }
  const profile = getProfile(data, chosen.id);
  try {
    assertEnabled(profile);
  } catch (e) {
    console.error(e.message);
    process.exit(2);
  }
  writeActiveId(profile.id);
  generatePiConfig(data, profile);
  console.log(`${colorBrand('SOVERYN')} active brain → ${profile.id}`);
  console.log(banner(profile));
}

function printGates(data, { exitOnFail = true } = {}) {
  const report = runGates(data);
  console.log(formatGateReport(report));
  if (exitOnFail && !report.ok) {
    process.exit(1);
  }
  return report;
}

function cmdSelfTest() {
  console.log(`${BRAND} doctor --self-test`);
  const st = runSelfTest();
  for (const s of st.steps) {
    console.log(`  ${s.ok ? 'PASS' : 'FAIL'}  ${s.name}${s.detail ? ` — ${s.detail}` : ''}`);
  }
  if (!st.ok) {
    console.log('  summary: SELF-TEST FAILED');
    process.exit(1);
  }
  console.log('  summary: SELF-TEST OK (mismatch correctly rejected)');
}

async function cmdStatus({ doctor = false, gatesOnly = false, selfTest = false } = {}) {
  if (selfTest) {
    cmdSelfTest();
    return;
  }

  const data = loadProfiles();

  if (gatesOnly) {
    printGates(data, { exitOnFail: true });
    return;
  }

  const activeId = readActiveId(data);
  const profile = getProfile(data, activeId);
  const piBin = findPi();
  const ver = piBin ? piVersion(piBin) : 'pi not found';

  const comp = profile.compaction || {};
  let compactLine;
  if (comp.enabled === false) {
    compactLine = 'off';
  } else {
    compactLine = `on  reserve=${comp.reserveTokens ?? '?'} keepRecent=${comp.keepRecentTokens ?? '?'}`;
  }
  console.log(
    statusHud(profile, {
      activeId,
      compactLine,
      piLine: `${ver}${piBin ? ` (${piBin})` : ''}`,
      profileFile: ACTIVE_PROFILE_PATH,
      syncedFile: SIBLING_ACTIVE_PROFILE_PATH,
    })
  );

  const cWarns = compactionWarnings(profile);
  for (const w of cWarns) {
    console.log(`  WARN:      ${w}`);
  }

  if (doctor) {
    console.log(`  config dir: ${CFG_DIR}`);
    console.log(`  profiles:   ${PROFILES_PATH}`);
    console.log(`  models.json:${fs.existsSync(`${CFG_DIR}/models.json`) ? ' present' : ' MISSING'}`);
    console.log(`  settings:   ${fs.existsSync(`${CFG_DIR}/settings.json`) ? ' present' : ' MISSING'}`);
    if (!IS_KERNEL) {
      console.log(`  note:       shares profiles SSOT with Kernel (config/soveryn-cli/profiles.json)`);
      console.log(`  failure modes: ${CFG_DIR}/NOTES-failure-modes.md`);
      console.log(`  policy gates: ${CFG_DIR}/POLICY-GATES.md`);
    } else {
      console.log(`  note:       Kernel harness — regenerates config/pi from shared profiles`);
    }
    if (cWarns.length === 0 && comp.enabled !== false) {
      console.log(`  compact ok: late trigger + large keep-recent (anti mid-loop amnesia)`);
    }
  }

  console.log(colorMuted('  profiles:'));
  const driftWarns = [];
  for (const id of listProfileIds(data)) {
    const p = data.profiles[id];
    if (p.enabled === false) {
      console.log(
        profileRow(id, activeId, 'PARKED', p.disabledReason || '')
      );
      // Drift check: parked profile whose serve is actually live.
      const h = await probe(p, 1500, { requireModel: true });
      if (h.ok) {
        driftWarns.push(
          `profile "${id}" is PARKED but ${shortEndpoint(p.baseUrl)} serves "${p.modelId}" — recorded state is stale.\n` +
          `               Fix: ${CMD} unpark ${id} --if-healthy   (or re-park the serve)`
        );
      }
    } else {
      const h = await probe(p, 1000);
      const detail = `${p.modelId} @ ${shortEndpoint(p.baseUrl)} (${h.detail})`;
      console.log(profileRow(id, activeId, h.ok ? 'OK' : 'DOWN', detail));
    }
  }
  for (const w of driftWarns) {
    console.log(`  DRIFT:     ${w}`);
  }

  if (doctor) {
    console.log('');
    if (driftWarns.length > 0) {
      process.exit(1);
    }
    const report = printGates(data, { exitOnFail: false });
    if (!report.ok) {
      process.exit(1);
    }
  }
}

function injectSession(parsed, picked) {
  const rest = (parsed.rest || []).filter((a) => a !== '--continue' && a !== '-c');
  const cwdArg =
    picked.cwd && fs.existsSync(picked.cwd) && fs.statSync(picked.cwd).isDirectory()
      ? picked.cwd
      : null;
  parsed.rest = [...(cwdArg ? [cwdArg] : []), '--session', picked.file, ...rest];
}

function readYn(question, defaultYes = true) {
  process.stderr.write(question);
  const buf = Buffer.alloc(80);
  let n = 0;
  try {
    n = fs.readSync(0, buf, 0, buf.length);
  } catch (_) {
    return defaultYes;
  }
  const ans = buf.slice(0, n).toString('utf8').trim().toLowerCase();
  if (!ans) return defaultYes;
  if (ans === 'y' || ans === 'yes') return true;
  if (ans === 'n' || ans === 'no' || ans === 'q') return false;
  return defaultYes;
}

function maybeSignInResume(parsed) {
  const decision = decideSignInResume({
    mode: resumeModeFromEnv(),
    isTty: !!(process.stdin.isTTY && process.stdout.isTTY),
    fresh: !!parsed.fresh,
    printMode: isPrintMode(parsed.rest),
    hasSession: hasSessionFlag(parsed.rest),
  });
  if (decision === 'skip') return;
  const picked = latestSession();
  if (!picked) return;
  const stale = sessionIsStale(picked);
  // Kill + soveryn must be a clean start. Resume is an explicit command.
  if (decision === 'ask' && stale) {
    console.error(
      `${CMD}: new session  (last ${picked.id.slice(0, 8)} is stale — ${CMD} resume to continue it)`,
    );
    return;
  }
  if (decision === 'ask') {
    process.stderr.write(`${CMD}: last session  ${formatSessionLine(picked)}\n`);
    const live = findLiveHarness().filter((p) => p.pid !== String(process.pid));
    for (const p of live) {
      console.error(
        `${CMD}: WARN — harness still running pid=${p.pid} ${p.tty || ''} — quit that TUI first`,
      );
    }
    const yes = readYn(`${CMD}: resume where you left off? [Y/n] `, true);
    if (!yes) {
      console.error(`${CMD}: new session`);
      return;
    }
  }
  console.error(`${CMD}: resume ${picked.id.slice(0, 8)}  cwd=${picked.cwd || '-'}  ${picked.harness}`);
  injectSession(parsed, picked);
}

function cmdCode(args) {
  const parsed = parseLaunchFlags(args);
  if (parsed.help) {
    printHelp();
    return;
  }
  maybeSignInResume(parsed);
  const data = loadProfiles();
  const activeId = parsed.profileOverride || readActiveId(data);
  let profile;
  try {
    profile = getProfile(data, activeId);
    assertEnabled(profile);
  } catch (e) {
    console.error(e.message);
    process.exit(e.code === 'PROFILE_PARKED' ? 2 : 1);
  }

  // Kernel: brain flags persist. soveryn-cli: one-shot unless `use`/`model`.
  if (parsed.profileOverride && IS_KERNEL) {
    writeActiveId(profile.id);
  }

  // Optional launch preflight: warn on gate FAIL (non-fatal unless SOVERYN_GATES_STRICT=1)
  try {
    const report = runGates(data);
    if (!report.ok) {
      console.error(formatGateReport(report));
      if (process.env.SOVERYN_GATES_STRICT === '1') {
        console.error(`${CMD}: REFUSED — policy gates failed (SOVERYN_GATES_STRICT=1)`);
        process.exit(1);
      }
      console.error(`${CMD}: WARN — policy gates failed; continuing (set SOVERYN_GATES_STRICT=1 to refuse)`);
    }
  } catch (e) {
    console.error(`${CMD}: WARN — gate preflight error: ${e.message}`);
  }

  if (parsed.showme) {
    process.env.SOVERYN_SHOWME = '1';
  }
  if (parsed.packOverride) {
    process.env.SOVERYN_PACK = String(parsed.packOverride);
  }

  launchPi({
    data,
    profile,
    thinking: parsed.thinkingOverride,
    passthroughArgs: parsed.rest,
    presetOverride: parsed.presetOverride,
    packOverride: parsed.packOverride || parsed.presetOverride,
    codeMode: !!parsed.codeMode,
    showme: !!parsed.showme,
  });
}

function isResumeCommand(cmd) {
  return (
    cmd === 'resume' ||
    cmd === 'continue' ||
    cmd === '--continue' ||
    cmd === '-c'
  );
}

function cmdSessionsList() {
  const rows = listSessions({ limit: 20 });
  if (!rows.length) {
    console.error(`${CMD}: no saved sessions under config/soveryn-cli/sessions or config/pi/sessions`);
    process.exit(1);
  }
  console.log(`${CMD} sessions (newest first):`);
  for (const s of rows) {
    console.log(`  ${formatSessionLine(s)}`);
  }
}

function cmdResume(cmdArgs, peeled) {
  const rest = [];
  let query = null;
  let listOnly = false;
  for (const a of cmdArgs || []) {
    if (a === '--list' || a === '-l' || a === 'list') {
      listOnly = true;
    } else if (a === '--help' || a === '-h') {
      printHelp();
      return;
    } else if (!query && !String(a).startsWith('-')) {
      query = a;
    } else {
      rest.push(a);
    }
  }
  if (listOnly) {
    cmdSessionsList();
    return;
  }

  const sessions = listSessions({ limit: 0 });
  const picked = matchSession(query, sessions);
  if (!picked) {
    console.error(
      query
        ? `${CMD}: no session matching ${query}`
        : `${CMD}: no saved sessions to resume`,
    );
    process.exit(1);
  }

  const live = findLiveHarness().filter((p) => p.pid !== String(process.pid));
  if (live.length) {
    for (const p of live) {
      console.error(
        `${CMD}: WARN — harness still running pid=${p.pid} ${p.tty || ''} — quit that TUI first or two processes will write the jsonl`,
      );
    }
  }

  const cwdArg =
    picked.cwd && fs.existsSync(picked.cwd) && fs.statSync(picked.cwd).isDirectory()
      ? picked.cwd
      : null;
  console.error(
    `${CMD}: resume ${picked.id.slice(0, 8)}  cwd=${picked.cwd || '-'}  ${picked.harness}  ${picked.file}`,
  );

  const launchArgs = [
    ...packFlagsFromParsed(peeled),
    ...(cwdArg ? [cwdArg] : []),
    '--session',
    picked.file,
    ...rest,
  ];
  cmdCode(launchArgs);
}

function parseDoctorArgs(args) {
  const out = { doctor: true, gatesOnly: false, selfTest: false };
  for (const a of args) {
    if (a === '--gates' || a === 'gates') out.gatesOnly = true;
    else if (a === '--self-test' || a === 'self-test') out.selfTest = true;
    else if (a === '--help' || a === '-h') out.help = true;
  }
  return out;
}

async function main(argv) {
  try {
    if (argv.length === 0) {
      cmdCode([]);
      return;
    }

    // Allow `soveryn --pack web status` / `soveryn --showme doctor`
    const peeled = peelGlobalFlags(argv);
    if (peeled.showme) process.env.SOVERYN_SHOWME = '1';
    if (peeled.packOverride) process.env.SOVERYN_PACK = String(peeled.packOverride);

    const cmd = peeled.rest[0];
    const cmdArgs = peeled.rest.slice(1);

    if (peeled.help && !cmd) {
      printHelp();
      return;
    }
    if (cmd === 'help' || cmd === '--help' || cmd === '-h') {
      printHelp();
      return;
    }
    if (cmd === 'use') {
      if (!cmdArgs[0]) {
        console.error(`Usage: ${CMD} use <flash|glm|aetheria>`);
        process.exit(1);
      }
      await cmdUse(cmdArgs[0]);
      return;
    }
    if (cmd === 'model' || cmd === 'models') {
      await cmdModel();
      return;
    }
    if (cmd === 'status') {
      await cmdStatus({ doctor: false });
      return;
    }
    if (cmd === 'sessions' || cmd === 'session') {
      cmdSessionsList();
      return;
    }
    if (isResumeCommand(cmd)) {
      cmdResume(cmdArgs, peeled);
      return;
    }
    if (cmd === 'new' || cmd === 'fresh') {
      cmdCode(['--new', ...packFlagsFromParsed(peeled), ...cmdArgs]);
      return;
    }
    if (cmd === 'doctor') {
      const d = parseDoctorArgs(cmdArgs);
      if (d.help) {
        printHelp();
        return;
      }
      await cmdStatus(d);
      return;
    }
    if (cmd === 'park') {
      if (!cmdArgs[0]) {
        console.error(`Usage: ${CMD} park glm [--confirm|--dry-run|--profile-only]`);
        process.exit(1);
      }
      await cmdPark(cmdArgs[0], cmdArgs.slice(1));
      return;
    }
    if (cmd === 'unpark') {
      if (!cmdArgs[0]) {
        console.error(`Usage: ${CMD} unpark glm [--confirm|--if-healthy|--dry-run]`);
        process.exit(1);
      }
      await cmdUnpark(cmdArgs[0], cmdArgs.slice(1));
      return;
    }
    if (cmd === 'code') {
      // Re-parse remaining with flags already applied via env; also allow flags after code
      cmdCode([...packFlagsFromParsed(peeled), ...cmdArgs]);
      return;
    }

    // Flags-first launch: kernel --flash, soveryn --help, kernel /path
    cmdCode(argv);
  } catch (e) {
    console.error(e.message || e);
    process.exit(e.code === 'PROFILE_PARKED' ? 2 : 1);
  }
}

function packFlagsFromParsed(parsed) {
  const out = [];
  if (parsed.packOverride) out.push('--pack', parsed.packOverride);
  if (parsed.showme) out.push('--showme');
  if (parsed.codeMode) out.push('--code-mode');
  if (parsed.thinkingOverride === 'medium') out.push('--medium');
  if (parsed.thinkingOverride === 'high') out.push('--high');
  if (parsed.thinkingOverride === 'off') out.push('--off');
  if (
    parsed.thinkingOverride &&
    !['medium', 'high', 'off'].includes(parsed.thinkingOverride)
  ) {
    out.push('--thinking', parsed.thinkingOverride);
  }
  if (parsed.profileOverride) out.push('--profile', parsed.profileOverride);
  if (parsed.fresh) out.push('--new');
  return out;
}

module.exports = { main };

if (require.main === module) {
  main(process.argv.slice(2));
}
