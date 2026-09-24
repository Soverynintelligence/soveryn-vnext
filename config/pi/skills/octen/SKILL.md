---
name: octen
description: Live web search and URL extract via Octen tools on Kernel (Pi). Use when Jon asks for current web facts, news, research across sources, or clean page extract — call octen_search, octen_news_search, octen_broad_search, or octen_extract.
---

# Octen (Kernel / Pi)

Pi has **no native MCP client**. House wire is a Pi extension that calls `https://api.octen.ai` with `OCTEN_API_KEY`.

## Tools

| Tool | When |
|------|------|
| `octen_search` | General live web search |
| `octen_news_search` | Recent news / headlines |
| `octen_broad_search` | Multi-angle research (sub-queries) |
| `octen_extract` | Clean content from URL(s) |

Slash: `/octen-status` — confirms whether the API key is loaded (does not print the secret).

## Auth

- Env: `OCTEN_API_KEY` (header `x-api-key`)
- `soveryn-pi` / `kernel` loads it from gitignored `~/soveryn_vnext/.env` when unset in the process env
- Never write the key into git-tracked files, SYSTEM.md, or session logs

If tools return "OCTEN_API_KEY is not set", tell Jon to add the key to `~/soveryn_vnext/.env` (gitignored) or export it in the launching TTY.

## Do not

- Do not invent OpenCode MCP OAuth for Kernel — Kernel runs Pi, not OpenCode
- Do not fall back to guessing live facts when Octen fails; report the error
