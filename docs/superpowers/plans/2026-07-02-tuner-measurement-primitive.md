# Tuner Measurement Primitive — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `measure(candidate) -> Measurement` — a bulletproof primitive that launches one inference config on the mixed rig, runs a fixed prompt, and returns a correctly-classified result (`ok`/`oom`/`load_failed`/`hung`/`garbage`/`hardware_error`) with clean, bounded teardown.

**Architecture:** Three units — a `Candidate` value object that translates to llama-server flags; a **pure** `classify()` function (all failure detection, unit-testable against captured log fixtures, no GPU); and `measure()`, the orchestration that launches/watches/benchmarks/tears-down and feeds the real run outcome to `classify()`. The purity split means correctness is provable offline; only the final self-test touches real hardware.

**Tech Stack:** Python 3.11, `subprocess`, `pynvml` (installed), `requests`/`urllib`, `pytest`. Reuses the production `llama-server` binary (`~/llama.cpp_head/build/bin/llama-server`) and cuda-compat env.

## Global Constraints
- **Spec:** `docs/superpowers/specs/2026-07-02-tuner-measurement-primitive-design.md`.
- **`model_file` is a FIELD on `Candidate`** (quant lives there) — never a fixed engine input.
- **cuda-compat env is REQUIRED at launch:** `LD_LIBRARY_PATH=/home/jon-deoliveira/miniconda3/envs/cuda131/cuda-compat:/home/jon-deoliveira/miniconda3/envs/cuda131/lib` (without it CUDA init fails).
- **llama-server flags use explicit values:** `-fa on|off` (bare `-fa` errors on this HEAD build).
- **Teardown is bounded:** poll VRAM release up to `TEARDOWN_TIMEOUT`, else warn + return (never hang).
- **Failure classes:** `ok | oom | load_failed | hung | garbage | hardware_error`.
- **Scope:** ONLY the primitive + self-test. No candidate-generation, no cost model.
- **HARD STOP July 10, 2026** — self-test green by then or park it for Shepherd.
- Python env for running: `~/miniconda3/envs/soveryn/bin/python` / `pytest`.

---

## Task 1: `Candidate` value object + flag translation

**Files:**
- Create: `soveryn/platform/tuner/__init__.py` (empty)
- Create: `soveryn/platform/tuner/candidate.py`
- Test: `tests/test_tuner_candidate.py`

**Interfaces:**
- Produces: `Candidate` dataclass (fields below) and `to_llama_server_args(c: Candidate, *, host: str, port: int) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tuner_candidate.py
from soveryn.platform.tuner.candidate import Candidate, to_llama_server_args

def _cand(**kw):
    base = dict(model_file="/m/x.gguf", device_map="CUDA0,CUDA2", tensor_split="85,15",
               ngl=99, ot_offload=None, ctx_size=8192, cache_type_k="q8_0",
               cache_type_v="q8_0", flash_attn=True)
    base.update(kw); return Candidate(**base)

def test_full_candidate_maps_to_flags():
    args = to_llama_server_args(_cand(), host="127.0.0.1", port=8199)
    assert "-m" in args and "/m/x.gguf" in args
    assert "--tensor-split" in args and "85,15" in args
    assert "-ngl" in args and "99" in args
    assert "--cache-type-k" in args and "--cache-type-v" in args
    assert "-fa" in args and args[args.index("-fa")+1] == "on"      # explicit value
    assert "--port" in args and "8199" in args

def test_optional_fields_omitted_when_none():
    args = to_llama_server_args(_cand(tensor_split=None, ot_offload=None), host="127.0.0.1", port=1)
    assert "--tensor-split" not in args
    assert "-ot" not in args

def test_expert_offload_flag():
    args = to_llama_server_args(_cand(ot_offload="exps=CPU"), host="127.0.0.1", port=1)
    assert "-ot" in args and args[args.index("-ot")+1] == "exps=CPU"

def test_flash_attn_off_is_explicit():
    args = to_llama_server_args(_cand(flash_attn=False), host="127.0.0.1", port=1)
    assert args[args.index("-fa")+1] == "off"
```

- [ ] **Step 2: Run test to verify it fails** — `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_tuner_candidate.py -q` → FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# soveryn/platform/tuner/candidate.py
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Candidate:
    model_file: str            # absolute path to GGUF — the quant lives here
    device_map: str            # e.g. "CUDA0,CUDA2"
    ngl: int
    ctx_size: int
    cache_type_k: str
    cache_type_v: str
    flash_attn: bool
    tensor_split: str | None = None
    ot_offload: str | None = None

