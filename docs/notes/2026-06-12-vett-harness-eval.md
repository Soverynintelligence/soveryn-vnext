# Vett Harness Port — Phase 1 Eval Results (2026-06-12)

**Task:** `cross_source_link`
**Topic:** SOVERYN's local-first, multi-agent architecture
**Claim:** SOVERYN is a fully-local multi-agent system that runs without
external API dependencies and is composed of distinct agents (Aetheria,
Vett, Scotty, Ares, Scout), each with a specific role.
**Expected evidence IDs (4):**
- `7e406410-09d3-43ee-b953-00339dfe626c` (Aetheria-authored canonical
  system-reference summary; library layer)
- `f5c9ccca-eeb0-4200-a5a9-9d136952a00b` (Chronicle §V "The Council":
  names the agents with models and roles)
- `92273e8c-2c32-4ee2-bc6b-f07deb6d613d` (Chronicle §V→§VI bridge: local
  hardware commitment "no cloud, no terms of service, no alignment tax")
- `86dde660-c31a-4641-a91a-f5ad8d226ca8` (Chronicle §VII lead-in: the
  336 GB VRAM hardware-locality fact)

## Setup

- **Vett-in-harness:**
  `python -m soveryn.agents.vett.harness.run_eval --task cross_source_link
  --max-turns 20 --layer-filter library`
  - Branch: `vett-harness-phase1` at `7ed7ea1` (Task 12), with Task-13
    telemetry refinements added on top of that.
  - Router: `http://127.0.0.1:8090` (`model=vett-scotty`).
- **Vett-current baseline:** vnext app `/chat` (HTTP POST to
  `127.0.0.1:5001/chat` with `agent=vett`). This routes through the
  normal `AgentLoop` — full persona, recall pipeline, and live tools as
  Vett currently runs them. Session id
  `22dedb4c-0406-4aa2-b181-e2bf591aad18`.
- **Lattice DB:** `~/soveryn_vnext/data/memory/lattice_vnext.db` (live).
- **Eval-time commit:** `vett-harness-phase1 @ 7ed7ea1` + Task-13 patch.

## Vett-in-harness results

- **Wall time:** 107.86 s
- **Turn count:** 3 (≪ 20-turn budget)
- **Tool-call breakdown:**
  `{fan_out_search: 1, read_document: 1, user_text: 1}`
- **reached_stop:** **True** (Task-13 refinement detects the
  natural-stop signal — last action is `user_text` and no further tools
  were called). The Task-10 placeholder would have reported False.
- **evidence_promoted:** 0 (no curated-evidence slot exists on the
  vendored Trajectory; scored qualitatively below)
- **Failure-mode flags:** `turn_cap_hit=False`, `zero_promotion=True`,
  `tool_diversity_collapse=False`, `tool_error_count=0`
- **Coverage of expected IDs: 1 / 4**
  - `7e406410…` mentioned 11 times (surfaced via fan_out_search, then
    explicitly read via read_document, then quoted in the user_text)
  - `f5c9ccca…`, `92273e8c…`, `86dde660…` — never surfaced in any
    fan_out_search top-3
- **Verification verdict (quoted):**
  > "the claim is **fully supported** by the lattice evidence."
  > "The evidence from document `7e406410-…` provides a direct and
  > complete verification of the claim. No further search is required."
- **Trajectory shape:**
  1. User observation (the task query).
  2. Action: `fan_out_search` with three reasonable query framings
     (`"SOVERYN local-first multi-agent architecture"`,
     `"SOVERYN fully-local multi-agent system without external API
     dependencies"`,
     `"Aetheria Vett Scotty Ares Scout agents SOVERYN"`).
  3. Observation: every query returned the same canonical reference
     node — net unique IDs surfaced = **1**.
  4. Action: `read_document` for the canonical node.
  5. Observation: full text of the canonical node (which the search
     observation had already shown).
  6. Action: `user_text` — verification answer + natural stop.

## Vett-current (baseline) results

- **Wall time:** 127.12 s
- **Tokens:** `prompt=12106` (`cached=3293`), `completion=1734`,
  `total=13840`. `finish_reason=stop`.
