'use strict';
// revamp phase 1: resume paths must honour the single-writer lease.
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { acquireLease, otherLiveLeases, hasPiPickerFlag } = require('../src/lease-check');

const REPO = path.resolve(__dirname, '..', '..', '..');

function stat(pid) {
  const s = fs.readFileSync(`/proc/${pid}/stat`, 'utf8');
  return s.slice(s.lastIndexOf(')') + 1).trim().split(/\s+/)[19];
}

test('held by another live pid -> refused (exit 3)', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lease-'));
  fs.mkdirSync(path.join(root, '.leases'));
  const holder = process.ppid; // a live pid that is not us
  fs.writeFileSync(path.join(root, '.leases', 'abc123.json'),
    JSON.stringify({ session_id: 'abc123', owner: 'desk', pid: holder, pid_start: stat(holder) }));
  const r = acquireLease(REPO, path.join(root, 'x', '2026_abc123.jsonl'), { root });
  assert.strictEqual(r.ok, false);
  assert.strictEqual(r.code, 3);
  assert.strictEqual(otherLiveLeases(root).length, 1);
});

test('free session -> acquired', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lease-'));
  const r = acquireLease(REPO, 'free999', { root });
  assert.strictEqual(r.ok, true);
});

test('picker flag detection', () => {
  assert.ok(hasPiPickerFlag(['--resume']));
  assert.ok(hasPiPickerFlag(['x', '-r']));
  assert.ok(!hasPiPickerFlag(['resume']));
});
