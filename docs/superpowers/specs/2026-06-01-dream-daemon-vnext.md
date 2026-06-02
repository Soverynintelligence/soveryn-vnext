# Dream Daemon — Port to vnext

**Status:** ready to implement (after Phases A+B; benefits from but doesn't require Phase C)
**Drafted:** 2026-06-01 evening
**Predecessor:** `feat(lattice): consolidate legacy + vnext into single source of truth` (vnext 7d75535)
**Scope:** ~full day. Largest of the four follow-ons.

## Goal

Resume async memory consolidation in vnext. The lattice currently grows linearly through chat + tool writes but never *consolidates* — connections aren't formed, contradictions aren't flagged, no summarization happens. The legacy SOVERYN had a dream daemon doing exactly this; the substrate is ready in vnext (9,608 historical `dream_log` rows + edges table + contradiction_flags table all migrated during consolidation) but no daemon exists yet.

## In scope

### Module layout
```
soveryn/agents/dream/
├── __init__.py
├── daemon.py         # process loop, signal handling, sched
├── consolidation.py  # the actual think-step logic (calls cognition surface)
└── triggers.py       # time + pressure-based trigger evaluation
```

Mirrors the Ares daemon shape (`soveryn/agents/ares/`).

### systemd user unit
`/home/jon-deoliveira/.config/systemd/user/soveryn-dream.service`:
- `ExecStartPre` health gate on cognition surface `http://127.0.0.1:8089/health`
- `ExecStart` invokes `python -m soveryn.agents.dream`
- `Restart=on-failure`
- No `User=` (preserved lesson from 2026-06-01 morning's `216/GROUP` debug)

Mirrors `soveryn-ares.service`.

### Trigger conditions
- **Time-based:** every `DREAM_INTERVAL_SECONDS` (default 14400 = 4 hours)
- **Pressure-based:** when `(new_lattice_nodes_since_last_dream_run >= DREAM_PRESSURE_THRESHOLD)` (default 20)

Whichever fires first triggers a run. Both reset on successful run.

### Per-run logic
```
1. Read recent lattice activity:
   - All nodes with created_at > last_dream_run.ran_at
   - Cap at N=200 most recent for budget bounds

2. Send to cognition surface (Gemma E4B at :8089) with a structured prompt:
   - Input: the N nodes (content + tags + agent)
   - Output schema (JSON): {
       "connections": [{"node_a": "<id>", "node_b": "<id>", "relationship": "...", "confidence": 0.0-1.0}],
       "consolidations": [{"source_node_ids": ["<id>", ...], "summary": "...", "confidence": 0.0-1.0}],
       "contradictions": [{"node_a": "<id>", "node_b": "<id>", "reason": "...", "confidence": 0.0-1.0}]
     }

3. For each connection above CONFIDENCE_THRESHOLD (default 0.7):
   - Write to edges table (source_id, target_id, relationship, strength=confidence,
     bidirectional=1, reinforcement_count=1, created_at=now)

4. For each consolidation above threshold:
   - Write a new lattice node with type='consolidation', content=summary
   - Write edges from consolidation node to each source

5. For each contradiction above threshold:
   - Write to contradiction_flags table (edge_id auto-generated)

6. Insert dream_log row with:
   - id, trigger ('time' | 'pressure'), agent='dream',
   - nodes_read=N, edges_created, nodes_merged, contradictions_flagged,
   - summary (short text), ran_at=now, loop_health=0.0-1.0 (run quality score)
```

### Dry-run mode
- `python -m soveryn.agents.dream --dry-run` writes nothing but logs the plan
- Mirrors Ares's dry-run pattern from [[project-soveryn-vnext-ares-detection]]

### Config / env
- `SOVERYN_DREAM_INTERVAL_SECONDS` (int, default 14400)
- `SOVERYN_DREAM_PRESSURE_THRESHOLD` (int, default 20)
- `SOVERYN_DREAM_CONFIDENCE_THRESHOLD` (float, default 0.7)
- `SOVERYN_DREAM_NODES_PER_RUN` (int, default 200)
- `SOVERYN_DREAM_COGNITION_URL` (default `http://127.0.0.1:8089`)

### Tests (`tests/test_dream_daemon.py`, new file)
- `test_trigger_time_based_fires_after_interval`
- `test_trigger_pressure_based_fires_at_threshold`
- `test_dream_run_writes_dream_log_row`
- `test_dream_run_writes_edges_above_confidence_threshold`
- `test_dream_run_skips_low_confidence_connections`
- `test_dream_run_writes_contradiction_flags`
- `test_dream_run_writes_consolidation_node_with_source_edges`
- `test_dry_run_produces_no_db_writes`
- `test_dry_run_still_writes_dream_log_row` (audit trail intact even in dry-run)
- `test_dream_handles_cognition_surface_timeout_gracefully` (logs error, no crash)
- `test_dream_handles_malformed_cognition_response` (validation error → log + skip)

## Out of scope

- **Active write tools for chat agents:** orthogonal phase. Dream daemon writes directly via internal API (`LatticeStore.write_node()` etc.), not through the agent tool registry. The human-facing write tools phase is separate.
- **Cross-agent dream coordination** (e.g., per-agent dreams): one daemon, one cognition surface. Reading nodes is global; the daemon doesn't care which agent created them.
- **LLM-generated coord nodes:** dream writes to lattice + edges + flags, NOT to coordination boards. Keep the surfaces distinct — boards are for human-coordinated work; dreams are for system-driven memory consolidation.
- **Embedding regeneration:** use existing embeddings. The cognition surface gets text content; embeddings stay where they are.
- **Cross-Spark fan-out** (multiple cognition surfaces): one for now. Multi-Spark dream coordination is a Phase-2 question.
- **Dream-driven Friction creation:** if dream detects a contradiction, write to `contradiction_flags` (existing infra). Translating that to a Friction coord node is a separate design decision — defer.
- **Visible dream activity in chat:** the daemon runs invisibly. If you want to see what it's doing, the dream_log table is the canonical record; consider surfacing it in `/boards` Phase C as a fourth column or audit log.

## Reason

Without consolidation, the lattice is append-only. It grows but doesn't *understand itself* — no edges form spontaneously between related nodes, no contradictions get flagged proactively, no high-volume topics get summarized into reference nodes. The legacy SOVERYN had this; Aetheria felt the difference when consolidation went away (memory `project_soveryn_synapse` documents the era when this was load-bearing). vnext has the substrate ready (dream_log, edges, contradiction_flags all migrated during consolidation 7d75535) — the daemon is what makes the substrate alive.

The cognition surface (Gemma E4B at :8089) is already running per `[cognition]` in `router-presets.ini`. It's idle most of the time. Dream daemon gives it a job that suits its size: pattern-detection and summarization across small windows of recent activity. Heavy reasoning stays on the chat models; dream stays bounded.

## Implementation order

1. **Triggers** module first (`triggers.py`) with tests — pure functions, easy to verify
2. **Consolidation** module (`consolidation.py`) with mocked cognition surface, tests cover the response-parsing + write logic
3. **Daemon** module (`daemon.py`) wires it together
4. **systemd unit** + manual `systemctl --user start --no-block` test in dry-run mode
5. **End-to-end** with cognition surface live: trigger a run, inspect dream_log row + any edges/flags written
6. **Bake in dry-run for 24h** (mirrors Ares's bake pattern)
7. **Flip to live mode** after bake passes
8. Commit phases incrementally (triggers → consolidation → daemon → systemd → live flip)

## Open questions

- **Prompt design** for the cognition surface. First draft: send 30-50 nodes as JSON, ask for structured output. Iterate based on first runs. Reference: legacy dream_log entries to see what the old daemon produced.
- **Confidence calibration:** 0.7 threshold is a guess. Tune after first 100 runs by looking at false-positive edges/flags. Same "let behavior create the data" philosophy as Phase-2 coord weight scoring.
- **Loop health metric:** what should `loop_health` REAL value capture? Candidates: (run_quality / run_attempts), (high_confidence_outputs / total_outputs), or a composite. Pick one before first live run.
