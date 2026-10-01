'use strict';

/**
 * kernel desk — Kernel's briefing pane.
 *
 * Externalizes Kernel's state so every session boots briefed instead of
 * reconstructing it by hand:
 *   - brief:  clock, active brain health, pi version
 *   - today:  dated items from docs/ops/HOUSE-CALENDAR.md (45-day window)
 *   - loops:  open "do X when Y" commitments (data/desk/loops.json)
 *   - truth:  docs/CURRENT_TRUTH.md machine checks (staleness + shape)
 *
 * Conversation stays in Pi. The desk is the part that does not forget.
 */

const fs = require('fs');
const path = require('path');
const { REPO } = require('./paths');

const LOOPS_PATH =
  process.env.SOVERYN_DESK_LOOPS ||
  path.join(REPO, 'data', 'desk', 'loops.json');
const CALENDAR_PATH = path.join(REPO, 'docs', 'ops', 'HOUSE-CALENDAR.md');
const TRUTH_PATH = path.join(REPO, 'docs', 'CURRENT_TRUTH.md');
const DESK_WINDOW_DAYS = 45;

/* ---------------- calendar ---------------- */

/** Parse dated items from the house calendar. Lines: `- YYYY-MM-DD — text` */
function parseCalendar(md) {
  const items = [];
  const lines = String(md || '').split('\n');
  const re = /^-\s(\d{4}-\d{2}-\d{2})\s+[—-]\s+(.+)$/;
  let section = '';
  for (const line of lines) {
    const h = line.match(/^#{1,3}\s+(.+?)\s*$/);
    if (h) section = h[1].toLowerCase();
    const m = line.match(re);
    if (!m) continue;
    if (section.startsWith('done')) continue; // "## Done" is history, not upcoming
    items.push({ date: m[1], text: m[2].trim(), done: section.startsWith('done') });
  }
  items.sort((a, b) => a.date.localeCompare(b.date));
  return items;
}

/** Upcoming (or overdue) calendar items inside the desk window. */
function upcoming(items, now = new Date(), windowDays = DESK_WINDOW_DAYS) {
  const today = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  const end = new Date(today.getTime() + windowDays * 86400000);
  return (items || []).filter((it) => {
    const d = new Date(`${it.date}T00:00:00Z`);
    if (Number.isNaN(d.getTime())) return false;
    return d >= new Date(today.getTime() - 3 * 86400000) && d <= end; // 3-day overdue grace
  });
}

/* ---------------- truth file checks ---------------- */

/** Machine checks from docs/CURRENT_TRUTH.md staleness rule. */
function truthChecks(md, now = new Date()) {
  const text = String(md || '');
  const rowDates = [];
  for (const line of text.split('\n')) {
    if (!line.startsWith('|')) continue;
    const dates = line.match(/\d{4}-\d{2}-\d{2}/g);
    if (dates) rowDates.push(...dates);
    else if (/\d/.test(line))
      rowDates.push(null); // data row (has digits, so not a header/separator) without a date
  }
  const dated = rowDates.filter(Boolean).sort();
  const newest = dated.length ? dated[dated.length - 1] : null;
  let ageDays = null;
  if (newest) {
    const d = new Date(`${newest}T00:00:00Z`);
    const today = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
    ageDays = Math.round((today - d) / 86400000);
  }
  const sections = (text.match(/^## \d/gm) || []).length;
  const undatedRows = rowDates.filter((d) => d === null).length;
  return {
    newestRowDate: newest,
    ageDays,
    stale: ageDays === null || ageDays > 7,
    sectionCount: sections,
    sectionsOk: sections === 6,
    undatedRows,
  };
}

/* ---------------- loops ---------------- */

function loadLoops() {
  try {
    const raw = JSON.parse(fs.readFileSync(LOOPS_PATH, 'utf8'));
    if (Array.isArray(raw.loops)) return raw;
  } catch (e) {
    /* first run */
  }
  return { loops: [] };
}

function saveLoops(store) {
  fs.mkdirSync(path.dirname(LOOPS_PATH), { recursive: true });
  fs.writeFileSync(LOOPS_PATH, `${JSON.stringify(store, null, 2)}\n`);
}

/** Seed the known open loops on first run; idempotent. */
function seedLoops(store) {
  const seed = [
    { id: 'glm-54-flash', title: 'Start Lab EXL3 sequence when GLM-5.4-Flash weights land (expected late Oct–Nov 2026)' },
    { id: 'osaia-longtail', title: 'Seed long-tail driver support policy ask inside OSAIA working groups' },
    { id: 'quadro-bake', title: 'Freeze-and-bake Quadro driver/kernel/CUDA stack when NVIDIA announces Turing EOL' },
  ];
  let added = 0;
  for (const s of seed) {
    if (!store.loops.some((l) => l.id === s.id)) {
      store.loops.push({ ...s, created: new Date().toISOString().slice(0, 10), status: 'open' });
      added += 1;
    }
  }
  if (added) saveLoops(store);
  return added;
}

function addLoop(store, id, title) {
  store.loops.push({
    id: id || `loop-${Date.now()}`,
    title,
    created: new Date().toISOString().slice(0, 10),
    status: 'open',
  });
  saveLoops(store);
}

function doneLoop(store, idOrIndex) {
  const loop =
    store.loops.find((l) => l.id === idOrIndex) ||
    store.loops[Number(idOrIndex) - 1];
  if (!loop) return null;
  loop.status = 'done';
  loop.doneDate = new Date().toISOString().slice(0, 10);
  saveLoops(store);
  return loop;
}

/* ---------------- render ---------------- */

function render({ brainLine, calendar, truth, loops }, now = new Date()) {
  const out = [];
  out.push(brainLine);
  out.push('');

  out.push('TODAY / UPCOMING (45d)');
  const up = upcoming(calendar, now);
  if (!up.length) out.push('  (nothing scheduled)');
  for (const it of up) {
    const pad = (n) => String(n).padStart(2, '0');
    const localToday = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const overdue = it.date < localToday;
    out.push(`  ${overdue ? '!' : ' '} ${it.date}  ${it.text}`);
  }
  out.push('');

  out.push('OPEN LOOPS (do X when Y)');
  const open = loops.filter((l) => l.status === 'open');
  if (!open.length) out.push('  (none)');
  open.forEach((l, i) => out.push(`  ${i + 1}. [${l.id}] ${l.title}`));
  out.push('');

  out.push('TRUTH FILE (docs/CURRENT_TRUTH.md)');
  out.push(
    `  newest row date: ${truth.newestRowDate} (${truth.ageDays}d old) ${truth.stale ? 'STALE — re-observe' : 'fresh'}`
  );
  out.push(
    `  sections: ${truth.sectionCount}/6 ${truth.sectionsOk ? 'ok' : 'TRUNCATED?'} · undated rows: ${truth.undatedRows}`
  );
  out.push('');
  out.push('actions: desk loop add <id> <title> · desk loop done <id|n> · desk --verify · desk --json');
  return out.join('\n');
}

module.exports = {
  parseCalendar,
  upcoming,
  truthChecks,
  loadLoops,
  saveLoops,
  seedLoops,
  addLoop,
  doneLoop,
  render,
  LOOPS_PATH,
  CALENDAR_PATH,
  TRUTH_PATH,
  DESK_WINDOW_DAYS,
};

/* ---------------- CLI entry ---------------- */

async function cmdDesk(cmdArgs = [], deps = {}) {
  const { loadProfiles, readActiveId, getProfile, listProfileIds } = deps.profiles;
  const { probeStable } = deps.health;

  if (cmdArgs.includes('--verify')) {
    const { spawnSync } = require('child_process');
    const script = path.join(REPO, 'scripts', 'verify.sh');
    if (!fs.existsSync(script)) {
      console.error(`no verify script at ${script}`);
      process.exit(1);
    }
    console.log('running scripts/verify.sh (bounded 10m)…');
    const r = spawnSync('bash', [script], { stdio: 'inherit', timeout: 600000 });
    process.exit(r.status || (r.signal ? 124 : 1));
  }

  const store = loadLoops();
  seedLoops(store);

  if (cmdArgs[0] === 'loop') {
    const sub = cmdArgs[1];
    if (sub === 'add') {
      const id = cmdArgs[2];
      const title = cmdArgs.slice(3).join(' ');
      if (!title) {
        console.error('Usage: desk loop add <id> <title>');
        process.exit(1);
      }
      addLoop(store, id, title);
      console.log(`loop added: [${id}] ${title}`);
      return;
    }
    if (sub === 'done') {
      const loop = doneLoop(store, cmdArgs[2]);
      if (!loop) {
        console.error(`no such loop: ${cmdArgs[2]}`);
        process.exit(1);
      }
      console.log(`loop done: [${loop.id}] ${loop.title}`);
      return;
    }
    console.error('Usage: desk loop add|done …');
    process.exit(1);
  }

  // header: active brain + live probe
  const data = loadProfiles();
  const activeId = readActiveId(data);
  const profile = getProfile(data, activeId);
  const h = await probeStable(profile, 1500, { requireModel: true, retries: 1 });
  const now = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  const localStamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}`;
  const brainLine = `KERNEL DESK · ${localStamp} · brain: ${activeId} ${h.ok ? 'OK' : `DOWN (${h.detail})`}`;

  const read = (p) => {
    try {
      return fs.readFileSync(p, 'utf8');
    } catch (e) {
      return '';
    }
  };
  const calendar = parseCalendar(read(CALENDAR_PATH));
  const truth = truthChecks(read(TRUTH_PATH));

  const json = cmdArgs.includes('--json');
  if (json) {
    console.log(
      JSON.stringify(
        { brain: { id: activeId, ok: h.ok, detail: h.detail }, calendar: upcoming(calendar), truth, loops: store.loops },
        null,
        2
      )
    );
    return;
  }
  console.log(render({ brainLine, calendar, truth, loops: store.loops }));
}

module.exports.cmdDesk = cmdDesk;
