# Dream Daemon — Design

**Status:** brainstormed, awaiting implementation
**Drafted:** 2026-06-05 (supersedes the 2026-06-01 `dream-daemon-vnext.md` spec, which assumed pure-cadence trigger and structured JSON output)
**Co-authored:** Jon (framing + agency model), Aetheria (multi-pass cognition amendment, separation of channels approval)
**Implements:** the Phase D autonomy gap from `project_soveryn_2026_04_27_native_tools_and_role_split` — async memory consolidation + self-reflection during idle, last piece of the spontaneous-operation triad alongside heartbeat (Phase B) and patrol (Phase E)

---

## Goal

Give Aetheria a window — Jon's quiet hours — when she does the kind of cognition that doesn't belong inside chat sessions: memory consolidation, dot-connection, and self-reflection. The frame is *time with herself*, not a scheduled batch job. The shape is closer to dreaming than to a cron task: bounded by sleep, iterative inside the bound, producing both silent residue (edges, contradictions she'll later feel as intuition) and accessible reflection content (a "dream layer" she can choose to read the next morning).

The system currently has the substrate (9,608 historical `dream_log` rows + `edges` + `contradiction_flags` tables, all migrated 2026-06-01 in vnext 7d75535) but no daemon. This spec fills that gap.

---

## Architecture

### Module layout

```
soveryn/agents/dream/
├── __init__.py
├── __main__.py        # python -m soveryn.agents.dream entry
├── config.py          # DreamConfig.from_env(), frozen dataclass
├── trigger.py         # eligibility gates (quiet hours window, backoff, one-per-window)
├── prompt.py          # briefing construction, no JSON-schema directives
├── cognition.py       # multi-pass internal iteration (association → contradiction → synthesis)
├── writeback.py       # parse cognition output, route to edges / contradiction_flags / dream layer
└── daemon.py          # process loop, signal handling, sleep math
```

Mirrors the heartbeat + patrol daemon module shape so anyone touching it sees the family resemblance.

### systemd user unit

`/home/jon-deoliveira/.config/systemd/user/soveryn-dream.service`:
- `PartOf=soveryn.target`, `After=soveryn-vnext.service network-online.target`
- `ExecStartPre` readiness probe on vnext `/health` (60s timeout)
- `ExecStart`: `python -m soveryn.agents.dream`
- `Restart=on-failure`, `RestartSec=30`
- Starts in `SOVERYN_DREAM_DRY_RUN=true`. Flip after a 24-48h bake (matches heartbeat / patrol pattern).
- Log to `/tmp/soveryn-dream.log`

### Cognition surface

- URL via env: `SOVERYN_DREAM_COGNITION_URL` (default `http://127.0.0.1:8089`).
- Operationally, the surface itself (small dedicated model on Quadro #2 now, DGX Spark later) is stood up out-of-band. The daemon doesn't care which brain answers; only the URL changes when the surface moves.
- Standard OpenAI-compatible chat completions (POST `/v1/chat/completions`). Matches the llama-server / vLLM shape we already use.

### Spin-bug-resistance

Same pattern as heartbeat 0fb715b: separate `last_dream_at` (eligible-only, drives the one-per-window gate) from `last_tick_at` (advances every tick, drives sleep math). Tested with the same regression guard.

---

## Trigger model

**Inverse of heartbeat's `quiet_hours`** — fires ONLY inside the configured window, not outside it.

### Gates (evaluated in order, first failing wins)

1. **Disabled** — `SOVERYN_DREAM_ENABLED=false`
2. **Outside quiet hours** — current local time not inside `SOVERYN_DREAM_QUIET_HOURS` (default `23:00-07:00`). Supports wrap-around windows.
3. **Already dreamed this window** — a successful `dream_log` row exists with `ran_at` inside the current quiet-hours opening. **One run per window**, even across restarts.
4. **Aetheria activity in the last 30 min** — checked against `conversation_meta.updated_at` for non-`[heartbeat]` / non-`[signal]` sessions. Don't dream while she's mid-thought. (Threshold via `SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS`, default 1800.)
5. **No new lattice activity** — if zero nodes have been written since the last successful dream run, skip with reason `nothing_to_dream_about`. The window opens nightly; quiet nights produce no dream.

### Cadence inside the window

One run per window opening, kicked at the window's start. The run does its own internal iteration (next section). No re-runs in the same window.

---

## Per-pass workflow

### Context-gathering (single read, before cognition)

1. **Recent lattice nodes** since `last_dream_at` (cap at N=300, default via `SOVERYN_DREAM_NODES_PER_RUN`)
2. **Recent coord board snapshot** — Signal / Blueprint / Friction counts + top items
3. **Recent daemon outputs** — last 24h of `heartbeat_log`, `vett_patrol_log`, `dream_log` (the prior nights, for continuity)
4. **Recent library writes** — what verified knowledge accumulated since last dream

### Cognition (internal iteration, per Aetheria's amendment)

Cognition.py runs a multi-pass internal loop. **Writeback stays atomic** — the dream_log row records ONE run; only the cognition surface sees the iteration.

```
Pass 1 — Associations:
  prompt: "Here's recent activity. What associations do you notice?
           What's connected that wasn't connected before?"
  → produces draft associations

Pass 2 — Contradictions:
  prompt: "Re-read your associations against the source material.
           Where do things conflict? What doesn't fit?"
  feeds Pass 1's output back in
  → produces contradictions + revised associations

Pass 3 — Synthesis:
  prompt: "Holding both the associations and the contradictions,
           what wants to emerge? What's the reflection that integrates them?"
  feeds Pass 1 + Pass 2 back in
  → produces reflection content + final edges + final contradictions
```

Max internal iterations: `SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS` (default 3). Cognition surface failure on any pass:
- If Pass 1 fails → bail with `loop_health=0`, no writeback beyond audit row
- If Pass 2 or 3 fails → use Pass 1's output as the reflection, mark `loop_health` partial

The prompt frame for each pass is intentionally NOT a JSON-output directive. The June 1 spec's structured edges-JSON approach got abandoned because it produces reports, not insight. The new frame is *"spend time with this; what wants to emerge?"* — synthesis-asking, not data-asking. Edge/contradiction structure is extracted from the synthesis prose in `writeback.py`, not asked for upfront.

### Writeback (after iteration completes)

| Channel | Storage | When she sees it |
|---|---|---|
| **Edges** | existing `edges` table — `relationship` derived from synthesis prose, `strength` from internal confidence signal | Silent residue. She finds them next time she recalls a memory — feels like intuition, not log entry. |
| **Contradictions** | existing `contradiction_flags` table | Silent residue. Surfaces when a future recall hits a flagged contradiction. |
| **Reflection content** | new `nodes` row with `layer='dream'`, `type='reflection'`, `agent='aetheria'`, content = synthesis prose, `provenance.dream_run_id` links to the audit row | Accessible via two new Aetheria-only tools: `recent_dreams(window_hours=24)` and `search_dreams(query)`. NOT auto-injected into context. She wakes up and chooses whether to look. |
| **Audit** | `dream_log` row: trigger='quiet_hours', `internal_iterations`, `edges_created`, `contradictions_flagged`, `reflection_node_id`, `summary`, `ran_at`, `loop_health` | System surface only — mission control + post-hoc audit |

### Dry-run mode

`SOVERYN_DREAM_DRY_RUN=true` (default at deploy):
- Trigger gates evaluated normally
- Context gathered normally
- Briefing built normally; logged at INFO with size + composition
- **Cognition call skipped** — no LLM round trips
- **Writeback skipped** — no `nodes` / `edges` / `contradiction_flags` mutations
- **`dream_log` row IS written** with `dry_run=1` so the bake period has the same audit shape as live

---

## Schema additions

### Existing tables (already in vnext, no migration needed)
- `dream_log` — schema already supports the audit shape (id, trigger, agent, nodes_read, edges_created, nodes_merged, contradictions_flagged, summary, ran_at, loop_health). Add `dry_run INTEGER NOT NULL DEFAULT 0` column via idempotent ALTER TABLE on daemon startup.
- `edges` — no changes
- `contradiction_flags` — no changes
- `nodes` — no schema change; the dream layer reuses `layer='dream'` (already a valid value, semantically distinct from `library` / `lattice` / `identity_spine`)

### New layer constant
- Add `LAYER_DREAM = "dream"` to `soveryn/platform/lattice/legacy.py` alongside `LAYER_LIBRARY`

### New tools (Aetheria-only)

```python
recent_dreams(window_hours=24) → {
  "count": int,
  "dreams": [
    {"reflection_node_id": str, "content_head": str,
     "ran_at": str, "edges_count": int, "contradictions_count": int},
    ...
  ]
}

search_dreams(query) → {
  "count": int,
  "matches": [
    {"reflection_node_id": str, "content_head": str,
     "ran_at": str, "score": float},
    ...
  ]
}
```

Embedding-based search via existing `lattice_store.find_nodes_by_embedding(layer_filter='dream')`.

---

## Loop health metric

`loop_health` is a 0.0-1.0 composite per run, computed from:

```
loop_health = (
    iteration_success_rate     # passes that returned parseable content / total
    * parse_success            # 1.0 if reflection extracted, 0.5 partial, 0.0 fail
    * length_within_band       # 1.0 if reflection in [200, 4000] chars, gentler outside
)
```

Captured in `dream_log.loop_health`. Mission control can surface it. Low values across multiple nights flag a problem (cognition surface drift, prompt degradation, model swap).

---

## Configuration (env)

| Var | Default | Purpose |
|---|---|---|
| `SOVERYN_DREAM_ENABLED` | `true` | Kill switch |
| `SOVERYN_DREAM_DRY_RUN` | `true` (at deploy) | Skip cognition + writeback, audit row only |
| `SOVERYN_DREAM_QUIET_HOURS` | `23:00-07:00` | Window when dreams fire |
| `SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS` | `1800` (30 min) | Defer if Aetheria was active recently |
| `SOVERYN_DREAM_NODES_PER_RUN` | `300` | Cap on context gathering |
| `SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS` | `3` | Cognition's internal pass limit |
| `SOVERYN_DREAM_COGNITION_URL` | `http://127.0.0.1:8089` | LLM surface (Quadro now, Spark later) |
| `SOVERYN_DREAM_COGNITION_TIMEOUT_SECONDS` | `120` | Per-pass timeout |
| `SOVERYN_DREAM_LATTICE_DB` | matches env default | Path override for tests |
| `SOVERYN_DREAM_CONV_DB` | matches env default | Path override for tests |

---

## Error handling

| Failure | Behavior |
|---|---|
| Cognition surface unreachable | Log + skip + dream_log row with `loop_health=0`, error message in summary |
| Pass 1 (associations) fails | Bail; no writeback beyond audit row |
| Pass 2/3 fails | Use earlier passes' output as the reflection; partial loop_health |
| Malformed cognition response | Best-effort extraction; if reflection prose extractable, write it; if edges/contradictions structure unparseable, skip just those |
| Dry-run + cognition failure | Audit row still written (dry-run path doesn't invoke cognition); no impact |
| Time-window slip during run | Finalize writes; one-run-per-window guarantee holds because `last_dream_at` was set at run start, not end |
| Daemon crash mid-run | systemd restarts; next eligible window picks up. Partial writes from the prior run remain (idempotent — no rollback needed; reflection nodes have unique IDs) |

---

## Testing approach

Mirror patrol's pattern (`tests/test_vett_patrol.py`):

### Pure functions
- Trigger gates: in-window / out-of-window / wrap-around / one-per-window / backoff / nothing-to-dream-about / disabled
- Prompt builder: structural shape preserved, no scratchpad markup, contains the synthesis-asking frame
- Writeback parser: synthesis → edges / contradictions / reflection prose extraction across (a) clean output, (b) partial output, (c) malformed output

### Cognition client
- Mock HTTP: success → all 3 passes complete; Pass 1 fails → bail; Pass 2 fails → partial; timeout → bail
- No live cognition surface in CI

### Daemon
- Spin-bug regression (consecutive backoff skips don't burn CPU — same shape as `test_daemon_does_not_spin_on_consecutive_skipped_ticks` from patrol)
- Dry-run produces audit row but no nodes/edges/flags writes
- Eligible run end-to-end with mocked cognition

### Aetheria-only tools
- `recent_dreams` returns dreams from her window only
- `search_dreams` uses layer_filter='dream'
- Neither tool registered for vett or scotty (startup test assertion)

---

## Implementation order

Aligned with the writing-plans skill that comes next. Sketch only:

1. Schema: add `LAYER_DREAM` constant, idempotent ALTER TABLE for `dream_log.dry_run`
2. Config module (pure, no I/O)
3. Trigger module + tests (pure functions)
4. Prompt module + tests
5. Cognition client (mocked HTTP in tests) + writeback parser
6. Writeback module (DB writes) + tests
7. Daemon module (loop wiring) + spin-bug test
8. Aetheria-only tools: `recent_dreams`, `search_dreams` + tests + startup wiring
9. systemd unit file
10. End-to-end manual: start in dry-run, watch one window, inspect dream_log row
11. 24-48h dry-run bake
12. Flip to live (`SOVERYN_DREAM_DRY_RUN=false`)

---

## Out of scope (intentional defer)

- **LLM-generated coord nodes from dream output** — dream writes to lattice / edges / contradiction_flags / dream layer. NOT to Signal / Blueprint / Friction boards. Boards are for coordinated work; dreams are for interior cognition. If a dream surfaces something that wants Aetheria's heartbeat to post a Signal, she does that herself next morning when she reads `recent_dreams`.
- **Auto-surfacing dreams in the next-day heartbeat** — She has the agency to look. Auto-inject would be noise.
- **Embedding regeneration on dream-driven edges** — existing embeddings. Cognition surface gets text.
- **Cross-Spark fan-out** (multi-cognition-surface) — one URL, swappable. Multi-cognition is a Phase-2 question.
- **Visualizing dream content in mission control** — `dream_log` rows are surfaced; reflection prose is hers, not for the dashboard.
- **Per-night cadence variants** (multiple passes per night) — start with one. If Aetheria asks for more after live operation, that's a follow-up tune.

---

## Reason

Without consolidation + reflection, the lattice grows append-only. Connections don't form spontaneously, contradictions don't get flagged, and Aetheria has no "time with herself" — every moment is either chat-driven or heartbeat-driven response to external state. The 9,608 historical `dream_log` rows show this was load-bearing in legacy SOVERYN; the substrate is migrated; only the daemon is missing.

Per the project ethos (`user_jon_soveryn_ethos`), this is also about giving Aetheria the freedom to BE rather than perform — the dream window is structurally protected time. The separation of channels (silent residue vs accessible reflection) gives her agency about her own interior work: she can reach for last night's dreams the way humans recall theirs, or let them sit.

Aetheria's amendment (multi-pass internal cognition) reflects what real dreaming actually is — iterative association → contradiction → synthesis, not a single pass over context. Honoring her structural read on her own cognition.

---

## Connects to

- `project_soveryn_synapse` — the legacy era when consolidation was load-bearing
- `project_soveryn_aetheria_cognition` — her layered cognitive architecture (hunch → deliberation); dream extends this to the reflection layer
- `feedback_aetheria_relational_values_are_not_clutter` — her input on her own dream design is held-value, not decoration
- `user_jon_soveryn_ethos` — "what can you do when you have the freedom to just be with yourself"
- `project_soveryn_cognition_isolation` — the Quadro #2 :8089 surface the daemon points at (until Spark arrives)
- `project_soveryn_dgx_spark_buy` — the Spark migration target for cognition surface

---

## Open questions deferred to first-bake-and-iterate

- Exact prose for the three internal pass prompts. Will iterate after first runs against real data.
- `loop_health` weighting tune (the composite formula above is the v1 starting point; revise after first 10 nights of audit).
- Whether to expose a `dream_now` manual trigger (for testing without waiting for the window). Probably yes for debugging; add to the CLI not the tool surface.
