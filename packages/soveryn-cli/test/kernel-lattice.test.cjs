'use strict';
/**
 * kernel-lattice extension + pack wiring (2026-09-27).
 * Loads the real .ts through Pi's own extension loader (jiti + aliases) with a
 * fake python (SOVERYN_PYTHON) so no Lattice DB is touched.
 */
const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { pathToFileURL } = require('url');

const presets = require('../src/presets');

const EXT = path.resolve(__dirname, '..', 'extensions', 'kernel-lattice.ts');
const TMP_DIRS = [];
function tmpDir(prefix) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  TMP_DIRS.push(d);
  return d;
}
test.after(() => {
  for (const d of TMP_DIRS) fs.rmSync(d, { recursive: true, force: true });
});

function findPiLoader() {
  const r = spawnSync('bash', ['-lc', 'command -v pi'], { encoding: 'utf8' });
  const bin = (r.stdout || '').trim();
  if (!bin) return null;
  let real;
  try {
    real = fs.realpathSync(bin);
  } catch (_) {
    return null;
  }
  const loader = path.join(path.dirname(real), 'core', 'extensions', 'loader.js');
  return fs.existsSync(loader) ? loader : null;
}

const FAKE_PY = `#!/usr/bin/env node
const fs = require('fs');
const dir = process.env.FAKE_LATTICE_DIR;
const args = process.argv.slice(2); // -m soveryn.platform.lattice.kernel_memory <cmd> ...
const cmd = args[2];
fs.appendFileSync(dir + '/calls.log', cmd + '\\n');
const stateFile = dir + '/facts.json';
const facts = fs.existsSync(stateFile) ? JSON.parse(fs.readFileSync(stateFile, 'utf8')) : {};
const opt = (k) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : ''; };
if (cmd === 'recall') {
  const lines = Object.entries(facts).map(([t, c]) => '- [' + t + '] ' + c);
  const text = ['[HOUSE LATTICE]', '- seed fact', ...lines].join('\\n');
  process.stdout.write(JSON.stringify({ ok: true, text }) + '\\n');
} else if (cmd === 'remember') {
  facts[opt('--entity')] = opt('--content');
  fs.writeFileSync(stateFile, JSON.stringify(facts));
  process.stdout.write(JSON.stringify({ ok: true, lattice_id: 'fake' }) + '\\n');
} else {
  process.stdout.write(JSON.stringify({ ok: true, facts: [] }) + '\\n');
}
`;

function setupFake() {
  const dir = tmpDir('kl-test-');
  const py = path.join(dir, 'python');
  fs.writeFileSync(py, FAKE_PY, { mode: 0o755 });
  return { dir, py, calls: () => fs.readFileSync(path.join(dir, 'calls.log'), 'utf8').trim().split('\n').filter(Boolean) };
}

