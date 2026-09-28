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

function ensurePiImageCap(piBin) {
  if (!piBin) return { ok: false, reason: 'no pi' };
  const file = providerPath(piBin);
  if (!fs.existsSync(file)) return { ok: false, reason: `missing ${file}` };
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

module.exports = { capOpenAiImages, ensurePiImageCap, providerPath, MARKER };
