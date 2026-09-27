/**
 * Kernel lattice memory (Pi). Default OFF; the soveryn + kernel launchers export KERNEL_LATTICE=1.
 * Flags: KERNEL_LATTICE=1 or KERNEL_MEMORY=1 or JIT_MEMORY=1
 * Loaded by:
 *   soveryn  -> packages/soveryn-cli/src/presets.js passes --extension (every pack)
 *   kernel   -> config/pi/extensions/kernel-lattice.ts (symlink to this file)
 *   bare pi  -> ~/.pi/agent/extensions symlink (-> ablit-bake overlay -> this file)
 * Dry: KERNEL_LATTICE=1 pi -e packages/soveryn-cli/extensions/kernel-lattice.ts
 * Does not write souls. Calls python -m soveryn.platform.lattice.kernel_memory
 *
 * Memory block: recalled once per session, cached, and appended to the system
 * prompt on EVERY turn (Pi resets to the base prompt each turn, so a one-shot
 * inject vanished after turn 1). A successful remember_fact or /remember marks
 * the cache stale, so a newly saved lesson shows up on the next turn.
 *
 * Correction nudge: when Jon's prompt reads like a correction, a hidden one-line
 * note asks the model to save or replace a kernel.lesson.* fact. It never writes.
 */
import { spawnSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

function enabled() {
  const v =
    process.env.KERNEL_LATTICE ||
    process.env.KERNEL_MEMORY ||
    process.env.JIT_MEMORY ||
    "0";
  return v === "1" || v === "true" || v === "TRUE";
}

const ROOT = process.env.SOVERYN_VNEXT || join(homedir(), "soveryn_vnext");
const PYTHON =
  process.env.SOVERYN_PYTHON ||
  join(homedir(), "miniconda3", "envs", "soveryn", "bin", "python");

const RECALL_CAP = "3000";
const MAX_FACT_CHARS = 400;
const MAX_RECALL_RETRIES = 3;
const TOPIC_OK = /^[a-z0-9][a-z0-9._:-]{1,95}$/;

export const LESSON_NUDGE_TYPE = "kernel-lattice-lesson-nudge";
export const LESSON_NUDGE =
  "[LESSON NUDGE] Jon's last message reads like a correction. After you fix it, record the rule so it sticks: " +
  "memory_search first (query 'kernel.lesson' or keywords) and read the topic fields, then remember_fact with " +
  "topic 'kernel.lesson.<short-slug>' and a one-line rule (<=400 chars). Reuse an existing topic EXACTLY to replace " +
  "the old lesson. If it was not really a correction, ignore this. Nothing has been saved automatically.";

// Start-of-message correction openers ("no, ...", "stop", "actually", "don't ...").
const CORRECTION_START =
  /^\s*(?:no\b|nope\b|nah\b|wrong\b|stop\b|actually\b|don'?t\b|dont\b|do not\b|never\b|not (?:that|this|what|like that)\b|why (?:did|are|would) you\b)/i;
// Correction phrasing anywhere in the (head of the) message.
const CORRECTION_ANY =
  /(?:\bthat'?s (?:wrong|not (?:right|it|what))|\bthat is (?:wrong|not (?:right|it|what))|\bi told you\b|\bi (?:already )?said\b|\bi asked you not\b|\byou(?: were|'re| are) wrong\b|\byou keep\b|\bnot what i (?:asked|said|meant|wanted)\b|\bhow many times\b|\bstop doing\b)/i;

export function looksLikeCorrection(text: unknown): boolean {
  const s = String(text ?? "").trim();
  if (!s || s.startsWith("/")) return false;
  const head = s.slice(0, 600);
  return CORRECTION_START.test(head) || CORRECTION_ANY.test(head);
}

export function withMemory(base: string, memory: string): string {
  return memory ? `${base}\n\n${memory}` : base;
}

export function normalizeTopic(raw: unknown): string {
  let t = String(raw ?? "").trim().toLowerCase();
  if (t.startsWith("entity:")) t = t.slice("entity:".length);
  return t.trim();
}

function run(args: string[]): { ok: boolean; raw: string } {
  const r = spawnSync(PYTHON, ["-m", "soveryn.platform.lattice.kernel_memory", ...args], {
    encoding: "utf8",
    cwd: ROOT,
    env: { ...process.env, PYTHONPATH: ROOT },
    timeout: 20000,
  });
  const raw = ((r.stdout || "") + (r.stderr || "")).trim();
  return { ok: r.status === 0, raw };
}

function textResult(text: string) {
  return { content: [{ type: "text" as const, text: text || "(empty)" }], details: {} };
}

export default function (pi: ExtensionAPI) {
  if (!enabled()) return;

  // ---- per-session memory cache (B) ----
  let cached = "";
  let stale = true;
  let failures = 0;

  function recallText(): string | null {
    const { ok, raw } = run(["recall", "--cap", RECALL_CAP]);
    if (!ok) return null;
    try {
      return String(JSON.parse(raw).text || "");
    } catch {
      return null;
    }
  }

  function memoryBlock(): string {
    if (stale) {
      const fresh = recallText();
      if (fresh !== null) {
        cached = fresh;
        stale = false;
        failures = 0;
      } else if (++failures >= MAX_RECALL_RETRIES) {
        stale = false; // stop re-spawning every turn; keep last good cache
      }
    }
    return cached;
  }

  function markStale() {
    stale = true;
    failures = 0;
  }

  function remember(topic: string, content: string): { ok: boolean; raw: string } {
    const r = run(["remember", "--content", content, "--entity", topic]);
    if (r.ok) markStale();
    return r;
  }

  pi.registerTool({
    name: "remember_fact",
    label: "Remember fact",
    description:
      "Save one durable house Lattice fact or lesson (<=400 chars). `topic` is REQUIRED. " +
      "BEFORE writing, call memory_search with the topic prefix or keywords (e.g. 'kernel.lesson') and read the returned `topic` fields. " +
      "If an existing topic covers the same rule, reuse that topic EXACTLY: the new fact supersedes the old one (old becomes history). " +
      "Only invent a new topic when nothing matches. Lessons from corrections/mistakes: kernel.lesson.<slug>; traps: kernel.gotcha.<slug>; " +
      "other facts: kernel.<area>.<slug>. Use when Jon corrects you, says remember / lock this, or at a decision point. " +
      "Never writes souls. Never store secrets.",
    parameters: Type.Object({
      topic: Type.String({
        description:
          "Required stable lowercase slug, e.g. kernel.lesson.git-push. Reuse an existing topic from memory_search to replace its fact.",
      }),
      content: Type.String({ description: "One claim, <=400 chars." }),
    }),
    async execute(_id, params) {
      const topic = normalizeTopic((params as any).topic);
      const content = String((params as any).content ?? "").trim();
      if (!topic) {
        throw new Error(
          "remember_fact: topic is required. Run memory_search first and reuse an existing topic, or use kernel.lesson.<slug> for a new lesson.",
        );
      }
      if (!TOPIC_OK.test(topic)) {
        throw new Error(
          `remember_fact: invalid topic "${topic}". Use a lowercase slug of [a-z0-9._:-], e.g. kernel.lesson.git-push.`,
        );
      }
      if (!content) throw new Error("remember_fact: content must be non-empty.");
      if (content.length > MAX_FACT_CHARS) {
        throw new Error(
          `remember_fact: content is ${content.length} chars; limit is ${MAX_FACT_CHARS}. Shorten to one claim and retry.`,
        );
      }
      const { ok, raw } = remember(topic, content);
      if (!ok) throw new Error(raw || "remember_fact failed");
      return textResult(raw);
    },
  });

  pi.registerTool({
    name: "memory_search",
    label: "Memory search",
    description:
      "Search current house Lattice facts by keywords OR by topic slug/prefix (e.g. 'kernel.lesson' lists current lessons). " +
      "Each hit shows its `topic`. Run this before remember_fact so you can reuse an existing topic.",
    parameters: Type.Object({
      query: Type.String({ description: "Keywords or a topic prefix like kernel.lesson" }),
    }),
    async execute(_id, params) {
      const { raw } = run(["search", "--query", String((params as any).query || "")]);
      return textResult(raw);
    },
  });

  pi.registerTool({
    name: "memory_get",
    label: "Memory get",
    description: "Read one Lattice node by id (jail: lattice ids only).",
    parameters: Type.Object({
      id: Type.String({ description: "Lattice node id" }),
    }),
    async execute(_id, params) {
      const { raw } = run(["get", "--id", String((params as any).id || "")]);
      return textResult(raw);
    },
  });

  pi.registerCommand("remember", {
    description: "Save one house fact: /remember <topic> <note>  (topic e.g. kernel.lesson.git-push)",
    handler: async (args, ctx) => {
      const s = String(args || "").trim();
      const m = s.match(/^(\S+)\s+([\s\S]+)$/);
      const topic = m ? normalizeTopic(m[1]) : "";
      if (!m || !TOPIC_OK.test(topic) || !topic.includes(".")) {
        ctx.ui.notify("Usage: /remember <topic> <note>   e.g. /remember kernel.lesson.git-push never force-push main", "error");
        return;
      }
      const note = m[2].trim();
      if (note.length > MAX_FACT_CHARS) {
        ctx.ui.notify(`Note is ${note.length} chars; limit is ${MAX_FACT_CHARS}.`, "error");
        return;
      }
      const { raw } = remember(topic, note);
      ctx.ui.notify(raw.slice(0, 200), "info");
    },
  });

  pi.registerCommand("flush", {
    description: "Ask Kernel to remember_fact this session's decisions (manual).",
    handler: async (_args, ctx) => {
      ctx.ui.notify(
        "Flush is manual: call remember_fact (with a topic) for each decision, open thread, and do-not-retry. No auto session-end write.",
        "info",
      );
    },
  });

  // Every turn: base prompt + cached memory block (B); correction -> hidden nudge (D).
  pi.on("before_agent_start", async (event) => {
    const mem = memoryBlock();
    const nudge = looksLikeCorrection(event.prompt);
    if (!mem && !nudge) return;
    const out: { systemPrompt?: string; message?: any } = {};
    if (mem) out.systemPrompt = withMemory(event.systemPrompt, mem);
    if (nudge) {
      // Sent as a message after the user turn (not in the system prompt) so the
      // prompt prefix stays byte-stable for the server's prefix cache.
      out.message = { customType: LESSON_NUDGE_TYPE, content: LESSON_NUDGE, display: false };
    }
    return out;
  });
}