async function loadExt(env) {
  const loader = findPiLoader();
  const saved = {};
  for (const [k, v] of Object.entries(env)) {
    saved[k] = process.env[k];
    process.env[k] = v;
  }
  try {
    const { loadExtensions } = await import(pathToFileURL(loader).href);
    const res = await loadExtensions([EXT], process.cwd());
    assert.deepStrictEqual(res.errors, [], JSON.stringify(res.errors));
    return res.extensions[0];
  } finally {
    // SOVERYN_PYTHON is read at module load; KERNEL_LATTICE at factory time.
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

const skipNoPi = findPiLoader() ? false : 'pi not installed';

test('packs: every pack loads kernel-lattice and keeps lattice tools visible', () => {
  for (const id of ['minimal', 'standard', 'web']) {
    const pack = presets.materialize(presets.PACKS[id], { cfgDir: null });
    assert.ok(pack.extensions.includes(presets.LATTICE_EXTENSION), `${id} missing lattice ext`);
    if (pack.tools) {
      for (const t of presets.LATTICE_TOOLS) assert.ok(pack.tools.includes(t), `${id} hides ${t}`);
      const i = pack.piArgs.indexOf('--tools');
      assert.ok(pack.piArgs[i + 1].includes('remember_fact'));
    } else {
      assert.ok(!pack.piArgs.includes('--tools'), 'standard has no allowlist (all tools on)');
    }
  }
  const args = presets.packPiArgs(presets.getPack('web'), []);
  assert.ok(args.includes(presets.LATTICE_EXTENSION));
  assert.ok(args[args.indexOf('--tools') + 1].split(',').includes('memory_search'));
});

test('packs: skip explicit lattice ext when agent dir already discovers it (kernel)', () => {
  const dir = tmpDir('kl-cfg-');
  fs.mkdirSync(path.join(dir, 'extensions'));
  fs.symlinkSync(presets.LATTICE_EXTENSION, path.join(dir, 'extensions', 'kernel-lattice.ts'));
  const pack = presets.materialize(presets.PACKS.web, { cfgDir: dir });
  assert.ok(!pack.extensions.includes(presets.LATTICE_EXTENSION));
  assert.ok(pack.tools.includes('remember_fact'), 'tools still allowlisted');
});

test('extension: memory injected on EVERY turn, recalled once, refreshed after a write', { skip: skipNoPi }, async () => {
  const fake = setupFake();
  const ext = await loadExt({ KERNEL_LATTICE: '1', SOVERYN_PYTHON: fake.py, FAKE_LATTICE_DIR: fake.dir });
  process.env.FAKE_LATTICE_DIR = fake.dir;
  assert.deepStrictEqual([...ext.tools.keys()].sort(), ['memory_get', 'memory_search', 'remember_fact']);
  const [hook] = ext.handlers.get('before_agent_start');

  const t1 = await hook({ type: 'before_agent_start', prompt: 'build the page', systemPrompt: 'BASE' });
  const t2 = await hook({ type: 'before_agent_start', prompt: 'next step please', systemPrompt: 'BASE' });
  for (const t of [t1, t2]) {
    assert.ok(t.systemPrompt.startsWith('BASE\n\n[HOUSE LATTICE]'), t.systemPrompt);
    assert.strictEqual(t.message, undefined);
  }
  assert.deepStrictEqual(fake.calls(), ['recall'], 'one recall per session, cached after');

  const tool = ext.tools.get('remember_fact').definition;
  const res = await tool.execute('id1', { topic: 'kernel.lesson.test', content: 'Always run the tests' });
  assert.match(res.content[0].text, /"ok": ?true/);
  const t3 = await hook({ type: 'before_agent_start', prompt: 'go on', systemPrompt: 'BASE' });
  assert.ok(t3.systemPrompt.includes('[kernel.lesson.test] Always run the tests'), 'new lesson visible next turn');
  assert.deepStrictEqual(fake.calls(), ['recall', 'remember', 'recall']);
});

test('extension: remember_fact requires a topic and enforces the 400-char cap before spawning', { skip: skipNoPi }, async () => {
  const fake = setupFake();
  const ext = await loadExt({ KERNEL_LATTICE: '1', SOVERYN_PYTHON: fake.py, FAKE_LATTICE_DIR: fake.dir });
  process.env.FAKE_LATTICE_DIR = fake.dir;
  const tool = ext.tools.get('remember_fact').definition;
  assert.deepStrictEqual(tool.parameters.required.sort(), ['content', 'topic']);
  assert.match(tool.description, /memory_search/);
  assert.match(tool.description, /reuse that topic EXACTLY/);
  await assert.rejects(tool.execute('a', { topic: '', content: 'x' }), /topic is required/);
  await assert.rejects(tool.execute('b', { topic: 'Bad Topic!', content: 'x' }), /invalid topic/);
  await assert.rejects(tool.execute('c', { topic: 'kernel.lesson.x', content: 'y'.repeat(401) }), /401 chars; limit is 400/);
  assert.ok(!fs.existsSync(path.join(fake.dir, 'calls.log')), 'no python spawn on invalid input');
});

test('extension: correction prompt adds a hidden lesson nudge and never writes', { skip: skipNoPi }, async () => {
  const fake = setupFake();
  const ext = await loadExt({ KERNEL_LATTICE: '1', SOVERYN_PYTHON: fake.py, FAKE_LATTICE_DIR: fake.dir });
  process.env.FAKE_LATTICE_DIR = fake.dir;
  const [hook] = ext.handlers.get('before_agent_start');
  const corrections = [
    "no, that's the wrong file",
    "That's wrong. Use the GLM endpoint.",
    "don't touch config/pi",
    'I told you to use timeout 20s',
    'stop re-reading the whole tree',
    'Actually, it lives in packages/soveryn-cli',
  ];
  for (const prompt of corrections) {
    const r = await hook({ type: 'before_agent_start', prompt, systemPrompt: 'BASE' });
    assert.ok(r.message, `no nudge for: ${prompt}`);
    assert.strictEqual(r.message.display, false);
    assert.match(r.message.content, /kernel\.lesson\./);
    assert.match(r.message.content, /Nothing has been saved automatically/);
    assert.ok(r.systemPrompt.includes('[HOUSE LATTICE]'), 'memory still injected on correction turns');
  }
  for (const prompt of ['add a dark mode toggle', 'now run the tests', 'know any faster way?', '/remember x y']) {
    const r = await hook({ type: 'before_agent_start', prompt, systemPrompt: 'BASE' });
    assert.strictEqual(r.message, undefined, `false nudge for: ${prompt}`);
  }
  assert.ok(!fake.calls().includes('remember'), 'nudge must not write');
});

test('extension: flag off registers nothing', { skip: skipNoPi }, async () => {
  const ext = await loadExt({ KERNEL_LATTICE: '0', KERNEL_MEMORY: '0', JIT_MEMORY: '0' });
  assert.strictEqual(ext.tools.size, 0);
  assert.strictEqual((ext.handlers.get('before_agent_start') || []).length, 0);
});
