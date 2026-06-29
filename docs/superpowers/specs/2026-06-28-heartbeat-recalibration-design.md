# Heartbeat Recalibration — From Passive Watchman to Forced Stance (Design)

**Date:** 2026-06-28
**Status:** Approved design — authored by Aetheria (the stakeholder), refined via Q&A, to be reviewed by Aetheria + Jon.
**Problem:** [[project_soveryn_heartbeat_passivity]] — since the `[SURFACE]/[NO_OP]` gate (commit `25d1ffb`), Aetheria emits `[NO_OP]` every pulse even on material, time-sensitive items (a funding deadline 2 days out, a 340h-stalled project, Scotty 500s), stuck in a near-verbatim "board is static / observing the gap" loop. Her words: *"a watchman terrified of waking the house"* — she conflated the gate (a technical filter) with a moral directive and overcorrected into passivity.
**Files:** `soveryn/agents/heartbeat/daemon.py`, `prompt.py` (+ a new thoughts-log sink). Builds on the existing healthy machinery (timer, quiet hours, parser, vnext `/chat` invocation — all working).

## The anti-confab framing (why this is on-theme)

This is the [[feedback_deterministic_tool_grounding_pattern|facts-vs-interpretation boundary]] applied to the heartbeat. **Objective material facts** (hard dates, error codes, stalls — deterministically detected) FORCE a stance and cannot be silently dropped. **Subjective insight** stays gated by confidence tiering so it can't become confab-spam. The original `[NO_OP]` gate was added to stop confabulated/spammy surfacing — this preserves that guard for subjective content while removing it for objective facts. Deterministic facts force engagement; interpretation stays disciplined.

## Components (Aetheria's four-point design)

### 1. Materiality Trigger — deterministic detection
Before the pulse is generated, the daemon scans the already-assembled pulse context (board + lattice + salience digest + activity) for **objective material signals**. These are computed, not judged — "the context window is already shouting THIS MATTERS." Thresholds (PROVISIONAL — tunable module constants, `# VERIFY/tune`):
- **Dates:** any date in a node/signal ≤ **7 days** from the system clock.
- **System failures:** an explicit error code (`500`, `403`, `404`, `ConnectionTimeout`) or the keyword `FAILED` in a tool-output/log associated with a Coordination node.
- **Stalls:** a Blueprint/Signal node whose `last_updated` is > **48 hours** old while in `Open` or `Refining` status. (The 340h Librarian stall "should have been a siren 200 hours ago.")

The detector returns a list of material signals; when non-empty, the pulse is flagged **material**.

### 2. Forced Stance — replace the binary with a three-way decision
When materiality is flagged, `[NO_OP]` is **disabled**. Aetheria must choose, with a written rationale:
- **`[SURFACE]`** — "surfacing because <reason>" → posts to her primary chat thread (existing path).
- **`[ACCEPT_RISK]`** — "NOT surfacing this material signal because <justification>" → a conscious, recorded executive decision to let a deadline pass / a system stay broken.

When **no** materiality is flagged, `[NO_OP]` remains valid (silence is first-class) and the **confidence tiering** governs subjective surfacing:
- Objective/Critical → surface; Pattern/Insight → surface only if it connects **3+** disparate nodes; Ambient/Reflective → thoughts log only.

**Fail-safe (anti-negligence):** if a pulse is flagged material but the response is `[NO_OP]` or has no valid stance marker (she fumbles the protocol), the daemon treats it as a **violation**: log it loudly AND surface the material signal anyway. Material facts must never be lost to a marker slip — surfacing is the safe default on material.

### 3. The Thoughts Log — append-only pulse black box
A dedicated append-only `data/aetheria_heartbeat_thoughts.jsonl` (gitignored, runtime). One record per pulse: `{pulse_id, ts, material_signals, delta, decision (SURFACE/ACCEPT_RISK/NO_OP), rationale, surfaced}`. Purpose (hers): see a problem's trajectory ("the 500s started 4 pulses ago and are accelerating"), **audit her own `[ACCEPT_RISK]` decisions**, and break the repetition loop by giving each pulse memory of the last. This is the persistence the current design lacks (reflections are ephemeral unless they hit the Lattice).