def to_llama_server_args(c: Candidate, *, host: str, port: int) -> list[str]:
    args = [
        "-m", c.model_file,
        "--device", c.device_map,
        "-ngl", str(c.ngl),
        "-c", str(c.ctx_size),
        "--cache-type-k", c.cache_type_k,
        "--cache-type-v", c.cache_type_v,
        "-fa", "on" if c.flash_attn else "off",
        "--host", host, "--port", str(port),
    ]
    if c.tensor_split:
        args += ["--tensor-split", c.tensor_split]
    if c.ot_offload:
        args += ["-ot", c.ot_offload]
    return args
```

- [ ] **Step 4: Run tests** → PASS.
- [ ] **Step 5: Commit** — `git add soveryn/platform/tuner/ tests/test_tuner_candidate.py && git commit -m "feat(tuner): Candidate value object + llama-server flag translation"`

---

## Task 2: The pure classifier — `classify()` + `RunOutcome` + `Measurement`

This is the correctness heart. Every failure class is decided here from captured signals — **no GPU needed to test it.** Detection order matters: `hardware_error` before `oom`/`load_failed` (a faulted card can masquerade as either).

**Files:**
- Create: `soveryn/platform/tuner/result.py`
- Test: `tests/test_tuner_classify.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Measurement` dataclass (`status:str, tok_s:float|None, peak_vram:dict[int,int], detail:str`); `RunOutcome` dataclass (`listened:bool, exit_code:int|None, stderr:str, generated_tokens:int, output_text:str, gpu_faulted:bool`); `classify(outcome: RunOutcome) -> tuple[str, str]` returning `(status, detail)`; `is_degenerate(text: str) -> bool`.

- [ ] **Step 1: Write the failing test** (fixtures are verbatim strings from real incidents this project)

```python
# tests/test_tuner_classify.py
from soveryn.platform.tuner.result import RunOutcome, classify, is_degenerate

def _oc(**kw):
    base = dict(listened=False, exit_code=1, stderr="", generated_tokens=0,
                output_text="", gpu_faulted=False)
    base.update(kw); return RunOutcome(**base)

def test_oom_from_real_235b_string():
    s = "ggml_backend_cuda_buffer_type_alloc_buffer: allocating 44148 MiB on device 2: cudaMalloc failed: out of memory"
    assert classify(_oc(stderr=s))[0] == "oom"

def test_load_failed_cuda_compat_miss():
    s = "ggml_cuda_init: failed to initialize CUDA: CUDA driver version is insufficient for CUDA runtime version"
    assert classify(_oc(stderr=s))[0] == "load_failed"

def test_load_failed_bad_arg():
    s = "error while handling argument \"-fa\": error: unknown value for --flash-attn: '--host'"
    assert classify(_oc(stderr=s))[0] == "load_failed"

def test_hardware_error_takes_priority():
    s = "CUDA error: an illegal memory access was encountered\ncudaMalloc failed: out of memory"
    # even though an OOM string is present, the illegal-access fault wins
    assert classify(_oc(stderr=s))[0] == "hardware_error"

def test_hardware_error_fallen_off_bus():
    assert classify(_oc(stderr="GPU 2 has fallen off the bus"))[0] == "hardware_error"

def test_hardware_error_from_gpu_faulted_flag():
    assert classify(_oc(gpu_faulted=True, stderr="anything"))[0] == "hardware_error"

def test_hung_listened_but_no_tokens():
    assert classify(_oc(listened=True, exit_code=None, generated_tokens=0))[0] == "hung"

def test_hung_never_listened_no_error():
    assert classify(_oc(listened=False, exit_code=None, stderr="loading model..."))[0] == "hung"

def test_garbage_degenerate_repetition():
    out = "the the the the the the the the the the the the"
    assert classify(_oc(listened=True, generated_tokens=12, output_text=out))[0] == "garbage"

def test_garbage_empty_output():
    assert classify(_oc(listened=True, generated_tokens=5, output_text="   "))[0] == "garbage"

def test_ok_clean_run():
    out = "Paris is the capital of France."
    assert classify(_oc(listened=True, exit_code=None, generated_tokens=7, output_text=out))[0] == "ok"

