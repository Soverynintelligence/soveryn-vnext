# Heterogeneous Inference Tuner — Step 1: The Measurement Primitive (Design)

**Date:** 2026-07-02
**Status:** Design for review.
**Scope:** This spec covers **ONLY the measurement primitive** — the load-bearing wall of the tuner. Candidate generation, the analytical cost model, quant search, and router-preset integration are **explicitly out of scope** and get their own later specs. Build this one thing, bulletproof, first.

## Why this, first

The tuner's job is to find the best way to run a model on SOVERYN's *mismatched* rig (Blackwell + 2× Turing Quadro + CPU offload). The expensive, load-bearing primitive underneath everything is: *launch a config, run it, report what happened.* Every later layer (candidate generation, cost model) is logic on top of this. If measurement is flaky, the whole tuner lies to you and you won't know which layer lied. On a heterogeneous rig, **failures are the common case during a search, not the exception** — so the primitive's real work is *classifying failure correctly*, not timing the happy path. That failure-classification is SOVERYN-specific (nobody's generic tuner handles Blackwell+Turing OOM cleanly) — it's the moat and the risk in the same place.

## Data model — quant is a FIELD, not a fixed input

The whole point: the model file's footprint changes *which configs fit at all*, so the quant cannot be an outer wrapper — it's the outermost dimension that defines the inner search space. Therefore `model_file` is a field on the Candidate from line one. (Later, quant-search is just varying this field across a list; a single-model run is a length-1 list. Same code path.)

```
Candidate = {
  model_file:   str,          # absolute path to the GGUF — the quant lives here
  device_map:   str,          # e.g. "CUDA0,CUDA2"   (which devices)
  tensor_split: str | None,   # e.g. "85,15"
  ngl:          int,          # n-gpu-layers
  ot_offload:   str | None,   # e.g. "exps=CPU"      (-ot override)
  ctx_size:     int,
  cache_type_k: str,          # KV quant, e.g. "q8_0"
  cache_type_v: str,
  flash_attn:   bool,
}

Measurement = {
  status:   "ok" | "oom" | "load_failed" | "hung" | "garbage",
  tok_s:    float | None,           # only when status == ok
  peak_vram: dict[int,int],         # per-device peak MiB, polled during the run
  detail:   str,                    # the deciding error string / reason (for debugging)
}
```

## `measure(candidate) -> Measurement` — behavior

1. **Precondition — clean slate.** Verify the target devices are free (fleet down for a tuning window, or a reserved VRAM budget). If not clean, refuse (don't measure into contamination).
2. **Launch.** Spawn `llama-server` with the candidate translated to flags, on a scratch port, using the **same binary + cuda-compat `LD_LIBRARY_PATH`** production uses (`~/miniconda3/envs/cuda131/cuda-compat:.../lib` — without it, CUDA init fails; we hit this). Capture stderr to a log.
3. **Load watchdog.** Poll for `"server is listening"` up to `LOAD_TIMEOUT`. On timeout/exit, classify from the log:
   - `oom` ← `"cudaMalloc failed: out of memory"` / `"failed to allocate CUDA buffer"` (verbatim what the 235B threw on GPU2).
   - `load_failed` ← `"CUDA driver version is insufficient"` (env miss), unknown-arg errors (the bare `-fa` value error), `"failed to load model"`, non-zero exit.
   - `hung` ← still running, never listened, no error string.
4. **Benchmark.** If listening, send a **fixed prompt** (a short, known-answerable question) with a **generation watchdog** (`GEN_TIMEOUT`): if zero tokens arrive in the window → `hung` (the same class as the download-hang, which happens on inference too). Poll `pynvml` per-device throughout for `peak_vram`.
5. **Output sanity → `garbage`.** v1 heuristics catch obvious broken output: empty, **degenerate repetition** (token/n-gram looping), or **language/format bleed** (we literally saw Chinese + planning-preamble on the raw-completion 235B). *Full quality-regression detection ("subtly worse") is explicitly deferred* — v1 catches broken, not dull.
6. **`ok`.** Listened + coherent-enough output → record `tok_s` from the response timings + `peak_vram`.
7. **Teardown — GUARANTEED clean.** Kill the server, then **poll until its processes are dead AND target-device VRAM is released** before returning. This is non-negotiable: the router-orphan incident (2026-07-02) proved this rig leaves orphan processes holding VRAM, and a leaked candidate silently **false-OOMs** the next one, corrupting the search.

## Failure modes are grounded in real incidents (not theory)

| status | real occurrence this project | detection |
|---|---|---|
| `load_failed` | cuda-compat env miss; bare `-fa` arg error | stderr string match + exit code |
| `oom` | 235B even-split OOM on GPU2 | `cudaMalloc failed: out of memory` |
| `hung` | overnight download hang (process alive, 0 progress) | load + generation timeouts |
| `garbage` | Chinese/planning-preamble bleed on raw completion | empty / repetition / language-bleed heuristics |
| (teardown) | parakeet orphan + router-orphan holding GPU2 | poll-until-VRAM-released between runs |

## The deliverable that PROVES it's bulletproof

A self-test that **deliberately triggers each failure mode on this actual rack** and asserts correct classification:
- a config that OOMs (over-allocate VRAM) → asserts `oom`
- a config with a bad arg → asserts `load_failed`
- a config that hangs (or a stub that never listens) → asserts `hung`
- a known-degenerate output → asserts `garbage`
- a good config → asserts `ok` with a plausible `tok_s`
- back-to-back runs → asserts VRAM returns to baseline between them (teardown proof)

This test *is* the hardening. It's the thing that de-risks the customer story, because the customer story is "it works on a rig as ugly as mine."

## Files
- `soveryn/platform/tuner/candidate.py` — the `Candidate` dataclass + `to_llama_server_args()`.
- `soveryn/platform/tuner/measure.py` — `measure(candidate) -> Measurement`, the launch/watchdog/classify/teardown logic.
- `tests/test_tuner_measure.py` — the failure-mode self-test (runs against the real rig; fleet-down window).

## Out of scope (later specs, in this order)
1. Candidate generation — a **dumb hand-written shortlist** first, proving the loop picks a sane winner end-to-end. No cleverness.
2. The analytical cost model (bottleneck prediction on heterogeneous silicon) — the research part + the paper. Worthless until measurement is trustworthy; comes last.

## Project constraint (load-bearing, non-technical)
**Timebox: a few evenings.** This primitive is genuinely worth building (SOVERYN needs it for its own rack), but it is exactly the absorbing technical problem that can eat the weeks that should close the Shepherd sale. If it stretches toward weeks, that's the signal the fun build is crowding out the valuable sale. **Shepherd-buddy-says-yes stays the higher-value event.** Build the primitive, ship the self-test, stop.
