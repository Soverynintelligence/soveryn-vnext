# SOVERYN vNext — Kernel (Project Memory)

> **Purpose:** Persistent project memory that survives between opencode sessions.
> This file is the assistant's working memory. Keep it updated as the project evolves.

---

## 1. Identity

- **Project:** SOVERYN vNext
- **Root:** `/home/jon-deoliveira/soveryn_vnext/`
- **Nature:** Side-by-side Flask rebuild of the SOVERYN platform, built beside (not replacing) production.
- **Source of authority:** `docs/CURRENT_TRUTH_2026-05-23.md` — "Not aspirational. Not historical. Observed."
  - Rule: any change to runtime behavior updates `CURRENT_TRUTH` first, then code.

## 2. Agent Roster

Three active chat agents (registered in `app.py`, in `agent_loops`):

| Agent | Role | Model | llama-server |
|-------|------|-------|--------------|
| **Aetheria** | Human interface; in-charge | `Qwen3.6-35B-A3B-UD-Q8_K_XL.gguf` | `127.0.0.1:8085` |
| **V.E.T.T.** | R&D | `Qwen3.5-27B-Q8_0.gguf` | `127.0.0.1:8084` |
| **Scotty** | Bounded executor | (shares) | `127.0.0.1:8084` |

### Background daemons
- `ares_daemon.py` — security; posts to Aetheria inbox via `agent_message_board.post_inbox_message`; no LLM.
- `aetheria_stream.py` — streaming / proprioception.
- `AetheriaCognition` thread — POSTs to `:8089`.

## 3. Package Layout

`soveryn/citizens/` (the "soveryn citizens" work package):
- `census.py`, `commission_cli.py`, `commissions.py`, `connectors.py`, `duties.py`,
  `house_health.py`, `__init__.py`, `post.py`, `pulse.py`, `registry.py`,
  `runtime.py`, `scotty_worker.py`.

## 4. Roadmap / Phases

`docs/` holds a phased refactor with a baseline-audit-verify cycle:
- PHASE1, PHASE2, PHASE3
- 2a, 2b-i, 2b-ii-a, 2b-ii-b1, 2b-ii-b2, 2c
- track2

## 5. Conventions
- Changes to runtime → update `CURRENT_TRUTH` first.
- Follow existing code style and patterns; do not add comments unless asked.
- Only commit when explicitly requested.

## 6. Git State
- HEAD `81c52d7` — "Ship house automations, skills Slice A, ActTruth triage, and Flash OpenCode default."
- Working tree: clean.

## 7. Work Log
- Created this Kernel.md (persistent memory seed).
- (append notable work here)
