"use strict";
/**
 * flatten-mpo: iPhone "Photos" exports are MPO (picture + depth frame) and
 * providers reject multi-frame images. Detection walks JPEG APPn segments to an
 * APP2 "MPF\0" header, so a large Exif APP1 in front of it no longer hides it.
 *
 * Fixtures in test/fixtures are synthetic (make-mpo-fixture.py). Jon's real
 * photo is private and never committed: set SOVERYN_MPO_FIXTURE, or keep it at
 * ~/soveryn-private/fixtures/pondtestkernel-mpo-original.jpeg.
 */
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

// .mjs from CommonJS: dynamic import works on Node 20 and 22 alike.
const mod = import("../extensions/flatten-mpo.mjs");

const FIXTURES = path.join(__dirname, "fixtures");
const b64 = (file) => fs.readFileSync(file).toString("base64");
const SYNTH_MPO = b64(path.join(FIXTURES, "synthetic-mpo.jpg"));
const SYNTH_FLAT = b64(path.join(FIXTURES, "synthetic-flat.jpg"));

const PYTHON =
  process.env.SOVERYN_PYTHON || path.join(os.homedir(), "miniconda3", "envs", "soveryn", "bin", "python");
const havePillow = spawnSync(PYTHON, ["-c", "import PIL"], { encoding: "utf-8" }).status === 0;
const NO_PILLOW = `flatten needs Python + Pillow at ${PYTHON} (set SOVERYN_PYTHON)`;

const PRIVATE_DEFAULT = path.join(os.homedir(), "soveryn-private", "fixtures", "pondtestkernel-mpo-original.jpeg");
const PRIVATE = process.env.SOVERYN_MPO_FIXTURE || (fs.existsSync(PRIVATE_DEFAULT) ? PRIVATE_DEFAULT : "");
const NO_PRIVATE = "private iPhone MPO not present: set SOVERYN_MPO_FIXTURE to run it";

/** Count JPEG frames by SOI markers at top level (MPF index lists the rest). */
function frameCount(base64) {
  const buf = Buffer.from(base64, "base64");
  let n = 0;
  for (let i = 0; i + 2 < buf.length; i++) {
    if (buf[i] === 0xff && buf[i + 1] === 0xd8 && buf[i + 2] === 0xff) n++;
  }
  return n;
}

test("a plain jpeg prefix is not an MPO", async () => {
  const { looksLikeMpoJpeg } = await mod;
  const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10]);
  assert.equal(looksLikeMpoJpeg(jpeg.toString("base64")), false);
});

test("an Apple AMPF header in APP0 is still recognized", async () => {
  const { looksLikeMpoJpeg } = await mod;
  const app0 = Buffer.alloc(18, 0);
  app0.write("JFIF\0", 0, "latin1");
  app0.write("AMPF", 14, "latin1");
  const head = Buffer.concat([
    Buffer.from([0xff, 0xd8, 0xff, 0xe0, 0x00, app0.length + 2]),
    app0,
    Buffer.from([0xff, 0xda, 0x00, 0x02]),
  ]);
  assert.equal(looksLikeMpoJpeg(head.toString("base64")), true);
});

test("synthetic MPO: MPF APP2 behind a >2 KB Exif is detected", async () => {
  const { looksLikeMpoJpeg } = await mod;
  const raw = Buffer.from(SYNTH_MPO, "base64");
  assert.equal(raw.indexOf("AMPF"), -1, "fixture carries no Apple AMPF");
  assert.ok(raw.indexOf("MPF\0") > 2048, "MPF sits past the Exif");
  assert.equal(looksLikeMpoJpeg(SYNTH_MPO), true);
});

test("synthetic MPO flattens to one frame", { skip: !havePillow && NO_PILLOW }, async () => {
  const { looksLikeMpoJpeg, flattenMpoBase64, flattenMpoInMessages } = await mod;
  assert.equal(frameCount(SYNTH_MPO), 2);
  const flat = flattenMpoBase64(SYNTH_MPO);
  assert.notEqual(flat, SYNTH_MPO);
  assert.equal(looksLikeMpoJpeg(flat), false);
  assert.equal(frameCount(flat), 1);
  const messages = flattenMpoInMessages([
    { role: "user", content: "leave me" },
    { role: "toolResult", content: [{ type: "text", text: "Read image file" }, { type: "image", data: SYNTH_MPO, mimeType: "image/jpeg" }] },
  ]);
  assert.ok(messages);
  assert.equal(messages[0].content, "leave me");
  assert.equal(messages[1].content[1].data, flat);
  assert.equal(messages[1].content[1].mimeType, "image/jpeg");
  assert.equal(flattenMpoInMessages(messages), undefined);
});

test("an already-flattened single frame is left alone", async () => {
  const { looksLikeMpoJpeg, flattenMpoBase64, flattenMpoInMessages } = await mod;
  assert.equal(frameCount(SYNTH_FLAT), 1);
  assert.equal(looksLikeMpoJpeg(SYNTH_FLAT), false);
  assert.equal(flattenMpoBase64(SYNTH_FLAT), SYNTH_FLAT);
  assert.equal(
    flattenMpoInMessages([{ role: "toolResult", content: [{ type: "image", data: SYNTH_FLAT, mimeType: "image/jpeg" }] }]),
    undefined,
  );
});

test("Jon's iPhone MPO (private, opt-in) is detected and flattened", { skip: !PRIVATE ? NO_PRIVATE : !havePillow && NO_PILLOW }, async () => {
  const { looksLikeMpoJpeg, flattenMpoBase64 } = await mod;
  const data = b64(PRIVATE);
  assert.equal(looksLikeMpoJpeg(data), true);
  const flat = flattenMpoBase64(data);
  assert.notEqual(flat, data);
  assert.equal(looksLikeMpoJpeg(flat), false);
});
