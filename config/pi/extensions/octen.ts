/**
 * Octen live web tools for Kernel (Pi).
 * Wire: config/pi/extensions/octen.ts (auto-loaded via PI_CODING_AGENT_DIR).
 *
 * Auth: OCTEN_API_KEY in the environment that launches `kernel` / soveryn-pi.
 *   Get a key: https://octen.ai/platform
 *   Prefer: export OCTEN_API_KEY=... in the TTY, or add to a sourced secrets file
 *   (do not commit). Header sent: x-api-key.
 *
 * Pi core has no MCP client. This is a thin HTTP proxy to api.octen.ai
 * (same capabilities as hosted MCP tools search / news_search / broad_search / extract).
 * Full remote-MCP via community pi-mcp-adapter is optional later — see report.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";

const BASE = (process.env.OCTEN_API_BASE || "https://api.octen.ai").replace(/\/$/, "");

function apiKey(): string | undefined {
  const k = (process.env.OCTEN_API_KEY || process.env.OCTEN_KEY || "").trim();
  return k || undefined;
}

function missingKeyText(): string {
  return [
    "Octen blocked: OCTEN_API_KEY is not set in Kernel's environment.",
    "Jon: create a key at https://octen.ai/platform then either:",
    "  export OCTEN_API_KEY=...   # in the shell before `kernel`",
    "  or put OCTEN_API_KEY=... in a secrets file you already source (do not git-commit).",
    "Pi has no built-in MCP; this extension calls https://api.octen.ai over HTTPS.",
  ].join("\n");
}

async function octenPost(
  path: string,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<{ ok: boolean; status: number; text: string }> {
  const key = apiKey();
  if (!key) return { ok: false, status: 0, text: missingKeyText() };
  try {
    const res = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json",
        "x-api-key": key,
      },
      body: JSON.stringify(body),
      signal,
    });
    const text = await res.text();
    return { ok: res.ok, status: res.status, text: text || `(empty body, HTTP ${res.status})` };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return { ok: false, status: 0, text: `Octen request failed: ${msg}` };
  }
}

function toolResult(r: { ok: boolean; status: number; text: string }) {
  const prefix = r.ok ? "" : `Octen error (HTTP ${r.status || "n/a"}):\n`;
  return {
    content: [{ type: "text" as const, text: prefix + r.text }],
    details: { ok: r.ok, status: r.status },
  };
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "octen_search",
    label: "Octen search",
    description:
      "Live web search via Octen (api.octen.ai/search). Ranked results with highlights. Use for current events, facts, docs on the public web.",
    parameters: Type.Object({
      query: Type.String({ description: "Search query (≤500 chars). Supports site:domain." }),
      count: Type.Optional(Type.Number({ description: "Result count 1–100 (default 5)" })),
      time_range: Type.Optional(
        Type.String({ description: "Relative window: day|week|month|year" }),
      ),
      include_domains: Type.Optional(Type.Array(Type.String())),
      exclude_domains: Type.Optional(Type.Array(Type.String())),
      full_content: Type.Optional(Type.Boolean({ description: "Include full page text (costlier)" })),
    }),
    async execute(_id, params, signal) {
      const body: Record<string, unknown> = { query: String(params.query || "").slice(0, 500) };
      if (params.count != null) body.count = params.count;
      if (params.time_range) body.time_range = params.time_range;
      if (params.include_domains?.length) body.include_domains = params.include_domains;
      if (params.exclude_domains?.length) body.exclude_domains = params.exclude_domains;
      if (params.full_content) body.full_content = { enable: true };
      body.highlight = { enable: true };
      return toolResult(await octenPost("/search", body, signal));
    },
  });

  pi.registerTool({
    name: "octen_news_search",
    label: "Octen news search",
    description:
      "Live news-oriented search via Octen (api.octen.ai/news-search). Prefer for recent news / headlines.",
    parameters: Type.Object({
      query: Type.String({ description: "News query" }),
      count: Type.Optional(Type.Number({ description: "Result count (default 5)" })),
      time_range: Type.Optional(Type.String({ description: "day|week|month|year" })),
    }),
    async execute(_id, params, signal) {
      const body: Record<string, unknown> = { query: String(params.query || "").slice(0, 500) };
      if (params.count != null) body.count = params.count;
      if (params.time_range) body.time_range = params.time_range;
      return toolResult(await octenPost("/news-search", body, signal));
    },
  });

  pi.registerTool({
    name: "octen_broad_search",
    label: "Octen broad search",
    description:
      "Decompose a question into sub-queries and search them concurrently (api.octen.ai/broad-search). Use for research / compare / survey questions.",
    parameters: Type.Object({
      query: Type.String({ description: "Research question" }),
      max_queries: Type.Optional(Type.Number({ description: "Sub-query cap 1–30 (default 5)" })),
      count: Type.Optional(Type.Number({ description: "Results per sub-query" })),
    }),
    async execute(_id, params, signal) {
      const body: Record<string, unknown> = { query: String(params.query || "").slice(0, 500) };
      if (params.max_queries != null) body.max_queries = params.max_queries;
      const search_options: Record<string, unknown> = { highlight: { enable: true } };
      if (params.count != null) search_options.count = params.count;
      body.search_options = search_options;
      return toolResult(await octenPost("/broad-search", body, signal));
    },
  });

  pi.registerTool({
    name: "octen_extract",
    label: "Octen extract",
    description:
      "Extract clean LLM-ready content from one or more URLs (api.octen.ai/extract). Optional query focuses highlights.",
    parameters: Type.Object({
      urls: Type.Array(Type.String(), { description: "One or more http(s) URLs" }),
      query: Type.Optional(Type.String({ description: "Focus keywords for highlights" })),
    }),
    async execute(_id, params, signal) {
      const urls = (params.urls || []).map(String).filter(Boolean).slice(0, 20);
      if (!urls.length) {
        return {
          content: [{ type: "text" as const, text: "octen_extract: urls required" }],
          details: { ok: false },
        };
      }
      const body: Record<string, unknown> = { urls };
      if (params.query) body.query = String(params.query);
      return toolResult(await octenPost("/extract", body, signal));
    },
  });

  pi.registerCommand("octen-status", {
    description: "Show whether OCTEN_API_KEY is set for Kernel Pi Octen tools",
    handler: async (_args, ctx) => {
      const key = apiKey();
      ctx.ui.notify(
        key
          ? `Octen: key present (${key.slice(0, 4)}…${key.slice(-2)}, ${key.length} chars). Base ${BASE}`
          : "Octen: OCTEN_API_KEY missing — tools will refuse until Jon exports a key.",
        key ? "info" : "error",
      );
    },
  });
}