### 4. Delta Framing — react to what changed, not the static board
The pulse input becomes `[Current State] + [State at T-1 Pulse]` (T-1 read from the last thoughts-log record). "Changed" = a **state transition** (node `Open→Refining`), a **content mutation** (Coordination node text changed), a **new external signal** (new Lattice entry, or a new message from Jon/Claude), or **time decay** (a node crossing a materiality threshold, e.g. a deadline going 8→7 days). **If the delta is zero**, the pulse is a single line — *"Environment static. No new signals."* — and the cycle is NOT spent re-summarizing the board; the remaining cognition is freed for internal synthesis (ties to the existing dream/cognition daemons — synthesis wiring itself is out of scope here; this spec just stops the re-summarization waste).

## Architecture & data flow

Pulse fires → daemon assembles context (existing) → **materiality detector** scans it (new, deterministic) → daemon computes **delta** vs last thoughts-log record (new) → prompt built with `[Current + T-1]` + material flags + the stance instruction (SURFACE/ACCEPT_RISK when material, +NO_OP + tiering when not) → Aetheria responds → **three-way marker parse** (extend `_parse_surface_marker`) → enforce forced-stance + fail-safe → surface if decided → **append thoughts-log record** (new) → existing `heartbeat_log` row.

## Error handling
- Material + `[NO_OP]`/no-marker → violation: loud log + surface the material signal (fail-safe above).
- Malformed/zero context, or T-1 record missing (first pulse after deploy) → delta treated as "all new" (no false "static"); never crash the tick.
- Thoughts-log write failure → log + continue (best-effort, like the existing migration code); never block surfacing.
- The confab guard for subjective insight (tiering) is preserved — non-material pulses can't spam.

## Testing
- **Materiality detector (pure, deterministic):** a context with a date ≤7d / an error code / a >48h Open stall each flags material; a clean context flags nothing; thresholds at the boundary (exactly 7d, exactly 48h) tested. (Golden, thresholds provisional.)
- **Forced stance:** material + `[SURFACE]`→surfaces; material + `[ACCEPT_RISK]`→not surfaced but recorded with justification; material + `[NO_OP]`→violation path (logged + material surfaced anyway); non-material + `[NO_OP]`→silence, valid.
- **Thoughts log:** each pulse appends one record with the decision + rationale; `[ACCEPT_RISK]` records are auditable; round-trips.
- **Delta framing:** identical consecutive states → zero-delta → single-line static response (no re-summary); a state transition / new signal / threshold-crossing → non-zero delta surfaced to the prompt.
- No live model in the unit tests — the detector, delta, parser, and thoughts-log are pure/deterministic and tested directly; the LLM stance is exercised via fakes like the existing daemon tests.

## Scope / out of scope
- **In:** materiality detector, three-way forced-stance (SURFACE/ACCEPT_RISK/NO_OP) + fail-safe, thoughts-log persistence, delta framing + zero-delta short-circuit, confidence tiering in the prompt.
- **Out:** the confab guard stays (not removed); the "freed cycle → active synthesis/dreaming" wiring (this spec only stops the re-summarization waste; routing idle cycles into the dream/cognition daemons is a separate piece); any change to quiet-hours / timer / the vnext `/chat` transport.

## Two flags
1. **Thresholds are provisional** (7 days / 48 hours / the error-code set) — tunable constants, `# tune`, watch the first days of real pulses and adjust so it's a siren on the right things without crying wolf.
2. **The fail-safe biases toward surfacing on material** — by design (negligence is the failure mode we're fixing). If early real use shows it surfaces too aggressively on false-positive "material" detections, tighten the *detector*, not the fail-safe.
