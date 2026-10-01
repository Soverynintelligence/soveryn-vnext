#!/usr/bin/env node
/**
 * html-module-host — Exit A scaffold: ES-module host HTML (no bundler).
 * Writes/serves an HTML that loads modules via <script type="module">.
 *
 * Usage:
 *   node html-module-host.mjs [--dir DIR] [--out host.html] [--modules a.mjs,b.mjs]
 *   node html-module-host.mjs --serve [--port 8765]
 *   node html-module-host.mjs --check   # print plan only
 *
 * Default modules (cathedral Exit A): core.mjs,kit.mjs,world.mjs,render.mjs
 */
import { createServer } from 'node:http';
import {
  readFileSync,
  writeFileSync,
  existsSync,
  statSync,
  mkdirSync,
  mkdtempSync,
  rmSync,
} from 'node:fs';
import { resolve, join, extname, relative, isAbsolute, sep } from 'node:path';
import { tmpdir } from 'node:os';

const DEFAULT_MODULES = ['core.mjs', 'kit.mjs', 'world.mjs', 'render.mjs'];

function parseArgs(argv) {
  const out = {
    dir: process.cwd(),
    outName: 'host.html',
    modules: null,
    serve: false,
    port: 8765,
    check: false,
    selfTest: false,
    title: 'SOVERYN Exit A host',
    canvasId: 'gl',
    help: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--serve') out.serve = true;
    else if (a === '--check') out.check = true;
    else if (a === '--self-test') out.selfTest = true;
    else if (a === '--dir') out.dir = resolve(argv[++i]);
    else if (a.startsWith('--dir=')) out.dir = resolve(a.slice(6));
    else if (a === '--out') out.outName = argv[++i];
    else if (a.startsWith('--out=')) out.outName = a.slice(6);
    else if (a === '--modules') out.modules = argv[++i].split(',').map((s) => s.trim()).filter(Boolean);
    else if (a.startsWith('--modules=')) out.modules = a.slice(10).split(',').map((s) => s.trim()).filter(Boolean);
    else if (a === '--port') out.port = Number(argv[++i]);
    else if (a.startsWith('--port=')) out.port = Number(a.slice(7));
    else if (a === '--title') out.title = argv[++i];
    else throw new Error(`unknown arg: ${a}`);
  }
  if (!out.modules) {
    // Prefer defaults that exist; else any *.mjs at top level (cap 8)
    const existing = DEFAULT_MODULES.filter((m) => existsSync(join(out.dir, m)));
    if (existing.length) out.modules = existing;
    else out.modules = [...DEFAULT_MODULES];
  }
  return out;
}

/** Structural containment — prefix startsWith is not containment (root vs root-backup). */
function isInsideRoot(root, file) {
  const rootAbs = resolve(root);
  const fileAbs = resolve(file);
  const rel = relative(rootAbs, fileAbs);
  if (!rel) return false;
  if (isAbsolute(rel)) return false;
  if (rel === '..' || rel.startsWith(`..${sep}`)) return false;
  return true;
}

function resolveHostFile(root, rawUrl) {
  let urlPath = String(rawUrl || '/').split('?')[0];
  try {
    urlPath = decodeURIComponent(urlPath);
  } catch {
    return null;
  }
  if (urlPath.includes('\0')) return null;
  const file = resolve(root, `.${urlPath}`);
  if (!isInsideRoot(root, file)) return null;
  return file;
}

