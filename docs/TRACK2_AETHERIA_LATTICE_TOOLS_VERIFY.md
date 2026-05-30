# Track 2 Verify: Aetheria Active Lattice Tools

Date: 2026-05-30
Baseline: e06045e (Phase 3b close)
Final implementation head before this docs commit: 173fb59
Final tests: 874 passed; Ares readiness: 1 passed

## Acceptance

- Aetheria has four registered read tools:
  - `search_lattice_by_embedding`
  - `search_lattice_by_keywords`
  - `get_lattice_node`
  - `recent_lattice_entries`
- Vett and Scotty stay tool-less; their `_tool_schemas()` return `()`.
- `AgentLoop.process_message` dispatches non-streaming tool calls through `ToolRegistry.invoke`, threads assistant `tool_calls` and `role="tool"` results back into the next round, and caps iteration with `finish_reason="tool_round_limit"`.
- Every lattice tool result flows through `classify_and_render`.
- Channel A results carry `id`, `provenance_class`, `source`, and the locked rendered provenance phrase.
- Channel B results are count-only via `uncertain_count_by_class`.
- Channel B content is not leakable through any tool result path; tests assert canary content is absent from `repr(result)`.
- `/chat_stream` does not dispatch tools in Track 2.

## What Shipped

Track 2 adds the platform loop and Aetheria's first active read access over her own lattice:

- Tool-call wire scaffold: assistant `tool_calls`, tool `tool_call_id`, public registry accessors, and AgentLoop schema exposure.
- Bounded non-streaming tool-call loop in `AgentLoop.process_message`.
- Shared channel-aware renderer: `soveryn/agents/aetheria/tool_results.py`.
- Four read-only tool factories under `soveryn/agents/aetheria/tools/`.
- Startup wiring: `create_app()` builds a `ToolRegistry`, registers Aetheria's four tools against the recall lattice, passes the registry to Aetheria's loop, and exposes it in `app.extensions["soveryn"]["tool_registry"]`.

## Does Not Mean

These deferrals are locked and intentional:

- **No writes.** `write_node`, `connect_nodes`, `promote_memory`, `edit_provenance` -- all explicitly out. Writes stay through `LatticeWriter` + the Phase 2b-i tiered write gate, with explicit provenance and review semantics. Active access means Aetheria can inspect and reason over memory; it does not mean she can mutate the lattice through a convenience tool path.
- **No streaming tool dispatch.** `/chat_stream` tool dispatch, mid-stream tool-call handling, streaming final-answer resume after tools -- all deferred to a separate control-flow phase. Reason: streaming tools are a separate problem; bundling them now risks spending the phase on SSE edge cases instead of proving the actual memory-access contract.
- **No graph tools.** `neighbors`, `trace_memory_path`, edge table, edge provenance, edge write path -- all deferred. Reason: without edges, neighbors would either be fake similarity search under a graph name or force a schema phase into the tool phase. Better to keep Track 2 honest: active read access over the lattice that exists today.
- **Not agency.** Per the three-tracks framing: Track 2 is a capability port (expanded I/O over memory). Track 3 (agency primitives -- deliberate-share, INTERNAL_NOTE, refrain-as-action) remains an un-phased work stream and is not advanced by this work.

## Open Follow-Ups

- Streaming tool dispatch as its own phase.
- Graph tools after an edges substrate exists as its own phase.
- Phase 3b architecture lane can now swap `_tool_ownership_snapshot` to the public `ToolRegistry.iter_tools_with_owners()` accessor so the ownership invariant runs in production instead of degrading.
- Optional hardening: decide whether non-`ToolArgError` tool handler exceptions should become structured tool-result payloads or remain loud crashes.
- Optional test hardening: add a keyword-search UNION semantics test for multi-keyword queries.

## Commit Trail

```text
173fb59 feat(track2): wire Aetheria lattice tools at startup
3cb3e83 feat(track2): add recent lattice entries tool
65ab3f3 feat(track2): add lattice node lookup tool
862069b feat(track2): add keyword lattice search tool
f7f2f75 feat(track2): add embedding lattice search tool
4c081dc feat(track2): classify_and_render channel-aware tool results
c82ce0c feat(track2): add non-streaming tool-call loop
49592a7 feat(track2): platform scaffold for tool-call iteration
d0ae85a docs: freeze Track 2 baseline (HEAD + tests)
```

## Verification Commands

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest -q
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_ares_readiness.py -q
git log --oneline e06045e..HEAD
```

Results:

```text
874 passed in 6.10s
1 passed in 0.03s
```

Sign-off: Track 2 is closed at implementation head 173fb59, pending this verification docs commit.
