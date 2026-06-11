# Vett Harness Port — Phase 1 Design

**Date:** 2026-06-11
**Status:** Draft — ready for implementation-plan review. Three-voice review (Codex + Aetheria + Claude) converged on the same five answers; flips to Approved when Jon accepts the small edits.
**Origin:** Press piece on Harness-1 (UIUC + UC Berkeley + Chroma) led to architectural-pattern question rather than model swap.

## What this is

Port the Harness-1 retrieval orchestration pattern onto SOVERYN's existing Vett model (Qwen3.6-27B on Quadro #1) and the existing Synapse lattice, with no training, no production wiring, and no autonomous use. Measure the architectural lift on SOVERYN-representative retrieval tasks against Vett-current as the baseline.

The principle being tested: *the structural state-management of multi-step retrieval is doing meaningful work that's currently being asked of the model's context window.* If the principle holds for Vett (we proved it holds for Aetheria's prompt assembly earlier today — see [[project-soveryn-aetheria-prompt-cache-fix]]), it's the same architectural lever applied at a different layer.

## Goal

Determine whether the harness pattern *alone* — without harness-trained model weights — earns its keep on Vett's retrieval workload. Phase 1 succeeds if Vett-in-harness **matches** Vett-current on representative SOVERYN tasks while producing cleaner evidence state (candidates, curated set, verification records, evidence links). Beating Vett-current is the home run; matching with better traceability is still a phase 2 trigger.

## Scope

### In
- Vendor the harness/ Python module from `github.com/pat-jj/harness-1` into `soveryn/agents/vett/harness/vendor/` with Apache 2.0 LICENSE and NOTICE preserved
- Lattice adapter at `soveryn/agents/vett/harness/lattice_adapter.py` — pure read-through implementation of whatever vector-search interface harness/ultra_core.py expects, backed by soveryn/memory/lattice.py
- LLM client config patch pointing harness at our llama-server router (`/v1/completions` model="vett-scotty")
- Standalone CLI runner at `soveryn/agents/vett/harness/run_eval.py`, invokable as `python -m soveryn.agents.vett.harness.run_eval --task ...`
- SOVERYN-representative eval task definitions (multi-source claim-verification, cross-source linking, patrol-shaped queries against the lattice)
- Bounded turn budget (start at 20, default in the runner; raise via flag)
- Trajectory persistence to JSON for every run, for post-hoc audit
- Failure-mode telemetry: turn-cap hit, zero-promotion outcomes, tool-call diversity collapse, tool errors
- Smoke tests at `tests/test_vett_harness_smoke.py` proving the integration loads and runs end-to-end against a trivial task
- Comparison run: Vett-current vs Vett-in-harness on identical eval task; write-up at `docs/notes/2026-06-XX-vett-harness-eval.md` (date set when results land)

### Out (deferred to phase 2 or later)
- Any modification to `soveryn/agents/vett/research_surface.py` or `soveryn/agents/vett/patrol/` — Vett's normal task surface is untouched
- Any modification to `soveryn/agents/loop.py` — no AgentLoop integration
- Vett's patrol daemon — autonomous use stays on the current code path
- Aetheria, Scotty, cognition — Vett-only experiment
- Router preset changes — Vett's model serving unchanged
- Lattice write-back — harness reads candidates from lattice but does not promote curated evidence back into it (phase 2 territory)
- BrowseComp+ benchmark reproduction — only run if their corpus is trivial to obtain; not the meaningful question
- SFT or RL training on Vett — phase 3 only if phase 2 shows insufficient gap
- Any change to model weights, quantization, or routing
- Heartbeat or signal-bridge integration with the harness

### Reason
Strict isolation lets the phase 1 measurement be honest. If the harness pattern is doing real work, it'll show up as cleaner state + comparable or better answers in a CLI-runnable experiment. If it isn't doing real work, we throw away ~few days of glue code and learn something definite. Bleeding harness into Vett's normal task surface before measuring would make a regression look like a successful integration and contaminate the comparison.

## Architectural shape

| Component | Today (Vett-current) | Phase 1 (Vett-in-harness, CLI only) |
|---|---|---|
| Model | Qwen3.6-27B Q8 on Quadro #1, reasoning on | Same |
| Retrieval substrate | Lattice queries via Vett's existing tools | Lattice queries via harness's read-through adapter |
| State for multi-step research | In Vett's prompt context | In an in-memory `Trajectory` object + JSON dump |
| Tool surface | patrol_sources, BrowserFetch, web_search | Harness tools (search, read, tag, verify, promote, stop) — **lattice-only first pass**; web/patrol wrappers deferred unless vendored harness requires them to run |
| Entry point | Aetheria's `task_agent("vett", ...)` | Direct CLI runner, not wired to Aetheria |
| Bounded by | Vett's max_tokens, model's own stopping | Turn budget (start at 20) + harness's stop tool |
| Failure visibility | Vett either answers or doesn't | Trajectory JSON shows where in the loop she ended |

## Files touched

**New:**
- `soveryn/agents/vett/harness/__init__.py` (1 line)
- `soveryn/agents/vett/harness/vendor/` (their code, copied verbatim) — `agent.py`, `config.py`, `prompts.py`, `rerank.py`, `tasks.py`, `tools.py`, `trajectory.py`, `ultra_core.py`, `utils.py`, `__init__.py`
- `soveryn/agents/vett/harness/lattice_adapter.py` (~100 lines estimated, read-through adapter)
- `soveryn/agents/vett/harness/llm_client.py` (~30 lines, wraps our router endpoint as their LLM client)
- `soveryn/agents/vett/harness/run_eval.py` (~80 lines, CLI runner with turn budget + trajectory persistence + telemetry)
- `soveryn/agents/vett/harness/eval_tasks/` (directory of SOVERYN-representative task definitions in YAML or Python)
- `tests/test_vett_harness_smoke.py` (smoke test: integration loads, trivial task runs end-to-end, trajectory JSON is well-formed)
- `LICENSES/harness-1-APACHE-2.0` (their license file)
- `LICENSES/harness-1-NOTICE` (attribution + statement of modifications: SOVERYN's lattice_adapter.py and llm_client.py replace their Chroma + vLLM defaults)

**Modified:**
- `pyproject.toml` — any new pip deps (unlikely; their code is mostly stdlib + an LLM HTTP client we can satisfy with httpx/requests we already have)

**Not modified:** anything in `soveryn/agents/vett/research_surface.py`, `soveryn/agents/vett/patrol/`, `soveryn/agents/loop.py`, `soveryn/agents/aetheria/`, the router presets, or any systemd unit.

## What we hope to learn

Phase 1 isn't binary success/failure — it's a measurement that informs what comes next. Concrete questions phase 1 should answer:

1. Does untrained Vett operate the harness sensibly, or does she get stuck in exploration loops / never verify / never promote?
2. Is the harness's structural state (candidates, curated set, evidence links, verification records) actually cleaner / more auditable than Vett-current's prompt-blob output, on the same task?
3. How does wall-time compare? Harness adds orchestration cost — does its better state management offset the extra LLM calls, or does it just slow Vett down?
4. Are there harness behaviors that obviously came from RL and don't transfer (e.g., reward-shaped verification thresholds, tool-diversity policies)? Phase 1 trajectories should make these visible.
5. Is the lattice adapter's shape sufficient, or does harness assume Chroma-specific metadata that requires more adapter complexity than the 100-line estimate?

Answers feed into the phase 2 decision: wire into Vett's normal task surface (if matching or better) vs. discard the port (if it makes Vett worse or sensibly-unusable without training).

## Risks

- **Harness behaviors may be RL-trained-in.** Verification confidence thresholds, evidence-promotion criteria, and tool-use diversity expectations may be implicitly tied to gpt-oss-20b's fine-tune. Most likely failure mode: Vett searches but never verifies/promotes; trajectory JSON should expose this clearly.
- **Chroma assumptions in their retrieval code.** Even if the LLM seam is OpenAI-compatible, retrieval backend may have Chroma-specific metadata or query shapes baked in. Adapter could be larger than 100 lines.
- **Harness orchestration overhead.** Up to 20-40 turns per task, each turn a tool call into the harness + an LLM call. Total wall time per Vett task could increase even with better outputs. Failure-mode telemetry surfaces this.
- **Apache 2.0 attribution.** Easy to comply but needs to actually happen (LICENSES/ directory + NOTICE stating modifications).
- **Vendoring drift.** We lose easy upstream tracking. If the team ships a meaningful update, we have to manually re-merge. Codex's "vendored, not submodule" call is right for now, but worth a periodic re-check.

## Self-review (per writing-plans skill)

- **Placeholder scan.** No "TBD" / "fill in later" / vague requirements. Eval task definitions are deferred to the implementation plan but explicitly so, not as a hand-wave.
- **Internal consistency.** Out scope matches in scope (no `loop.py` mentioned in either). Architectural-shape table aligns with file paths.
- **Scope check.** Phase 1 is a single CLI runner + integration test + comparison run. Implementable as a single plan. Phase 2/3 explicitly out, future spec.
- **Ambiguity check.** Success bar is "match Vett-current with cleaner evidence state" — defined enough that the comparison run can judge it. "Cleaner" is qualitative but operationalized via the trajectory JSON having structured candidate/curated/verification fields rather than a freeform prompt blob.

## See also

- [[project-soveryn-aetheria-prompt-cache-fix]] — same architectural principle (move state out of model context) applied at a different layer earlier today
- [[project-soveryn-scout-retired]] — Vett's current tool roster after Scout retirement
- [[project-soveryn-cognition-isolation]] — separate-thinking-surface precedent for offloading model-side work
- [[feedback-verify-incident-diagnoses]] — applies: phase 1 is a measurement, not a declaration
- [[feedback-evaluate-the-shadow-not-the-function]] — applies: judge the harness by what it suppresses *and* what it enables, not just the benchmark headline
