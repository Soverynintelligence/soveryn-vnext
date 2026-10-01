/**
 * SOVERYN web pack — real Chromium/HTML tools for cathedral / canvas work.
 * Loaded via: pi --extension <this-file>  (soveryn --pack web)
 *
 * Tools:
 *   web-api-probe     — typeof/existence of browser APIs in live Chromium
 *   html-module-host  — Exit A ES-module host (no bundler)
 *   open-html         — open/screenshot HTML with house 20s Chrome timeout
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const EXT_DIR = dirname(fileURLToPath(import.meta.url));
const SCRIPTS = join(EXT_DIR, "..", "scripts", "web");

function scriptPath(name: string): string {
	const p = join(SCRIPTS, name);
	if (!existsSync(p)) {
		throw new Error(`web pack script missing: ${p}`);
	}
	return p;
}

function runNode(script: string, args: string[], cwd: string): {
	ok: boolean;
	status: number | null;
	stdout: string;
	stderr: string;
} {
	const r = spawnSync(process.execPath, [script, ...args], {
		cwd,
		encoding: "utf8",
		maxBuffer: 8 * 1024 * 1024,
		env: process.env,
	});
	return {
		ok: r.status === 0,
		status: r.status,
		stdout: r.stdout || "",
		stderr: r.stderr || "",
	};
}

const ProbeParams = Type.Object({
	apis: Type.Optional(
		Type.Array(Type.String(), {
			description:
				"Browser API names to probe (e.g. AudioContext, WebGL2RenderingContext, canvas.getContext). Default: house canvas/audio set.",
		}),
	),
});

const HostParams = Type.Object({
	dir: Type.Optional(Type.String({ description: "Project dir (default: cwd)" })),
	out: Type.Optional(Type.String({ description: "Output HTML name (default: host.html)" })),
	modules: Type.Optional(
		Type.Array(Type.String(), {
			description: "Module files as type=module (default: core.mjs,kit.mjs,world.mjs,render.mjs)",
		}),
	),
	serve: Type.Optional(
		Type.Boolean({
			description: "If true, append serve command (tool itself does not hang on a server)",
		}),
	),
	check: Type.Optional(Type.Boolean({ description: "Plan only; do not write" })),
});

const OpenParams = Type.Object({
	target: Type.String({ description: "HTML file path or http(s) URL" }),
	screenshot: Type.Optional(Type.String({ description: "Optional PNG path (forces headless)" })),
	headless: Type.Optional(Type.Boolean({ description: "Headless dump-dom smoke (bounded)" })),
});

export default function soverynWebPack(pi: ExtensionAPI) {
	pi.registerTool({
		name: "web-api-probe",
		label: "web-api-probe",
		description:
			"Probe named Web/DOM/Audio/WebGL APIs in real Chromium (headless, 20s timeout). Use BEFORE writing canvas/audio code so you do not invent nonexistent APIs. Returns JSON typeof/exists (and canvas.getContext webgl/webgl2/2d).",
		promptSnippet: "Live Chromium API existence probe",
		promptGuidelines: [
			"Call web-api-probe before relying on AudioContext, WebGL, OffscreenCanvas, or other browser APIs.",
			"Do not invent browser APIs; trust probe JSON over memory.",
			"House wraps Chrome with timeout — never launch unbounded headless Chrome yourself.",
		],
		parameters: ProbeParams,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const args: string[] = ["--json"];
			if (params.apis?.length) args.push(...params.apis);
			const r = runNode(scriptPath("web-api-probe.mjs"), args, ctx.cwd);
			const text = (r.stdout || r.stderr || "").trim() || `probe failed status=${r.status}`;
			return {
				content: [{ type: "text", text }],
				details: { status: r.status, ok: r.ok },
			};
		},
	});

	pi.registerTool({
		name: "html-module-host",
		label: "html-module-host",
		description:
			"Write Exit A ES-module host HTML (no bundler): <script type=\"module\" src=\"./….mjs\"> for the four cathedral modules (or custom list). Prefer this over inventing Vite/webpack/esbuild APIs.",
		promptSnippet: "Scaffold ES-module HTML host (Exit A, no bundler)",
		promptGuidelines: [
			"Exit A: no bundler. Use type=module script tags only.",
			"Default modules: core.mjs, kit.mjs, world.mjs, render.mjs.",
			"To serve long-running, use bash: node …/html-module-host.mjs --serve --port 8765",
		],
		parameters: HostParams,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const args: string[] = [];
			if (params.dir) args.push("--dir", params.dir);
			if (params.out) args.push("--out", params.out);
			if (params.modules?.length) args.push("--modules", params.modules.join(","));
			if (params.check) args.push("--check");
			const r = runNode(scriptPath("html-module-host.mjs"), args, ctx.cwd);
			let text = (r.stdout || "").trim();
			if (r.stderr) text += (text ? "\n" : "") + r.stderr.trim();
			if (params.serve) {
				const dir = params.dir || ctx.cwd;
				text += `\n\nTo serve (long-running): node ${scriptPath("html-module-host.mjs")} --dir ${dir} --serve --port 8765`;
			}
			return {
				content: [{ type: "text", text: text || `html-module-host status=${r.status}` }],
				details: { status: r.status, ok: r.ok },
			};
		},
	});

	pi.registerTool({
		name: "open-html",
		label: "open-html",
		description:
			"Open an HTML file or URL in Chromium with the house 20s timeout. Optional screenshot PNG (headless). Use for smoke-checking Exit A hosts; never leave Chrome unbounded.",
		promptSnippet: "Open/screenshot HTML via bounded Chromium",
		promptGuidelines: [
			"Always bounded (SOVERYN_CHROME_TIMEOUT, default 20s).",
			"Prefer screenshot/headless for CI-like checks; interactive open is timeout-killed by design.",
		],
		parameters: OpenParams,
		async execute(_id, params, _signal, _onUpdate, ctx) {
			const args: string[] = [params.target];
			if (params.screenshot) args.push("--screenshot", params.screenshot);
			if (params.headless) args.push("--headless");
			const r = runNode(scriptPath("open-html.mjs"), args, ctx.cwd);
			const text = (r.stdout || r.stderr || "").trim() || `open-html status=${r.status}`;
			return {
				content: [{ type: "text", text }],
				details: { status: r.status, ok: r.ok },
			};
		},
	});
}
