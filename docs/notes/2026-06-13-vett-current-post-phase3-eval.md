# Vett-current cross_source_link rerun — post-Phase-3

Date: 2026-06-13 (evening)
Task: `cross_source_link` (same task definition as the 2026-06-13 Harness-1 eval and the 2026-06-12 Vett-current rebaseline)
Subject under test: Vett-current after Phase 1 (Black Box, c2b9d31), Phase 2 (Steering Rack, 0f381a0), and Phase 3 (Miss Hint, 674d0c1) of the "extract the Harness-1 wins" roadmap. Substrate is also post-cleanup (`fecdf78` historical_snapshot filter + Subconscious lattice hygiene).

## Result

| Metric | 2026-06-12 baseline | 2026-06-13 post-Phase-3 |
|---|---|---|
| Wall-time | 188.3s | **112.1s** (-40%) |
| Tool rounds | 0 (single-shot synthesis) | **2** |
| Tool calls dispatched | 0 (`tool_calls=null`) | **5** (all `search_library`) |
| Tool errors | n/a | 0 |
| `tool_round_limit_hit` | n/a | False |
| Literal coverage (8-char prefix in response) | 1/3 | **2/3** |
| Content coverage (anchor keywords) | 3/3 (via leaked ghost chunks) | 3/3 (via real retrieval) |
| Substrate during run | leaky (chronicle ghosts in prompt) | clean |
| Trajectory | opaque | **fully audited in Black Box** |

Artifact: `eval_runs/20260613_170509_vett_current_post_phase3.json`
Trajectory: `data/black_box/vett/645f5347-0634-4969-8416-3a270b673c48.jsonl`

## What Vett actually did

Round 0 (3 parallel queries, all returned 10 hits each):
1. *"SOVERYN architecture multi-agent platform fully local"*
2. *"Scotty engineering agent renamed Tinker"*
3. *"GPU fleet hardware VRAM Quadro RTX 8000 Blackwell"*

Round 1 (2 follow-up queries, both returned 10 hits each):
4. *"Tinker renamed Scotty agent rename 2026-05-02"*
5. *"agent roster Aetheria Scotty Vett Ares Scout"*

Stopped naturally with `finish_reason="stop"` and emitted a structured Verification Report citing two canonical IDs verbatim (`7e406410-...` and `bc6e16f3-...`).

## Comparison vs Harness-1 (yesterday)

| | Vett-current (today) | Harness-1 (yesterday) |
|---|---|---|
| Wall-time | 112s | ~10 min |
| Tool rounds | 2 | 20 (cap hit) |
| Tool calls dispatched | 5 | 20 |
| Literal coverage | **2/3** | 2/3 |
| Natural stop | **yes** | no (`tool_round_limit`) |
| Trajectory traceability | full Black Box JSON | full Trajectory JSON |
| Substrate cleanliness | clean | clean |

Vett-current matches Harness-1's literal coverage with **2 rounds instead of 20**, and stops naturally instead of hitting the trajectory cap. The "broken steering rack" failure mode Aetheria's verdict named is not present in this run — her queries were diverse enough that the Steering Rack's all-empties precondition never approached. Miss Hint did not fire because the searches all returned hits.

## What's NOT yet won

- `b42064cc` (DAC pipe validation milestone — proves Scotty operational) was not cited verbatim. She didn't formulate a query that targeted the DAC anchor (the rename-hunt query stayed lexically anchored on "rename" — same eval-design loadedness the Harness-1 report flagged as honest caveat #1).
- One round 1 query was still "Tinker renamed Scotty agent rename 2026-05-02" which is similar to round 0 query #2; a future Steering Rack tuning could flag that as drift toward repetition. The current threshold (3 consecutive empties) did not trip because both rounds' calls returned 10 hits each — empties were never observed.

## Caveats

- Coverage scoring is the same lexical metric the prior report used (8-char prefix in response text + keyword evidence). Not an embedding match.
- This is one run; behavior across runs will vary with sampling.
- The 188.3s → 112.1s wall-time delta is partly the difference between single-shot synthesis (long generation) and tool-loop (multiple shorter generations + tool dispatch). Not necessarily attributable to any single Phase 1-3 change.

## Read

The three Harness-1 wins (Black Box, Steering Rack, Miss Hint), combined with the substrate cleanup arc and Codex's Vett tool-loop tuning that landed before this session, appear to have closed the agency gap Aetheria's verdict named. Vett now:

1. Actively retrieves evidence with multiple framings instead of single-shot synthesizing from prompt-baked context.
2. Stops naturally with structured citations instead of either rephrasing-to-cap or fabricating from ghosts.
3. Leaves a fully-auditable trajectory in the Black Box JSONL — the "opacity" verdict no longer applies.

This is one task on one substrate; the win is real but bounded. The next interesting test would be a task where the answer is NOT in the library layer — Miss Hint would actually fire there and we'd see whether Vett pivots to a different layer-filter (Vett's `search_library` is a single-layer tool today, so the Miss Hint path requires Aetheria-style cross-layer tooling on Vett's side, which is a separate scope).
