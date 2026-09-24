/**
 * SOVERYN harness controls — backend enforcement (not SOVERYN.md lectures).
 *
 * G6_TOOL_EVIDENCE  — durable JSONL sidecar for every tool_result; warn on
 *                     done/fixed/pass claims without recent successful tools
 * Sink-gate         — append before compaction can eat context
 * Loop guard        — block 3rd identical failed tool call (tool_call hook)
 * --showme          — require screenshot / file:// / open-html artifact before
 *                     visual-done claims (SOVERYN_SHOWME=1)
 *
 * Loaded on every soveryn/kernel launch via --extension.
 */
import { appendFileSync, existsSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DEFAULT_LOOP_LIMIT = 3;
const MAX_LOOP_LIMIT = 32;

/** Invalid/NaN/Infinity/0/huge env must not silently disable the loop guard. */
function parseLoopLimit(raw: unknown, fallback = DEFAULT_LOOP_LIMIT): number {
	const s = raw == null ? "" : String(raw).trim();
	const n = s === "" ? fallback : Number(s);
	if (!Number.isInteger(n) || n < 1 || n > MAX_LOOP_LIMIT) return fallback;
	return n;
}

const LOOP_LIMIT = parseLoopLimit(process.env.SOVERYN_LOOP_GUARD);
const SHOWME = ["1", "true", "yes", "on"].includes(
	String(process.env.SOVERYN_SHOWME || "").trim().toLowerCase(),
);

const CLAIM_RE =
	/\b(done|fixed|passed|pass\b|verified|complete[d]?|shipped|works now|all green|visual(?:ly)? (?:ok|done|good|ready))\b/i;

type FailState = { count: number; lastSummary: string };

function stableStringify(value: unknown): string {
	if (value === null || typeof value !== "object") return JSON.stringify(value);
	if (Array.isArray(value)) return `[${value.map(stableStringify).join(",")}]`;
	const obj = value as Record<string, unknown>;
	const keys = Object.keys(obj).sort();
	return `{${keys.map((k) => `${JSON.stringify(k)}:${stableStringify(obj[k])}`).join(",")}}`;
}

function bashCommand(input: unknown): string {
	if (!input || typeof input !== "object") return "";
	const o = input as Record<string, unknown>;
	return String(o.command || o.cmd || o.script || "");
}

function isChromeBash(cmd: string): boolean {
	return (
		/\b(google-chrome(?:-stable)?|chromium(?:-browser)?|chrome)\b/i.test(cmd) ||
		/\bCHROME_BIN\b/.test(cmd)
	);
}

function chromeKind(cmd: string): string {
	if (/--dump-dom/i.test(cmd) || /\bdump-dom\b/i.test(cmd)) return "dump-dom";
	if (/--screenshot/i.test(cmd)) return "screenshot";
	if (/--print-to-pdf/i.test(cmd)) return "print-to-pdf";
	if (/--virtual-time-budget/i.test(cmd)) return "virtual-time";
	if (/\bRuntime\.evaluate\b|\b--eval\b/i.test(cmd)) return "eval";
	return "chrome";
}

function chromeTarget(cmd: string): string {
	const fileUrl = String(cmd).match(/file:\/\/[^\s'"]+/i);
	if (fileUrl) return fileUrl[0].replace(/^file:\/\//i, "");
	const html = String(cmd).match(/(?:^|[\s'"=])(\/?[^\s'"]+\.html)\b/i);
	if (html) return html[1];
	return "";
}

/** Chrome dump-dom / screenshot flag nits still collide on kind + target file. */
function fingerprint(toolName: string, input: unknown): string {
	let raw = `${toolName || ""}::${stableStringify(input || {})}`;
	if (String(toolName || "") === "bash") {
		const cmd = bashCommand(input);
		if (isChromeBash(cmd)) {
			raw = `bash::chrome::${chromeKind(cmd)}::${chromeTarget(cmd)}`;
		}
	}
	return createHash("sha256").update(raw).digest("hex").slice(0, 16);
}

/** stdout-shaped failures that still return tool isError=false (Chrome DT_FAIL). */
function looksLikeSoftFail(summary: string): boolean {
	const text = String(summary || "");
	if (!text) return false;
	return (
		/\bDT_FAIL\b/i.test(text) ||
		/\bDT_ERROR\b/i.test(text) ||
		/verdict\s*=\s*\S*FAIL/i.test(text) ||
		/\bTIMEOUT\b/i.test(text) ||
		/Traceback \(most recent call last\)/.test(text) ||
		/^Error:/m.test(text) ||
		/\b(?:TypeError|ReferenceError|SyntaxError|RangeError):\s/i.test(text)
	);
}

function summarizeContent(content: unknown): string {
	if (content == null) return "";
	if (typeof content === "string") return content.slice(0, 2000);
	if (Array.isArray(content)) {
		return content
			.map((c: any) => {
				if (!c) return "";
				if (typeof c === "string") return c;
				if (c.type === "text") return String(c.text || "");
				return JSON.stringify(c).slice(0, 400);
			})
			.join("\n")
			.slice(0, 2000);
	}
	try {
		return JSON.stringify(content).slice(0, 2000);
	} catch {
		return String(content).slice(0, 2000);
	}
}

function evidenceDir(cwd: string): string {
	return join(cwd, ".soveryn", "evidence");
}

function evidencePath(cwd: string): string {
	return join(evidenceDir(cwd), "tools.jsonl");
}

function appendEvidence(cwd: string, entry: Record<string, unknown>): string {
	const dir = evidenceDir(cwd);
	mkdirSync(dir, { recursive: true });
	const file = evidencePath(cwd);
	const row = { ts: new Date().toISOString(), ...entry };
	appendFileSync(file, `${JSON.stringify(row)}\n`, "utf8");
	writeFileSync(
		join(dir, "LATEST"),
		`${file}\n${row.ts}\t${entry.toolName || ""}\t${entry.isError ? "ERR" : "OK"}\n`,
		"utf8",
	);
	return file;
}

function readRecent(cwd: string, limit = 40): any[] {
	const file = evidencePath(cwd);
	if (!existsSync(file)) return [];
	const lines = readFileSync(file, "utf8").split("\n").filter(Boolean).slice(-limit);
	const out: any[] = [];
	for (const line of lines) {
		try {
			out.push(JSON.parse(line));
		} catch {
			/* skip */
		}
	}
	return out;
}

function recentSuccessCount(cwd: string, maxLookback = 24): number {
	return readRecent(cwd, maxLookback).filter((r) => !r.isError).length;
}

function hasShowmeArtifact(cwd: string): boolean {
	const rows = readRecent(cwd, 40);
	for (let i = rows.length - 1; i >= 0; i--) {
		const r = rows[i];
		if (r.isError) continue;
		const blob = `${r.summary || ""} ${stableStringify(r.details || {})} ${stableStringify(r.input || {})}`;
		if (
			r.toolName === "open-html" ||
			/\.png\b/i.test(blob) ||
			/screenshot/i.test(blob) ||
			/file:\/\//i.test(blob) ||
			/"screenshotExists"\s*:\s*true/.test(blob)
		) {
			return true;
		}
	}
	return false;
}

function assistantText(message: any): string {
	const content = message?.content;
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.map((c: any) => (c?.type === "text" ? String(c.text || "") : ""))
		.join("\n");
}

function withAnnotation(message: any, note: string): any {
	const content = message?.content;
	const suffix = `\n\n[${note}]`;
	if (typeof content === "string") {
		return { ...message, content: content + suffix };
	}
	if (Array.isArray(content)) {
		return {
			...message,
			content: [...content, { type: "text", text: suffix }],
		};
	}
	return {
		...message,
		content: [{ type: "text", text: suffix }],
	};
}

export default function soverynHarnessControls(pi: ExtensionAPI) {
	/** Consecutive identical failures by fingerprint */
	const failStreak = new Map<string, FailState>();
	/** Last fingerprint per toolCallId for result correlation */
	const callFp = new Map<string, { fp: string; toolName: string; input: unknown }>();

	pi.on("session_start", (_event, ctx) => {
		const file = evidencePath(ctx.cwd);
		mkdirSync(evidenceDir(ctx.cwd), { recursive: true });
		appendEvidence(ctx.cwd, {
			toolName: "_session",
			isError: false,
			event: "session_start",
			showme: SHOWME,
			loopLimit: LOOP_LIMIT,
			evidenceFile: file,
		});
		try {
			pi.appendEntry("soveryn-evidence", {
				evidenceFile: file,
				showme: SHOWME,
				at: new Date().toISOString(),
			});
		} catch {
			/* appendEntry optional on some modes */
		}
		if (SHOWME) {
			ctx.ui.notify("SOVERYN --showme ON: visual done needs screenshot/file:// evidence", "info");
		}
	});

	pi.on("tool_call", async (event) => {
		const fp = fingerprint(event.toolName, event.input);
		callFp.set(event.toolCallId, { fp, toolName: event.toolName, input: event.input });
		const streak = failStreak.get(fp);
		if (streak && streak.count >= LOOP_LIMIT) {
			return {
				block: true,
				reason:
					`SOVERYN loop-guard: ${LOOP_LIMIT} identical failed calls blocked ` +
					`(${event.toolName} fp=${fp}). Change args/approach or stop. ` +
					`Last error: ${streak.lastSummary.slice(0, 240)}`,
			};
		}
	});

	pi.on("tool_result", async (event, ctx) => {
		const meta = callFp.get(event.toolCallId) || {
			fp: fingerprint(event.toolName, event.input),
			toolName: event.toolName,
			input: event.input,
		};
		callFp.delete(event.toolCallId);

		const summary = summarizeContent(event.content);
		const softFail = !event.isError && looksLikeSoftFail(summary);
		const failed = !!event.isError || softFail;
		const file = appendEvidence(ctx.cwd, {
			toolName: event.toolName,
			toolCallId: event.toolCallId,
			isError: failed,
			osError: !!event.isError,
			softFail,
			fp: meta.fp,
			input: event.input,
			summary,
			details: event.details ?? null,
		});

		try {
			pi.appendEntry("soveryn-tool-evidence", {
				toolName: event.toolName,
				isError: failed,
				softFail,
				fp: meta.fp,
				evidenceFile: file,
				at: new Date().toISOString(),
			});
		} catch {
			/* ignore */
		}

		if (failed) {
			const prev = failStreak.get(meta.fp) || { count: 0, lastSummary: "" };
			prev.count += 1;
			prev.lastSummary = summary || (softFail ? "soft-fail" : "error");
			failStreak.set(meta.fp, prev);
		} else {
			failStreak.delete(meta.fp);
		}
	});

	// Flush pointer before compaction eats session context
	pi.on("session_before_compact", async (_event, ctx) => {
		const file = evidencePath(ctx.cwd);
		const rows = readRecent(ctx.cwd, 8);
		appendEvidence(ctx.cwd, {
			toolName: "_compact",
			isError: false,
			event: "session_before_compact",
			recentTail: rows.map((r) => ({
				ts: r.ts,
				toolName: r.toolName,
				isError: r.isError,
				fp: r.fp,
			})),
			note: "Evidence sidecar retained on disk; re-read after compact",
			evidenceFile: file,
		});
		try {
			pi.appendEntry("soveryn-evidence-checkpoint", {
				evidenceFile: file,
				at: new Date().toISOString(),
				count: rows.length,
			});
		} catch {
			/* ignore */
		}
		// Do not cancel compaction — sidecar is the durable store
	});

	pi.on("message_end", async (event, ctx) => {
		if (event.message?.role !== "assistant") return;
		const text = assistantText(event.message);
		if (!text || !CLAIM_RE.test(text)) return;

		const successes = recentSuccessCount(ctx.cwd, 24);
		const notes: string[] = [];

		if (successes < 1) {
			notes.push(
				`SOVERYN G6_TOOL_EVIDENCE: WARN — progress claim without successful tool evidence. Re-read ${evidencePath(ctx.cwd)}`,
			);
		}

		if (SHOWME && CLAIM_RE.test(text) && !hasShowmeArtifact(ctx.cwd)) {
			notes.push(
				"SOVERYN --showme: WARN — visual/html done claim lacks screenshot or file:// artifact (use open-html --screenshot)",
			);
		}

		if (!notes.length) return;
		return { message: withAnnotation(event.message, notes.join(" | ")) };
	});

	pi.registerCommand("evidence", {
		description: "Show path + tail of SOVERYN durable tool evidence log",
		handler: async (_args, ctx) => {
			const file = evidencePath(ctx.cwd);
			const rows = readRecent(ctx.cwd, 12);
			const lines = rows
				.map((r) => `${r.ts} ${r.isError ? "ERR" : "OK "} ${r.toolName} fp=${r.fp || "-"}`)
				.join("\n");
			ctx.ui.notify(`${file}\n${lines || "(empty)"}`, "info");
		},
	});
}
