'use strict';

const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const desk = require('../src/desk');

/* ---- parseCalendar ---- */

test('parseCalendar: dated items, skips Done section, skips prose', () => {
  const md = [
    '# House calendar',
    '- 2026-09-30 — ChatGPT Plus billing expected',
    '- 2027-03-11 - BAP insurance expires',
    'prose line without a date',
    '## Done',
    '- 2026-09-22 — finished thing',
  ].join('\n');
  const items = desk.parseCalendar(md);
  assert.strictEqual(items.length, 2);
  assert.strictEqual(items[0].date, '2026-09-26' === '' ? '' : '2026-09-30');
  assert.match(items[0].text, /ChatGPT Plus/);
  assert.match(items[1].text, /BAP insurance/);
});

test('parseCalendar: em-dash and hyphen separators both accepted', () => {
  const items = desk.parseCalendar('- 2026-10-01 — a\n- 2026-10-02 - b');
  assert.strictEqual(items.length, 2);
});

/* ---- upcoming ---- */

test('upcoming: window filter, overdue grace, sorted input', () => {
  const now = new Date('2026-09-28T12:00:00Z');
  const items = desk.parseCalendar(
    '- 2026-09-20 — too old (outside grace)\n- 2026-09-27 — overdue grace\n- 2026-09-30 — this week\n- 2026-12-25 — beyond window'
  );
  const up = desk.upcoming(items, now);
  const dates = up.map((i) => i.date);
  assert.deepStrictEqual(dates, ['2026-09-27', '2026-09-30']);
});

/* ---- truthChecks ---- */

test('truthChecks: fresh file with 6 sections passes', () => {
  const now = new Date('2026-09-28T12:00:00Z');
  const rows = [];
  for (let i = 0; i < 6; i++) rows.push(`## ${i} Section`);
  rows.push('| A | b | 2026-09-28 |');
  const t = desk.truthChecks(rows.join('\n'), now);
  assert.strictEqual(t.newestRowDate, '2026-09-28');
  assert.strictEqual(t.ageDays, 0);
  assert.strictEqual(t.stale, false);
  assert.strictEqual(t.sectionsOk, true);
});

test('truthChecks: stale date flagged, truncation caught, undated data row counted', () => {
  const now = new Date('2026-09-28T12:00:00Z');
  const md = '## 0 a\n## 1 b\n| A | 2026-09-10 |\n| B | port :8091 |';
  const t = desk.truthChecks(md, now);
  assert.strictEqual(t.ageDays, 18);
  assert.strictEqual(t.stale, true);
  assert.strictEqual(t.sectionsOk, false);
  assert.strictEqual(t.undatedRows, 1);
});

test('truthChecks: empty file is stale, not silently fresh', () => {
  const t = desk.truthChecks('', new Date('2026-09-28T12:00:00Z'));
  assert.strictEqual(t.stale, true);
  assert.strictEqual(t.newestRowDate, null);
});

/* ---- loops ---- */

test('loops: seed is idempotent, add/done round-trips', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'desk-test-'));
  const file = path.join(dir, 'loops.json');
  process.env.SOVERYN_DESK_LOOPS = file;
  // require a fresh module instance so LOOPS_PATH picks up env
  delete require.cache[require.resolve('../src/desk')];
  const d = require('../src/desk');

  const store = d.loadLoops();
  assert.strictEqual(d.seedLoops(store), 3);
  assert.strictEqual(d.seedLoops(store), 0); // idempotent

  d.addLoop(store, 'test-a', 'do the thing');
  const open = store.loops.filter((l) => l.status === 'open');
  assert.ok(open.some((l) => l.id === 'test-a'));

  const done = d.doneLoop(store, 'test-a');
  assert.strictEqual(done.status, 'done');
  assert.ok(done.doneDate);

  const persisted = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.ok(persisted.loops.some((l) => l.id === 'glm-54-flash'));
  delete process.env.SOVERYN_DESK_LOOPS;
});

/* ---- render ---- */

test('render: includes brain, loops, truth, overdue marker', () => {
  const out = desk.render(
    {
      brainLine: 'KERNEL DESK · test · brain: glm OK',
      calendar: desk.parseCalendar('- 2026-09-26 — overdue thing\n- 2026-10-05 — future thing'),
      truth: { newestRowDate: '2026-09-28', ageDays: 0, stale: false, sectionCount: 6, sectionsOk: true, undatedRows: 0 },
      loops: [{ id: 'a', title: 'loop a', status: 'open' }],
    },
    new Date('2026-09-28T16:00:00Z')
  );
  assert.match(out, /brain: glm OK/);
  assert.match(out, /loop a/);
  assert.match(out, /fresh/);
  assert.match(out, /! 2026-09-26/);
  assert.match(out, /2026-10-05/);
});
