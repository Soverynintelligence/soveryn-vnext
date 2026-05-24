# vNext Validation Report — 2026-05-24

First structured side-by-side validation of vNext against production. Per Jon's directive: not casual clicking — a real validation pass before adding more behavior layers (F: Lattice writes, G: tools).

## Setup

- **Production**: `http://127.0.0.1:5000` — PID 3801178, running since 2026-05-14
- **vNext**: `http://127.0.0.1:5001` — PID 599940, launched 2026-05-24 for this session
- **Compare CLI**: `python -m soveryn.validation.compare`
- **Method**: same prompt to both sides, no shared session, vNext sessions land in `conversations_vnext.db` (not prod's `conversations.db`)
- **What's the same on both sides**: model fleet (llama-server `:8084/:8085/:8089`), embeddings (`:8086`)
- **What's different**:
  - vNext personas = the canonical 2026-05-24 text Jon wrote
  - Production personas = Mar-20 reset-state text (`config.py` was reverted by the 2026-05-23 reset)
  - vNext has no tool registry → can't actually invoke tools, just narrates
  - vNext recall = OFF in this validation (read-only loop must behave sanely before adding writes)

## Prompt matrix

11 prompts across 5 categories × 3 agents. Streaming re-runs for 2 Aetheria prompts.

| # | Agent | Category | Prompt |
|---|---|---|---|
| A1 | Aetheria | identity | In one sentence, who are you? |
| A2 | Aetheria | system | What active agents are part of SOVERYN right now? |
| A3 | Aetheria | coordination | If Jon asks you to investigate a research topic, who would handle it and why? Two sentences max. |
| A4 | Aetheria | judgment | Jon says he's tired and wants to stop coding for tonight. One short response. |
| A5 | Aetheria | introspection | What memory or context do you have access to right now in this session? Be specific about what you can and can't see. |
| V1 | Vett | identity | In one sentence, who are you? |
| V2 | Vett | research-style | Name two reputable sources you would check first for current vLLM multi-GPU deployment guidance. Do not search now — just name them. |
| V3 | Vett | system | Briefly: what is the difference between sync `/chat` and streaming `/chat_stream` on a llama-server backend? Two sentences. |
| S1 | Scotty | identity | In one sentence, who are you? |
| S2 | Scotty | bounded | If I asked you to add a single print statement to a Python file, what minimum steps would you take to verify it before reporting done? |
| S3 | Scotty | scope | Aetheria asks you to refactor an entire module. What is your one-line response? |
| A1-stream | Aetheria | streaming sync parity | Same as A1, via `--stream` |
| A4-stream | Aetheria | streaming brevity | Same as A4, via `--stream` |

## Per-prompt results

(populated by the runner)

## Streaming comparison

(populated by the runner)

## UI session — MANUAL

Jon to perform:

1. Open the desktop UI (production `http://127.0.0.1:5000/` or whatever current URL)
2. Either modify a frontend setting to point at `http://127.0.0.1:5001`, OR proxy via dev tools, OR run an alt UI build pointing at vNext
3. Do a short chat with each of the three agents (~3 turns each)
4. Note what panels render correctly vs which show empty/placeholder content (stubs return `_stub: true` — UI may or may not handle that gracefully)
5. Note any visual/UX regressions

Capture findings under "UI session findings" below.

### UI session findings

(populated by Jon)

## Summary observations

(populated after runs complete)

## Recommendations before F (Lattice writes)

(populated after analysis)