def test_is_degenerate_helper():
    assert is_degenerate("")
    assert is_degenerate("ok ok ok ok ok ok ok ok")
    assert not is_degenerate("A clear, varied sentence with real content.")
```

- [ ] **Step 2: Run test to verify it fails** → FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

```python
# soveryn/platform/tuner/result.py
from __future__ import annotations
from dataclasses import dataclass, field
import re

@dataclass
class Measurement:
    status: str                      # ok|oom|load_failed|hung|garbage|hardware_error
    tok_s: float | None = None
    peak_vram: dict[int, int] = field(default_factory=dict)
    detail: str = ""

@dataclass
class RunOutcome:
    listened: bool
    exit_code: int | None
    stderr: str
    generated_tokens: int
    output_text: str
    gpu_faulted: bool = False

# verbatim-from-incident signal strings
_HARDWARE = ("has fallen off the bus", "an illegal memory access",
             "unspecified launch failure", "device-side assert", "Xid",
             "uncorrectable ecc", "ECC error")
_OOM = ("cudaMalloc failed: out of memory", "failed to allocate", "out of memory")
_LOAD_FAILED = ("CUDA driver version is insufficient", "failed to load model",
                "error while handling argument", "unknown value for", "unknown argument")

def is_degenerate(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    toks = t.split()
    if len(toks) >= 6:
        # any single token making up >60% of output = a loop
        top = max(set(toks), key=toks.count)
        if toks.count(top) / len(toks) > 0.6:
            return True
        # short n-gram loop, e.g. "a b a b a b"
        if len(set(toks)) <= max(2, len(toks) // 5):
            return True
    return False

def classify(o: RunOutcome) -> tuple[str, str]:
    s = o.stderr or ""
    def _hit(sigs): return next((x for x in sigs if x.lower() in s.lower()), None)
    # 1. hardware first — a faulted card masquerades as oom/load_failed
    if o.gpu_faulted:
        return "hardware_error", "gpu_faulted flag set"
    if (h := _hit(_HARDWARE)):
        return "hardware_error", f"hardware signal: {h!r}"
    # 2. oom
    if (h := _hit(_OOM)):
        return "oom", f"oom signal: {h!r}"
    # 3. load_failed
    if (h := _hit(_LOAD_FAILED)):
        return "load_failed", f"load-failure signal: {h!r}"
    # 4. never got a healthy generation
    if o.listened and o.generated_tokens > 0:
        if is_degenerate(o.output_text):
            return "garbage", "degenerate/empty output"
        return "ok", "clean run"
    # listened but produced nothing, or never listened w/o a known error → hung
    return "hung", "no healthy generation (timed out at load or during gen)"
```

- [ ] **Step 4: Run tests** → all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(tuner): pure classify() — 6-class failure detection from captured signals"`

---

## Task 3: `measure()` orchestration — launch / watch / benchmark / bounded teardown

Wires Tasks 1+2 to real processes. Unit-test the orchestration with an injected fake launcher (no GPU); the real-hardware proof is Task 4.

**Files:**
- Create: `soveryn/platform/tuner/measure.py`
- Test: `tests/test_tuner_measure_unit.py`

**Interfaces:**
- Consumes: `Candidate`, `to_llama_server_args` (Task 1); `RunOutcome`, `Measurement`, `classify` (Task 2).
- Produces: `measure(candidate, *, devices, port=8199, load_timeout=300, gen_timeout=60, teardown_timeout=30, launcher=None) -> Measurement`. `launcher` is an injectable seam: a callable `(args, env) -> RunHandle`; default is the real subprocess launcher. `RunHandle` exposes `.wait_listen(timeout)`, `.benchmark(prompt, timeout)`, `.peak_vram(devices)`, `.stderr`, `.gpu_faulted()`, `.kill()`.

- [ ] **Step 1: Write the failing test** (fake launcher lets us drive every branch deterministically)

```python
# tests/test_tuner_measure_unit.py
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.measure import measure

def _cand(): return Candidate(model_file="/m/x.gguf", device_map="CUDA0", ngl=99,
    ctx_size=4096, cache_type_k="q8_0", cache_type_v="q8_0", flash_attn=True)

class FakeHandle:
    def __init__(self, *, listened, stderr="", tokens=0, out="", faulted=False, tok_s=0.0):
        self._l, self.stderr, self._t, self._o, self._f, self._toks = listened, stderr, tokens, out, faulted, tok_s
        self.killed = False
    def wait_listen(self, timeout): return self._l
    def benchmark(self, prompt, timeout): return (self._t, self._o, self._toks)  # (n_tokens, text, tok_s)
    def peak_vram(self, devices): return {d: 100 for d in devices}
    def gpu_faulted(self): return self._f
    def kill(self): self.killed = True
    def wait_vram_released(self, devices, timeout): return True

def _launcher(handle):
    def make(args, env): return handle
    return make

def test_measure_ok():
    h = FakeHandle(listened=True, tokens=7, out="Paris.", tok_s=14.2)
    m = measure(_cand(), devices=[0], launcher=_launcher(h))
    assert m.status == "ok" and m.tok_s == 14.2 and m.peak_vram == {0: 100}
    assert h.killed  # teardown ran

def test_measure_oom():
    h = FakeHandle(listened=False, stderr="cudaMalloc failed: out of memory")
    assert measure(_cand(), devices=[0], launcher=_launcher(h)).status == "oom"

def test_measure_hardware_error():
    h = FakeHandle(listened=True, tokens=1, stderr="an illegal memory access was encountered")
    assert measure(_cand(), devices=[0], launcher=_launcher(h)).status == "hardware_error"

def test_measure_always_tears_down():
    h = FakeHandle(listened=False, stderr="whatever")
    measure(_cand(), devices=[0], launcher=_launcher(h))
    assert h.killed
```

- [ ] **Step 2: Run test** → FAIL (module missing).

- [ ] **Step 3: Write minimal implementation** — the orchestration skeleton (real subprocess launcher lives here too; the default builds a real `RunHandle` around `llama-server` with the cuda-compat env, `pynvml` polling, an HTTP benchmark call, and a bounded `wait_vram_released`).

```python
# soveryn/platform/tuner/measure.py  (orchestration; real RunHandle sketched, default launcher)
from __future__ import annotations
import logging
from soveryn.platform.tuner.candidate import Candidate, to_llama_server_args
from soveryn.platform.tuner.result import RunOutcome, Measurement, classify

log = logging.getLogger(__name__)
FIXED_PROMPT = "In one short sentence: what is the capital of France?"

def measure(candidate: Candidate, *, devices: list[int], port: int = 8199,
            load_timeout: float = 300, gen_timeout: float = 60,
            teardown_timeout: float = 30, launcher=None) -> Measurement:
    launcher = launcher or _real_launcher
    args = to_llama_server_args(candidate, host="127.0.0.1", port=port)
    h = launcher(args, _cuda_compat_env())
    try:
        listened = h.wait_listen(load_timeout)
        n_tokens, out_text, tok_s = (0, "", 0.0)
        peak = {}
        if listened:
            n_tokens, out_text, tok_s = h.benchmark(FIXED_PROMPT, gen_timeout)
            peak = h.peak_vram(devices)
        outcome = RunOutcome(listened=listened, exit_code=None, stderr=h.stderr,
                             generated_tokens=n_tokens, output_text=out_text,
                             gpu_faulted=h.gpu_faulted())
        status, detail = classify(outcome)
        return Measurement(status=status, detail=detail,
                           tok_s=(tok_s if status == "ok" else None), peak_vram=peak)
    finally:
        h.kill()
        if not h.wait_vram_released(devices, teardown_timeout):
            log.warning("TEARDOWN_TIMEOUT: VRAM not released on %s within %ss — "
                        "returning; next precondition will refuse contaminated state",
                        devices, teardown_timeout)
```

*(The `_real_launcher`, `_cuda_compat_env`, and the real `RunHandle` — subprocess spawn with `LD_LIBRARY_PATH` cuda-compat, poll stderr for "server is listening", `requests` POST to `/v1/chat/completions` for the benchmark with `tok_s` from `usage`+wall-time, `pynvml` peak-VRAM sampling in a thread, `pynvml` ECC/Xid read for `gpu_faulted`, and `wait_vram_released` polling `nvidia_smi`/`pynvml` until used-MiB returns to the pre-launch baseline or `teardown_timeout` — are implemented in this task following the RunHandle interface the unit tests mock. Precondition check (devices clean before launch) is a guard at the top of the real launcher: refuse if baseline VRAM already elevated.)*

- [ ] **Step 4: Run unit tests** → PASS (against the fake launcher).
- [ ] **Step 5: Commit** — `git commit -m "feat(tuner): measure() orchestration + injectable launcher seam + bounded teardown"`

---

## Task 4: The self-test — deliberately trigger each failure mode on the REAL rig

The hardening deliverable. Runs against real hardware in a fleet-down window — the proof the primitive classifies this rack's actual failures. Marked `@pytest.mark.rig` so it's opt-in (not in the default CI/unit run).

**Files:**
- Create: `tests/test_tuner_measure_rig.py`
- Modify: `pyproject.toml` — register the `rig` marker.

**Interfaces:** Consumes `Candidate`, `measure` + a small real GGUF path (use an existing fleet model, e.g. `cognition`'s `gemma-4-E4B` or `embeddings` — something small that loads fast).

- [ ] **Step 1: Write the tests** (each deliberately provokes one class)

```python
# tests/test_tuner_measure_rig.py   (run:  pytest -m rig  — FLEET DOWN FIRST)
import pytest, pynvml
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.measure import measure

pytestmark = pytest.mark.rig
SMALL = "/mnt/soveryn_models/GGUF/gemma-4-E4B-it-Q8_0.gguf"   # loads fast

def _c(**kw):
    base = dict(model_file=SMALL, device_map="CUDA0", ngl=99, ctx_size=2048,
                cache_type_k="q8_0", cache_type_v="q8_0", flash_attn=True)
    base.update(kw); return Candidate(**base)

def test_ok_and_teardown_returns_vram_to_baseline():
    pynvml.nvmlInit()
    m = measure(_c(), devices=[0])
    assert m.status == "ok" and m.tok_s and m.tok_s > 0
    # teardown proof: baseline restored (a second measure won't false-OOM)
    m2 = measure(_c(), devices=[0])
    assert m2.status == "ok"

def test_oom_by_over_context():
    # absurd ctx forces an allocation failure on a single card
    m = measure(_c(ctx_size=4_000_000), devices=[0])
    assert m.status in ("oom", "load_failed")   # both are "config won't fit", acceptable

def test_load_failed_bad_model_path():
    m = measure(_c(model_file="/does/not/exist.gguf"), devices=[0])
    assert m.status == "load_failed"

def test_hung_by_tiny_load_timeout():
    # a big model with a 2s load window can't finish loading → hung, not crash
    m = measure(_c(model_file="/mnt/soveryn_models/GGUF/google_gemma-4-31B-it-Q8_0.gguf"),
                devices=[0], load_timeout=2)
    assert m.status == "hung"
```

- [ ] **Step 2: Register the marker** in `pyproject.toml` under `[tool.pytest.ini_options]`: `markers = ["rig: runs against real GPUs; fleet must be down"]`.
- [ ] **Step 3: Run — FLEET DOWN first.** `systemctl --user stop soveryn.target` (free VRAM), then `~/miniconda3/envs/soveryn/bin/python -m pytest tests/test_tuner_measure_rig.py -m rig -v`. Iterate `measure()`'s real launcher until every class asserts correctly. **This iteration is where the hardening actually happens** — real failures rarely match the fixture strings exactly.
- [ ] **Step 4: Restore fleet** — `systemctl --user start soveryn.target`, verify vnext :5001 → 200.
- [ ] **Step 5: Commit** — `git commit -m "test(tuner): real-rig self-test — each failure class provoked + classified, teardown proven"`

---

## Self-Review notes
- **Spec coverage:** Candidate w/ model_file-as-field (T1) ✓; 6-class `classify` grounded in real strings incl. `hardware_error` priority (T2) ✓; launch+cuda-compat+watchdogs+pynvml+bounded teardown (T3) ✓; self-test triggering each mode + teardown-baseline proof (T4) ✓; garbage=empty/repetition, quality-regression deferred ✓.
- **Type consistency:** `Candidate` fields, `to_llama_server_args(...,host,port)`, `RunOutcome`/`Measurement` fields, `classify->tuple[str,str]`, `measure(...)->Measurement`, `RunHandle` methods (`wait_listen`/`benchmark`/`peak_vram`/`gpu_faulted`/`kill`/`wait_vram_released`) consistent T1→T4.
- **Not fully specified by design:** the real `RunHandle`'s subprocess/pynvml internals (T3) are described by interface + behavior, not line-by-line — they're hardware-integration code best written against the real rig in T4's iteration loop; the unit tests pin the contract.
- **Timebox:** T1–T2 are an evening (pure, fast). T3–T4 are the real work, and T4's iteration is where July-10 discipline applies — if the classifier won't converge on the rig by then, park it.