- **Tool calls visible in `/chat` response:** `null` (the AgentLoop's
  internal recall/retrieval calls aren't surfaced via `/chat`'s
  response payload — they happen inside the loop before the model
  emits its assistant turn).
- **Coverage of expected IDs: 3 / 4**
  - `7e406410…` (Source A: "Migration Smoke Test Summary")
  - `f5c9ccca…` (Source B: "How We Became SOVERYN" — Council section)
  - `92273e8c…` (Source C: "How We Became SOVERYN" — What We Are
    Building section)
  - `86dde660…` — not cited. Vett substituted a DIFFERENT chronicle
    chunk (`de0d4423-e411-443c-982f-fad905d352da`, "Conclusion") as
    her fourth source.
- **Verification verdict (quoted):**
  > "**SUPPORTED, with one named discrepancy**" — and then names
  > Tinker (Scotty's prior name) as the discrepancy between the §V
  > Council roster and the current-state Source A roster. Vett also
  > produced a cross-document consistency table.
- **Notes on shape:** one assistant turn from the user's perspective,
  but recall+retrieval happened inside the AgentLoop before the
  visible reply — no tool-call trace is exposed in `/chat` output.

## Comparison table

| Axis | Vett-current | Vett-in-harness |
|---|---|---|
| Wall time | 127 s | 108 s |
| Expected ID coverage | **3 / 4** | **1 / 4** |
| Cross-source synthesis | Yes (table; named discrepancy across A/B) | No (single source) |
| Explicit tool trace | None (opaque) | Yes (3 actions, 1 observation, terminal text) |
| Verification verdict shape | Per-component table | Per-component prose |
| Natural stop signal | n/a | **True** (telemetry-confirmed) |
| Trajectory replayability | No | Yes (`eval_runs/*_harness.json`) |

## Verdict against phase 1 success bar

The spec's success bar:
> "Phase 1 succeeds if Vett-in-harness **matches** Vett-current on
> representative SOVERYN tasks while producing cleaner evidence state
> (candidates, curated set, verification records, evidence links).
> Beating Vett-current is the home run; matching with better
> traceability is still a phase 2 trigger."

### Verdict: **FAIL** on the matching bar.

Vett-in-harness retrieved **1 of the 4 expected evidence IDs**, against
Vett-current's **3 of 4**. The harness verdict was logically correct
("fully supported") but reached on materially thinner evidence — a
single source — where Vett-current cross-checked four. On the
representative SOVERYN cross-source task this eval was designed to
measure, the harness path under-matched and the **answer quality is
visibly worse**, which is the explicit fail condition in the spec.

### Where the failure actually sits

Honest read of the trajectory: the architecture worked end-to-end on
the first run against a representative SOVERYN task. The harness
issued a sensible fan-out, read the top hit, verified the claim, and
naturally stopped in 3 turns. The seam (vendored Agent + lattice tools
+ chat-completions inference model + llama-server tool format) is
functional under live conditions.

The **bottleneck was retrieval depth, not orchestration.** All three
of Vett's fan_out_search query framings returned the same canonical
reference node as top-1 — and with `DEFAULT_FAN_OUT_K=3` per query,
the chronicle chunks never made the cut for any of the framings. The
canonical node was reranked to the top of all three result sets, then
deduplicated by the model itself when reading the observation.

Concretely tunable surfaces — none of these change the architecture:
- Bump `DEFAULT_FAN_OUT_K` above 3 (e.g., 6–8) so chronicle chunks
  reach the model's working set.
- Add MMR / cross-document diversity to fan_out (penalize already-seen
  IDs across the per-query slates).
- Reformulate query expansion to bias toward chronicle-shaped framings
  (the queries the model wrote were all reference-style framings; the
  chronicle is narrative).
- Or simpler: do not exit at the first verification-positive. Give the
  model a "find at least N independent sources" prompt nudge.

None of these are harness-architecture problems. The harness happily
auto-drove a 3-turn trajectory in 108 s, stopped naturally, and
reported it honestly. The retrieval surface it's sitting on top of is
just too thin at the default `k`.

That said — **the spec's bar is the spec's bar**, and on this single
representative task the harness's answer quality lost to baseline. I'm
calling this FAIL rather than PASS for that reason.

## Honest caveats

- **Single eval task.** One task, with 4 expected IDs, is a coarse
  scoreboard. A more confident verdict would need 3–5 tasks with
  different retrieval shapes. Phase-1 plan deliberately scoped to one;
  honest about the limit.
- **Single-author corpus.** All 4 expected IDs are Aetheria-authored
  library nodes (system reference + chronicle chunks). True
  cross-author linking wasn't possible given how thin the library
  layer is right now. This was flagged in Task 11 discovery; it
  remains a real limit on what `cross_source_link` actually measures.
- **Vett-in-harness was not harness-trained.** Phase 1 explicitly tests
  the architecture alone — same Vett weights driving the harness as
  driving `/chat`. The spec called this out: phase 3 (SFT/RL) is what
  would close the weight-architecture gap. So this FAIL is on the
  weights+default-prompts combo, not on the harness as such.
- **Vett-current path is opaque.** The `/chat` response surfaces a
  finished answer and `tool_calls=null` — Vett's recall/retrieval is
  inside the AgentLoop and we can't see what she actually retrieved.
  The harness's trajectory JSON is, in contrast, fully inspectable.
  This is exactly the "cleaner evidence state" axis the spec named —
  the harness wins that axis on every run, just not loud enough to
  outweigh the answer-quality gap.
- **Telemetry placeholders:** `evidence_promoted` is still 0 because
  the vendored Trajectory has no curated-set slot. Scored
  qualitatively. The other two flagged refinements (Task 13 work)
  ARE in this run:
  - `reached_stop` now reflects the real natural-stop signal (last
    action is `user_text` only) — the eval shows True, which is
    correct.
  - `tool_diversity_collapse` is now gated on `total_calls >= 3` so
    it won't false-positive on the trivial 1/1 ratio that the smoke
    task produced.

## Recommendation

**Do not proceed to Phase 2 yet.** The architecture is sound and the
seam is verified live, but the answer-quality gap on this task is
real. Two cheaper iterations before committing to wiring this into
Vett's normal task surface:

1. **Bump retrieval depth + add cross-doc diversity** to fan_out_search
   in `lattice_tools.py`. Re-run `cross_source_link`. If 4/4 (or 3/4)
   coverage emerges, the FAIL→PASS flip is mostly a tuning result.
2. **Add 2–3 more eval tasks with varied retrieval shapes** — e.g., a
   single-source verification, a refutation task, a task whose answer
   requires reading across two clearly distinct authors. One coarse
   eval is not enough signal to drive a phase-2 decision either way.

If iteration (1) closes the coverage gap and iteration (2) confirms
across multiple tasks, then Phase 2 (wire into Vett's normal task
surface) is justified. **Phase 3 (SFT/RL on harness trajectories)
should be deferred** until Phase 2 demonstrates the architecture
producing meaningfully cleaner / more traceable answers in real use —
that's the real Phase-3 trigger, not single-task coverage parity.

The architecture earned a "promising but not proven" — not a
greenlight, not a rejection.

## Trajectory artifacts

- Vett-in-harness:
  - Trajectory: `eval_runs/20260612_142946_harness.json`
  - Telemetry stderr: `eval_runs/20260612_142946_harness.stderr`
- Vett-current baseline:
  - Response: `eval_runs/20260612_142946_baseline.json`
  - Stderr: `eval_runs/20260612_142946_baseline.stderr`

## Telemetry-refinement decision

**Applied (both)** in this commit:
- `tool_diversity_collapse` gated on `total_calls >= 3`
  (`TOOL_DIVERSITY_MIN_CALLS = 3` in `run_eval.py`).
- `reached_stop` now derived from
  `_trajectory_reached_natural_stop()` — mirrors the vendored
  `Agent._finished_with_user_text` check (vendor/agent.py:960-968).

Both are small, isolated changes with unit-test coverage in
`tests/test_vett_harness_run_eval.py`. They affect this verdict in
exactly one place: the harness telemetry line correctly reports
`reached_stop=True` on this run (it would have been False under the
placeholder), which contributed to the read that "the architecture
worked end-to-end."