function runContainmentSelfTest() {
  const tmp = mkdtempSync(join(tmpdir(), 'soveryn-host-'));
  const root = join(tmp, 'root');
  const sibling = join(tmp, 'root-backup');
  try {
    mkdirSync(root);
    mkdirSync(sibling);
    writeFileSync(join(root, 'ok.txt'), 'ok\n');
    writeFileSync(join(sibling, 'secret.txt'), 'TOP-SECRET-IN-SIBLING\n');

    const leakUrl = '/%2e%2e/root-backup/secret.txt';
    const decoded = decodeURIComponent(leakUrl);
    const naive = resolve(root, `.${decoded}`);
    const naiveLeaks = naive.startsWith(root) && existsSync(naive);
    if (!naiveLeaks) {
      console.error('html-module-host --self-test: control failed — naive prefix did not leak');
      process.exit(2);
    }
    if (resolveHostFile(root, leakUrl)) {
      console.error('html-module-host --self-test: FAIL encoded .. still escapes --dir');
      process.exit(1);
    }
    if (resolveHostFile(root, '/../root-backup/secret.txt')) {
      console.error('html-module-host --self-test: FAIL plain .. still escapes --dir');
      process.exit(1);
    }
    const ok = resolveHostFile(root, '/ok.txt');
    if (!ok || !ok.endsWith(`${sep}ok.txt`) || !existsSync(ok)) {
      console.error('html-module-host --self-test: FAIL in-root ok.txt not resolved');
      process.exit(1);
    }
    console.log(
      JSON.stringify({
        ok: true,
        naivePrefixLeaks: true,
        encodedTraversalBlocked: true,
        plainTraversalBlocked: true,
        inRootServed: true,
      }),
    );
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

function mime(p) {
  switch (extname(p).toLowerCase()) {
    case '.html': return 'text/html; charset=utf-8';
    case '.js':
    case '.mjs': return 'text/javascript; charset=utf-8';
    case '.css': return 'text/css; charset=utf-8';
    case '.json': return 'application/json';
    case '.png': return 'image/png';
    case '.svg': return 'image/svg+xml';
    default: return 'application/octet-stream';
  }
}

function buildHtml({ title, canvasId, modules }) {
  const tags = modules
    .map((m) => `  <script type="module" src="./${m.replace(/^\.\//, '')}"></script>`)
    .join('\n');
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title.replace(/</g, '')}</title>
  <style>
    html, body { margin: 0; height: 100%; background: #0a0a0c; color: #e8e8e8; font: 14px/1.4 ui-monospace, monospace; }
    #wrap { min-height: 100%; display: grid; place-items: center; }
    canvas { image-rendering: pixelated; background: #000; }
    #meta { position: fixed; left: 8px; bottom: 8px; opacity: 0.55; font-size: 11px; }
  </style>
</head>
<body>
  <div id="wrap"><canvas id="${canvasId}" width="960" height="540"></canvas></div>
  <div id="meta">Exit A · ES modules · no bundler · ${modules.join(' → ')}</div>
  <!-- Load order: dependency-friendly sequence. Each file is type=module (real browser ESM). -->
${tags}
</body>
</html>
`;
}

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.help) {
    console.log(`Usage: html-module-host.mjs [--dir DIR] [--out host.html] [--modules a.mjs,b.mjs] [--serve] [--port N]
Exit A host: writes HTML that loads modules as <script type="module"> — no bundler APIs.`);
    process.exit(0);
  }
  if (opts.selfTest) {
    runContainmentSelfTest();
    process.exit(0);
  }

  const outPath = resolve(opts.dir, opts.outName);
  const missing = opts.modules.filter((m) => !existsSync(join(opts.dir, m)));
  const html = buildHtml(opts);

  const report = {
    ok: true,
    mode: 'exit-a-es-modules',
    bundler: false,
    dir: opts.dir,
    out: outPath,
    modules: opts.modules,
    missingModules: missing,
    serve: opts.serve,
  };

  if (opts.check) {
    console.log(JSON.stringify(report, null, 2));
    process.exit(0);
  }

  writeFileSync(outPath, html);
  report.wrote = true;
  report.bytes = Buffer.byteLength(html);

  if (!opts.serve) {
    console.log(JSON.stringify(report, null, 2));
    console.error(`html-module-host: wrote ${outPath}`);
    if (missing.length) {
      console.error(`html-module-host: WARN missing modules (create them): ${missing.join(', ')}`);
    }
    process.exit(0);
  }

  const root = opts.dir;
  const server = createServer((req, res) => {
    try {
      let urlPath = (req.url || '/').split('?')[0];
      if (urlPath === '/') urlPath = `/${opts.outName}`;
      const file = resolveHostFile(root, urlPath);
      if (!file) {
        res.writeHead(403); res.end('forbidden'); return;
      }
      if (!existsSync(file) || !statSync(file).isFile()) {
        res.writeHead(404); res.end('not found'); return;
      }
      const body = readFileSync(file);
      res.writeHead(200, {
        'content-type': mime(file),
        'cache-control': 'no-store',
        // ESM from file:// is awkward cross-origin; http host is the real path.
        'access-control-allow-origin': '*',
      });
      res.end(body);
    } catch (e) {
      res.writeHead(500); res.end(String(e && e.message || e));
    }
  });

  server.listen(opts.port, '127.0.0.1', () => {
    const url = `http://127.0.0.1:${opts.port}/${opts.outName}`;
    report.url = url;
    console.log(JSON.stringify(report, null, 2));
    console.error(`html-module-host: serving ${url}  (Ctrl+C to stop)`);
    console.error(`html-module-host: open with: open-html.mjs ${url}`);
  });
}

main();
