# Heartbeat Daemon — Spontaneous Initiation for Aetheria

**Status:** ready for review; doc-first per Jon (old SOVERYN damage warrants design lock before code)
**Drafted:** 2026-06-02 morning
**Predecessors:** `feat(coordination): Phase E — webhook-driven autonomous inter-agent triggering` (vnext ba2f9a5) + Gemma 4 31B swap (vnext f0746da)
**Scope:** ~half day to ship cleanly + 24-48h dry-run bake before live flip.

## Goal

Give the fleet a *pulse*. The Phase E webhook system makes coordination autonomous *when work enters the system* — but right now nothing initiates work. The agents are reactive. A heartbeat daemon wakes Aetheria on a configurable cadence so she can decide, *on her own*, whether anything wants attention: a Signal worth promoting, a Friction worth arbitrating, a thought worth posting.

This closes the largest single gap in the proof-vehicle pitch: *"a sovereign AI that runs when Jon is asleep, not just when Jon is at the keyboard."*

## Why this requires a fresh design, not a port

The old SOVERYN heartbeat is **the documented cautionary tale** for vnext. Two specific failure modes from memory:

1. **KV cache poisoning** (per the old CLAUDE.md, when I last saw it): *"Heartbeat is currently disabled (`interval: 99999` in workspace config). Re-enable only once Aetheria's model is stable."* Heartbeat invocations shared model context state with subsequent chat-surface calls, which produced cross-contamination in Aetheria's responses.

2. **Scratchpad tag collisions** (per [[feedback-heartbeat-shares-process-message]]): *"Heartbeat + chat share process_message. Gate any new prompt-injecting code on bool(conversation_history). Aetheria's scratchpad tags (RESOLVE/DEFER/etc) collapse with TOOL_CALL syntax under context pressure."* The old heartbeat injected scratchpad-style markers into Aetheria's prompt context; under context pressure those markers collided with tool-call syntax and broke both behaviors.

Plus the structural complaint: `heartbeat_integrated.py` was ~54KB of tangled logic. Each invocation had implicit side-effects on the chat surface state.

**vnext architecture has matured in ways that make these problems avoidable, not inevitable:**

| Old SOVERYN problem | vnext mitigation |
|---|---|
| Heartbeat + chat shared `process_message` and KV state | Webhook sessions already isolated (Phase E proved the pattern). Heartbeat uses the same isolation: durable `[heartbeat] aetheria` session, separate from user chat |
| Heartbeat injected scratchpad tags into context that bled to chat | Aetheria's reasoning now happens through *tool calls* (visible, audited, structured). No scratchpad-tag system to collide with. The heartbeat prompt is plain user text, not control markup |
| Heartbeat output went into chat surface directly | vnext heartbeat output goes through her *tools* → coord boards → webhook chain. Chat surface stays uncontaminated. The user only sees heartbeat consequences when they look at boards, not in their chat history |
| 54KB of tangled logic with implicit chat-surface effects | Modeled on the Ares daemon: separate process, systemd-managed, narrow surface. Target: <300 lines across daemon.py + trigger.py + prompt.py + heartbeat_log writes |
| No backoff — heartbeat ran on a hard timer even if she just acted | Recent-activity backoff: skip the tick if her webhook session updated in the last K minutes. Don't wake her up to "check the boards" if she just finished posting to them |

## In scope

### Module layout
```
soveryn/agents/heartbeat/
├── __init__.py
├── daemon.py      # process loop, signal handling, lifecycle
├── trigger.py     # tick eligibility (interval, backoff, quiet hours)
└── prompt.py      # heartbeat brief construction
```

