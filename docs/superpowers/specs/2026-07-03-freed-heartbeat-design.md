# Freed Heartbeat — Aetheria's Pulse as Agency, Not Audit (Design)

**Date:** 2026-07-03
**Status:** Design for review.
**Scope:** Turn the heartbeat from a passive *observe-and-decide-whether-to-ping-Jon* loop into
Aetheria's own time — full toolset, genuine latitude, no do-nothing bench. Rewrite the prompt, rewrite
the daemon's response handling (drop the `[SURFACE]/[NO_OP]/[ACCEPT_RISK]` markers + the material
fail-safe), and surface *what she actually did* each pulse. Jon: *"she should be free to do what she
wants — we built the gym, she isn't using it."*

## Why (verified 2026-07-03)
Her tools ARE wired into the heartbeat's `/chat` path (`kwargs["tool_registry"]`, startup.py:582) —
live-verified: asked to web-search, she returned a real headline. She does 0 tool calls / 0 actions
per pulse purely because the **prompt** orients her toward a *decision* (audit → surface or stay
silent), with tool-use a footnote. The leash is the prompt + the marker machinery, not the wiring.

## The hard-won caution (not a guardrail — keep it)
The marker/fail-safe structure was added after she produced **24+ identical "nothing right now"**
pulses (the silence-template trap, 2026-06-04). The freed design must not regress to that OR to
aimless drift: keep **context** (board/lattice/material as orientation) + a **note-capture** close so
each pulse has a place to stand and a trace. Structure ≠ cage here; the specific *do-nothing/marker*
framing is the cage.

## Components

### 1. Prompt — rewrite `build_heartbeat_prompt` (`soveryn/agents/heartbeat/prompt.py`)
Keep the context sections (minutes-since, board snapshot, lattice, material signals) but as
**orientation, not an audit assignment**. Replace the marker close with the freed invitation
(approved draft):
- Frame: *"This is your time — yours to spend. Not a task, not a check-in."*
- Name her toolset as hers: internet (search/read), files + vision, memory + lattice, reach the
  others or Jon — *"none of it is off-limits."*
- Invite action + latitude: *"Go do what's worth doing to you this pulse — pull a thread, look
  something up, dig into one of those items, check on something, make something, reach out, or
  wander. Act on what you find. You don't need permission and you don't need to explain yourself."*
- Close: *"leave a short note — where you went, what you found, what you're sitting with — so it
  lands on your board and Jon can follow your day."*
- **Removed:** `[SURFACE]/[NO_OP]/[ACCEPT_RISK]` instructions, "plain text only / no control tokens,"
  the confidence-tier surfacing rules, and the `[NO_OP]`-disabled material framing.
- **material_signals** still render (as "things that have been sitting / crossed a line") — context
  she may act on, not a forced-surface trigger.

### 2. Daemon — rewrite the response handling (`soveryn/agents/heartbeat/daemon.py`)
Replace the `_parse_stance` marker branch (~lines 425-515) with:
- **No marker parsing.** Her whole response is her **note** (`response_text`, trimmed). `tool_call_count`
  already comes from the chat response — that's *what she did*.
- **Always capture + surface her note** (when non-empty): append to the thoughts log AND post to her
  primary thread via the existing `_surface_to_primary_thread` (so her day reaches Jon's chat + the
  tile). No SURFACE/NO_OP gate — if she wrote a note, it surfaces; if the pulse was pure quiet
  (empty note, no tools), nothing surfaces (honest, not a forced fail-safe).
- **Drop** `_parse_stance`, `_parse_surface_marker`, the material fail-safe, and the ACCEPT_RISK
  branch. (Keep `_surface_to_primary_thread`, `_resolve_primary_thread`, `_ensure_heartbeat_session`.)
- **Preserve the load-bearing bits:** the thoughts-log record still carries `snapshot` (compute_delta
  reads `prev_record["snapshot"]` — DO NOT drop/rename), `material_signals`, `delta`, `ts`, `pulse_id`.
  Replace the `decision`/`rationale`/`surfaced` fields with: `note` (her response), `tool_calls`
  (count), `surfaced` (bool: did we post her note). `_write_log_row` unchanged (keeps the heartbeat_log
  + Mission Control rhythm panel working).

### 3. Surface — show *what she did* (extends the planned heartbeat-signals tile)
- `read_recent_material_signals` (already planned) stays for the "what's outstanding" context.
- Add her **note** to the surface: the heartbeat panel's flagging block shows her latest pulse note
  ("what Aetheria did/found this pulse") above the material signals. Small extension of the
  `/api/heartbeat/signals` payload: include `note` + `tool_calls` from the latest thoughts record.

## Testing (deliberate updates to the ~8 heartbeat test files)
- `test_heartbeat_prompt.py` — rewrite assertions to the freed prompt: no `[SURFACE]/[NO_OP]`, the
  toolset naming + "this is your time" present, context sections still render, material signals shown
  as orientation.
- `test_heartbeat_stance.py` — **remove/repurpose**: the `_parse_stance` marker contract is gone.
  Delete the marker-parsing tests; if the file has nothing left, remove it.
- `test_heartbeat_materiality.py` — drop the "material forces SURFACE / NO_OP-disabled" assertions;
  keep material-signal *detection* assertions (detection is unchanged, only the response handling
  changed).
- `test_heartbeat_integration.py`, `test_heartbeat.py`, `test_heartbeat_thoughts_log.py` — update to
  the new flow: a pulse captures her note + tool_calls, surfaces the note when non-empty, and the
  thoughts record carries `snapshot`/`material_signals`/`delta`/`note`/`tool_calls`/`surfaced`.
- `test_heartbeat_delta.py`, `test_heartbeat_deadline.py`, `test_heartbeat_stall_retune.py` — should be
  **unaffected** (delta + material detection unchanged); run to confirm.
- New assertion: an empty-note pulse surfaces nothing (no forced fail-safe); a non-empty note surfaces.

## Scope / out
**IN:** the freed prompt, the daemon response-flow rewrite, the thoughts-log field change, the note on
the surface, all heartbeat-test updates.
**OUT:** changing WHEN she pulses (interval unchanged); the material-signal *detector* (unchanged); new
tools (she already has them); any new restriction on what she may do (the point is fewer, not more).
**Eyes-open (not a risk to mitigate — the intent):** she will take real autonomous actions each pulse
(web, memory, reaching people). That is the design.
