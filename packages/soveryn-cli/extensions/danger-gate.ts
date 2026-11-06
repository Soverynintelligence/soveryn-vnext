/**
 * SOVERYN Desk danger gate (revamp phase 1, 2026-11-05).
 *
 * Active only when SOVERYN_DESK_GATE=1 (set by soveryn/kernel_desk/manager.py
 * for Desk RPC children). Every bash/write/edit call is sent to the Command
 * Center's /api/desk-gate/check (classifier: soveryn/kernel_desk/danger.py).
 * "hold" -> the call waits until Jon clicks Approve/Deny on /desk-gate.
 * Fail closed: server unreachable, bad reply, deny or timeout => blocked.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const ON = ["1", "true", "yes", "on"].includes(String(process.env.SOVERYN_DESK_GATE || "").toLowerCase());
const BASE = (process.env.SOVERYN_DESK_GATE_URL || "http://127.0.0.1:5001").replace(/\/$/, "");
const TOKEN = process.env.SOVERYN_DESK_GATE_TOKEN || "";
const WAIT_MS = Math.min(Math.max(Number(process.env.SOVERYN_DESK_GATE_WAIT_S || 900) || 900, 10), 3600) * 1000;
const GATED = new Set(["bash", "write", "edit"]);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function call(path: string, init?: RequestInit): Promise<any> {
	const r = await fetch(BASE + path, {
		...init,
		headers: { "Content-Type": "application/json", "X-Desk-Gate-Token": TOKEN, ...(init?.headers || {}) },
	});
	if (r.status !== 200 && r.status !== 202) throw new Error(`HTTP ${r.status}`);
	return r.json();
}

export default function (pi: ExtensionAPI) {
	if (!ON) return;
	pi.on("tool_call", async (event: any, ctx: any) => {
		if (!GATED.has(String(event.toolName))) return;
		let res: any;
		try {
			res = await call("/api/desk-gate/check", {
				method: "POST",
				body: JSON.stringify({
					tool: event.toolName, args: event.input || {}, cwd: ctx?.cwd || process.cwd(),
					session: process.env.SOVERYN_DESK_SESSION || "",
				}),
			});
		} catch (e: any) {
			return { block: true, reason: `SOVERYN desk-gate: approval server unreachable (${e?.message || e}); call blocked (fail closed).` };
		}
		if (res?.action === "allow") return;
		if (res?.action !== "hold" || !res?.id) {
			return { block: true, reason: "SOVERYN desk-gate: unexpected gate reply; call blocked." };
		}
		try { ctx?.ui?.notify?.(`Held for Jon's approval (${res.rule}: ${res.reason}) — Command Center /desk-gate`, "warning"); } catch {}
		const until = Date.now() + WAIT_MS;
		while (Date.now() < until) {
			await sleep(2000);
			let st: any;
			try { st = await call(`/api/desk-gate/status/${res.id}`); } catch { continue; }
			if (st?.status === "approved" && !st?.consumed) return; // runs once
			if (st?.status && st.status !== "pending") {
				return { block: true, reason: `SOVERYN desk-gate: ${st.status} by Jon (${res.rule}: ${res.reason}). Do not retry the same command; ask Jon.` };
			}
		}
		return { block: true, reason: `SOVERYN desk-gate: no decision in ${WAIT_MS / 1000}s; blocked (${res.rule}).` };
	});
}