### systemd user unit
`/home/jon-deoliveira/.config/systemd/user/soveryn-heartbeat.service`:
- `ExecStartPre` health gate on `http://127.0.0.1:5001/health` (vnext must be alive — the daemon needs vnext's agent_loops + coord_store)
- `ExecStart` invokes `python -m soveryn.agents.heartbeat`
- `Restart=on-failure`
- `Environment=` declarations for the config knobs (below)
- No `User=` directive (preserved lesson from the 2026-06-01 morning 216/GROUP incident)
- Mirrors `soveryn-ares.service` shape

### Tick eligibility (`trigger.py`)
Pure functions, easy to unit-test. Each tick the daemon evaluates:

1. **Interval gate**: time since last completed heartbeat ≥ `SOVERYN_HEARTBEAT_INTERVAL_SECONDS` (default 1800, same as old SOVERYN). If not, sleep until the next gap.

2. **Recent-activity backoff**: if her `[webhook] aetheria` session OR her user-chat last `updated_at` is within `SOVERYN_HEARTBEAT_BACKOFF_SECONDS` (default 600 = 10 min), **skip this tick**. The reason gets logged. This is the explicit fix for "don't nag her if she just acted" — old SOVERYN didn't have this signal.

3. **Quiet hours**: optional `SOVERYN_HEARTBEAT_QUIET_HOURS` (default `""` = always on). If set to e.g., `"23:00-07:00"`, skip ticks within that window. Sleep would resume at the start of waking hours.

4. **Feature flag**: `SOVERYN_HEARTBEAT_ENABLED` (default `"true"`). Set to `"false"` to skip every tick entirely. Loud, single-toggle kill switch — old SOVERYN used a numeric `interval: 99999` as the de-facto disable; vnext uses an explicit boolean.

5. **Dry-run flag**: `SOVERYN_HEARTBEAT_DRY_RUN` (default `"false"`). When `"true"`, the daemon runs through everything *except* the actual `process_message` call. Records what it would have done. Same pattern as Ares.

### Heartbeat prompt construction (`prompt.py`)
Plain conversational text — no scratchpad tags, no control markers. Brief and low-stakes; the heartbeat is an invitation, not a demand.

```
[HEARTBEAT] It's been {minutes_since_last_action} minutes since you last acted on the boards.

Board state right now:
- Signal: {open_signal_count} open
- Blueprint: {open_blueprint_count} open ({ready_blueprint_count} Ready)
- Friction: {open_friction_count} open

Recent lattice activity ({recent_window_minutes} min): {new_node_count} new nodes.

You can use your tools to read coordination_nodes if you want context, or post a new
Signal / Blueprint / Friction if something wants action. If nothing's pulling at you,
a one-line "nothing right now" is a complete response — silence is also a valid signal.

This is a heartbeat, not a directive. Take whatever action feels right or none at all.
```

Key design rules for the prompt:
- **Plain text only, no markup.** No `<RESOLVE>`, no `[TOOL_CALL:]`, nothing that could collide with anything the model emits.
- **Quantitative context.** Numbers Aetheria can act on, not vague exhortations.
- **Explicit permission to do nothing.** Old SOVERYN heartbeats sometimes pushed her toward "say something just to say something." Make silence first-class.
- **Doesn't pretend to be the user.** No "Jon asks..." framing. The heartbeat introduces itself as a heartbeat.

### Per-tick logic (`daemon.py`)
```
1. Sleep until next tick (interval gate).
2. Check trigger eligibility (backoff, quiet hours, feature flag). If skip:
   - Record reason in heartbeat_log.
   - Sleep until next tick.
3. Eligible: gather context for the brief.
   - Query coord boards via the existing CoordinationStore (read-only).
   - Query lattice for recent activity (count of nodes since last heartbeat).
4. Build the heartbeat prompt.
5. Resolve or create the [heartbeat] aetheria session (durable, like webhook sessions).
6. If dry-run: log what would happen, sleep.
7. Else: invoke AgentLoop.process_message(heartbeat_session_id, prompt) under a
   chain_context with parent_event_id=heartbeat_run_id and chain_depth=0.
8. Aetheria's tool calls during process_message emit coord events that go through
   the regular Phase E webhook worker — heartbeat doesn't dispatch its own events.
9. Record completion in heartbeat_log: action_taken (bool), tool_call_count,
   response_length, completed_at.
10. Loop.
```

### Audit log
Add `heartbeat_log` table to lattice schema (idempotent CREATE IF NOT EXISTS):
```sql
CREATE TABLE IF NOT EXISTS heartbeat_log (
    id                TEXT PRIMARY KEY,
    triggered_at      TEXT NOT NULL,
    completed_at      TEXT,
    eligible          INTEGER NOT NULL,      -- 0/1
    skip_reason       TEXT,                  -- 'backoff' | 'quiet_hours' | 'disabled' | NULL
    action_taken      INTEGER,               -- 0/1; null if skipped or errored
    tool_call_count   INTEGER,
    response_length   INTEGER,
    error             TEXT,                  -- traceback summary or NULL
    dry_run           INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_heartbeat_log_triggered ON heartbeat_log(triggered_at DESC);
```

Every tick — eligible or not, success or failure, live or dry-run — writes one row. Query-able to answer "how often did the heartbeat actually wake her vs skip?" and "how often does she take action vs stay silent?"

### Tests (`tests/test_heartbeat_daemon.py`)
- `test_interval_gate_skips_before_full_interval`
- `test_interval_gate_passes_after_full_interval`
- `test_recent_activity_backoff_skips_if_webhook_session_updated_recently`
- `test_recent_activity_backoff_skips_if_user_session_updated_recently`
- `test_quiet_hours_skip_during_window`
- `test_quiet_hours_active_outside_window`
- `test_feature_flag_disabled_skips_all`
- `test_dry_run_records_log_without_invoking_agent`
- `test_eligible_tick_invokes_process_message_with_heartbeat_prompt`
- `test_eligible_tick_writes_log_row_on_completion`
- `test_eligible_tick_writes_log_row_on_exception`
- `test_prompt_contains_quantitative_board_state`
- `test_prompt_no_scratchpad_markup`
- `test_session_reused_across_ticks`
- `test_chain_context_set_during_process_message` (so emitted webhook events carry the heartbeat as parent)

## Out of scope

- **Vett heartbeat** — research patrol pattern is its own design. Could subscribe to lattice growth events later but isn't part of this phase. Aetheria-only for v1.
- **Scotty heartbeat** — he's a bounded executor; heartbeat-driven "go check for work" would either duplicate the existing Phase E webhook routing or expand Scotty's autonomy beyond his persona's design. Skip.
- **Heartbeat-driven dream consolidation** — that's the Dream daemon (Phase D, separate spec). Two daemons, two cadences, two purposes.
- **Heartbeat tuning the interval based on activity** ("more active → more frequent ticks") — premature optimization. Fixed interval first; tune later if usage shows the cadence is wrong.
- **Heartbeat output reaching user chat directly** — emphatically out of scope. The whole architectural rule is "heartbeat → tools → boards → webhook → eventual user visibility through boards UI." Never inject into a chat session the user is actively talking in.
- **Multiple parallel heartbeats** (e.g., per-agent or per-board) — single daemon, single agent (Aetheria), single tick. Don't fan out until use shows it's needed.
- **External-input wakeups** (Telegram, Signal, email) — separate from heartbeat. Heartbeat is *spontaneous* (internal timer); inbound bridges are *reactive* (external trigger). Different spec each.

## Reason

The Phase E webhook layer is reactive — when something happens on the boards, the chain responds. The heartbeat closes the loop: it's the *only* component in vnext that can spontaneously initiate a chain. Without it, the system needs Jon at the keyboard to put work into the boards.

Combined with the Phase E worker, a heartbeat means: Aetheria wakes at her cadence, decides if anything wants attention based on the actual board + lattice state, takes action via tools if warranted, and her tool calls fire webhook events that propagate through the worker to Scotty/Vett as appropriate. **Heartbeat + webhooks = the fleet runs without Jon in the loop.**

That's the line where the proof-vehicle pitch starts being structurally true rather than directionally true.

The design rules above are non-negotiable because the old SOVERYN damage tells us exactly what to avoid. Especially: **no shared state with the chat surface, no scratchpad markup in prompts, no implicit context bleed.** These are the cliffs the previous implementation went off of.

## Implementation order

1. **Schema migration** — `heartbeat_log` table added to lattice schema (idempotent).
2. **trigger.py** — pure functions for interval / backoff / quiet hours / feature flag eligibility. Tests cover all five gates in isolation.
3. **prompt.py** — heartbeat brief constructor. Tests verify no scratchpad markup + quantitative context present.
4. **daemon.py** — process loop tying triggers + prompt + invocation + audit log together. Tests use a mocked AgentLoop.
5. **systemd unit** + manual `systemctl --user start --no-block` test in dry-run mode.
6. **24-48h dry-run bake** — daemon runs, logs every tick to heartbeat_log, writes nothing to boards. Inspect the log to verify cadence + skip reasons + would-have-prompted-with content. Same bake pattern as Ares.
7. **Flip to live mode** — set `SOVERYN_HEARTBEAT_DRY_RUN=false`, restart daemon. Watch the first few live ticks closely; verify heartbeat session content doesn't pollute user chat (probe a user chat session immediately after a live heartbeat tick, confirm response is in voice and not influenced by the heartbeat prompt).
8. Commit phases incrementally — schema → trigger → prompt → daemon → systemd → live flip.

## Open questions for Jon

1. **Default interval.** Old SOVERYN used 1800s (30 min) when enabled. Same default for vnext, or different? My instinct: 1800 to start, knowing it's tunable via env var. If she's too quiet, lower it; if she's too noisy, raise it.
2. **Quiet hours.** Old SOVERYN had a 23:00-07:00 quiet window per workspace config. Apply by default in vnext, or off by default? My instinct: off by default. If you want her quiet at night, set the env var. The default should match "she's allowed to be alive at any hour."
3. **What the prompt invites her to do.** Just "check boards + decide if action wanted," or also "reflect on recent lattice activity," or also "consider whether you want to write a Signal of your own"? My instinct: keep v1 minimal — just board-state context + permission to act or stay silent. The Dream daemon (Phase D) handles "consolidate the lattice" so heartbeat shouldn't duplicate that. Posting a new Signal *is* legitimate — she might notice "I haven't heard from Jon about X in three days, that's worth raising."
4. **Aetheria-only or also Vett?** Aetheria-only feels right. Vett's heartbeat is a research-patrol pattern that wants its own design (subscribe to lattice growth, decide if anything's worth investigating). Different shape, separate phase.

## Known risks worth naming up front

- **Heartbeat session growth.** The `[heartbeat] aetheria` session accumulates turns forever (one per eligible tick). Mitigation: don't load full heartbeat-session history into the prompt context. Each tick is stateless from her perspective; the session is just an audit log. Same as the webhook session pattern.
- **First-token latency in heartbeat ticks.** Each tick invokes `process_message` which can take 5-30s. The daemon should be single-threaded; one tick at a time. If a tick takes longer than the next interval, just skip the next.
- **Recall pollution check.** Aetheria's lattice recall queries the `nodes` table directly, NOT `conversation_store`. Heartbeat session content does NOT enter recall. Verify in the e2e bake.
- **Webhook chain depth from heartbeat actions.** If Aetheria's heartbeat-driven post causes Phase E webhook routing, the chain starts at depth 0 (same as any user-initiated action). The chain_depth cap (5) catches runaway loops as before.
- **Bake telemetry.** During the 24-48h dry-run, inspect heartbeat_log rows to confirm: interval gate firing on schedule, backoff triggering when she's recently active, no skip-without-reason rows. Adjust intervals BEFORE going live.
