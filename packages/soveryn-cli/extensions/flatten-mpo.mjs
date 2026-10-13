/**
 * iPhone Photos exports a .jpeg that is really an MPO: the picture, then a
 * second grayscale depth map. Providers reject that with
 * "animated and multipage images are unsupported; send a single frame".
 * The rejection kills the whole turn, and the bytes stay in the session, so
 * a restart resends the same file and fails again. Flatten to the first frame
 * before the request.
 */
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

const PYTHON =
  process.env.SOVERYN_PYTHON ||
  join(homedir(), "miniconda3", "envs", "soveryn", "bin", "python");

const FLATTEN_PY = `
import sys, base64
from io import BytesIO
from PIL import Image
raw = base64.b64decode(sys.stdin.read())
im = Image.open(BytesIO(raw))
im.seek(0)
out = BytesIO()
im.convert("RGB").save(out, "JPEG", quality=90)
sys.stdout.write(base64.b64encode(out.getvalue()).decode("ascii"))
`;

const cache = new Map();

const MPF_ID = Buffer.from("MPF\0", "latin1");
const AMPF_ID = Buffer.from("AMPF", "latin1");

// Decode only as much base64 as the header walk needs. Exif alone can be tens
// of KB, so grow the window instead of guessing a fixed prefix.
function headBytes(data, bytes) {
  const chars = Math.min(data.length, Math.ceil(bytes / 3) * 4);
  return Buffer.from(data.slice(0, chars - (chars % 4)), "base64");
}

/**
 * Walk the JPEG marker segments from SOI to SOS and report whether any APP2
 * segment carries the CIPA multi-picture header "MPF\0". Apple also writes
 * "AMPF" into APP0 on these exports; treat that as a signal too. A plain
 * single-frame JPEG (JFIF/Exif only) returns false.
 */
export function looksLikeMpoJpeg(data) {
  if (typeof data !== "string" || !data.startsWith("/9j/") || data.length < 8) return false;
  let want = 4096;
  for (;;) {
    let buf;
    try {
      buf = headBytes(data, want);
    } catch {
      return false;
    }
    const verdict = scanSegments(buf);
    if (verdict !== null) return verdict;
    // Ran off the decoded window before SOS; widen it unless we already have it all.
    if (Math.ceil(want / 3) * 4 >= data.length) return false;
    want *= 4;
  }
}

/** true/false when decided, null when more bytes are needed. */
function scanSegments(buf) {
  if (buf.length < 4 || buf[0] !== 0xff || buf[1] !== 0xd8) return false;
  let i = 2;
  while (true) {
    if (i + 4 > buf.length) return null;
    if (buf[i] !== 0xff) return false; // not a marker: corrupt or not a JPEG header
    const marker = buf[i + 1];
    if (marker === 0xff) {
      i += 1; // fill byte
      continue;
    }
    if (marker === 0xda || marker === 0xd9) return false; // SOS/EOI: header done, no MPF
    if (marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) {
      i += 2; // standalone markers carry no length
      continue;
    }
    const len = buf.readUInt16BE(i + 2);
    if (len < 2) return false;
    const start = i + 4;
    const end = i + 2 + len;
    if (marker >= 0xe0 && marker <= 0xef) {
      const id = Math.min(end, start + 4);
      if (id > buf.length) return null;
      if (marker === 0xe2 && buf.subarray(start, id).equals(MPF_ID)) return true;
      if (end > buf.length) return null;
      if (buf.subarray(start, end).includes(AMPF_ID)) return true;
    }
    i = end;
  }
}

export function flattenMpoBase64(data) {
  if (!looksLikeMpoJpeg(data)) return data;
  const key = `${data.length}:${data.slice(0, 48)}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const r = spawnSync(PYTHON, ["-c", FLATTEN_PY], {
    input: data,
    encoding: "utf-8",
    maxBuffer: 20 * 1024 * 1024,
  });
  const flat = (r.stdout || "").trim();
  if (r.status !== 0 || !flat.startsWith("/9j/") || looksLikeMpoJpeg(flat)) return data;
  cache.set(key, flat);
  return flat;
}

export function flattenMpoInMessages(messages) {
  if (!Array.isArray(messages)) return undefined;
  let changed = false;
  const next = messages.map((msg) => {
    const content = msg && msg.content;
    if (!Array.isArray(content)) return msg;
    let copied = content;
    for (let i = 0; i < content.length; i++) {
      const block = content[i];
      if (!block || block.type !== "image" || typeof block.data !== "string") continue;
      const flat = flattenMpoBase64(block.data);
      if (flat === block.data) continue;
      if (copied === content) copied = content.slice();
      copied[i] = { ...block, data: flat, mimeType: "image/jpeg" };
      changed = true;
    }
    return copied === content ? msg : { ...msg, content: copied };
  });
  return changed ? next : undefined;
}
