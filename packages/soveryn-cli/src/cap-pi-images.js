'use strict';

const fs = require('fs');
const path = require('path');

const MARKER = 'SOVERYN_IMAGE_CAP';
const LIMIT = 4;

// Keep the newest pictures. vLLM and the Grok image API both 400 a prompt
// that carries more than four: "At most 4 image(s) may be provided".
function capOpenAiImages(params, limit = LIMIT) {
  const locs = [];
  params.forEach((msg, i) => {
    if (!Array.isArray(msg.content)) return;
    msg.content.forEach((part, j) => {
      if (part && part.type === 'image_url') locs.push([i, j]);
    });
  });
  if (locs.length <= limit) return params;
  const drop = new Set(locs.slice(0, locs.length - limit).map(([i, j]) => `${i}:${j}`));
  const note = `[${locs.length - limit} earlier picture(s) left out. A turn can look at ${limit} pictures.]`;
  let noted = false;
  return params.map((msg, i) => {
    if (!Array.isArray(msg.content)) return msg;
    const content = [];
    let lost = false;
    msg.content.forEach((part, j) => {
      if (drop.has(`${i}:${j}`)) {
        lost = true;
        return;
      }
      content.push(part);
    });
    if (lost && !noted) {
      noted = true;
      if (content[0] && content[0].type === 'text') {
        content[0] = { ...content[0], text: `${note}\n\n${content[0].text || ''}` };
      } else {
        content.unshift({ type: 'text', text: note });
      }
    }
    return { ...msg, content };
  });
}

const INJECT = `
function capOpenAiImages(params, limit = ${LIMIT}) {
  // ${MARKER}
  const locs = [];
  params.forEach((msg, i) => {
    if (!Array.isArray(msg.content)) return;
    msg.content.forEach((part, j) => {
      if (part && part.type === 'image_url') locs.push([i, j]);
    });
  });
  if (locs.length <= limit) return params;
  const drop = new Set(locs.slice(0, locs.length - limit).map(([i, j]) => i + ':' + j));
  const note = '[' + (locs.length - limit) + ' earlier picture(s) left out. A turn can look at ' + limit + ' pictures.]';
  let noted = false;
  return params.map((msg, i) => {
    if (!Array.isArray(msg.content)) return msg;
    const content = [];
    let lost = false;
    msg.content.forEach((part, j) => {
      if (drop.has(i + ':' + j)) { lost = true; return; }
      content.push(part);
    });
    if (lost && !noted) {
      noted = true;
      if (content[0] && content[0].type === 'text') {
        content[0] = Object.assign({}, content[0], { text: note + '\\n\\n' + (content[0].text || '') });
      } else {
        content.unshift({ type: 'text', text: note });
      }
    }
    return Object.assign({}, msg, { content });
  });
}
`;

function providerPath(piBin) {
  const distDir = path.dirname(piBin);
  return path.join(
    distDir,
    '..',
    'node_modules',
    '@earendil-works',
    'pi-ai',
    'dist',
    'providers',
    'openai-completions.js',
  );
}

/**
 * Pi >=0.8x ships a bundled CLI (dist/bundle/cli.js) with pi-ai inlined into
 * minified chunks (0.87.1: openai-completions-OBX42CLD.js; 0.99.1:
 * openai-completions-XW2Q5HVC.js; 1.0.0: openai-completions-JXDDPZ23.js —
 * needle verified once in all three).
 * Locate the openai-completions chunk next to the bundle.
 */
function bundledProviderPath(piBin) {
  const bundleDir = path.dirname(piBin);
  const chunks = path.join(bundleDir, 'chunks');
  if (path.basename(bundleDir) !== 'bundle' || !fs.existsSync(chunks)) return null;
  const hits = fs
    .readdirSync(chunks)
    .filter((f) => /^openai-completions-[A-Za-z0-9_-]+\.js$/.test(f));
  return hits.length === 1 ? path.join(chunks, hits[0]) : null;
}

const BUNDLE_NEEDLE = '}return params}function convertTools(tools,compat){';

function ensurePiImageCap(piBin) {
  if (!piBin) return { ok: false, reason: 'no pi' };
  const file = providerPath(piBin);
  if (!fs.existsSync(file)) {
    const bundled = bundledProviderPath(piBin);
    if (!bundled) return { ok: false, reason: `missing ${file}` };
    const bsrc = fs.readFileSync(bundled, 'utf8');
    if (bsrc.includes(MARKER)) return { ok: true, already: true, file: bundled };
    if (bsrc.split(BUNDLE_NEEDLE).length !== 2) {
      return { ok: false, reason: 'bundled convertMessages shape changed', file: bundled };
    }
    const bnext = bsrc.replace(
      BUNDLE_NEEDLE,
      `}return capOpenAiImages(params)}\n${INJECT}\nfunction convertTools(tools,compat){`,
    );
    fs.writeFileSync(bundled, bnext);
    return { ok: true, patched: true, file: bundled };
  }
  const src = fs.readFileSync(file, 'utf8');
  if (src.includes(MARKER)) return { ok: true, already: true, file };
  const needle = '    return params;\n}\nfunction convertTools(';
  if (!src.includes(needle)) return { ok: false, reason: 'convertMessages shape changed', file };
  const next = src.replace(
    needle,
    `    return capOpenAiImages(params);\n}\n${INJECT}\nfunction convertTools(`,
  );
  fs.writeFileSync(file, next);
  return { ok: true, patched: true, file };
}

module.exports = { capOpenAiImages, ensurePiImageCap, providerPath, bundledProviderPath, MARKER, BUNDLE_NEEDLE };
