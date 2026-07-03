# Tuner Layer 2 — Candidate Generation + Search Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically find the best run-config for a model on the mixed rig — a rule-based generator emits a spread of candidate configs, a sequential loop measures each with the existing primitive, and the empirical winner (highest `tok_s`) is reported.

**Architecture:** Four small units mirroring the primitive's purity split — `rig.py` (pure `Rig` data + a `pynvml` probe), `generate.py` (pure rules), `search.py` (the loop with an injectable `measure_fn`), and a thin `__main__` CLI. Backend is a `Candidate` field (default `"cuda"`) so the design is heterogeneous-ready without hardcoding; v1 resolves it only to the CUDA build.

**Tech Stack:** Python 3.11+, `pynvml` (already a dependency of `measure.py`), the existing tuner primitive (`candidate.py`, `measure.py`, `result.py`), pytest.

## Global Constraints

- **A dimension that reshapes the search space is a FIELD, not a constant** — `backend` joins `model_file` (quant) as a `Candidate` field. Unknown backend → `ValueError`, never a silent CUDA fallback.
- **The generator is DUMB** — it emits a spread of sensible candidates and lets measurement decide. It must NOT reason about topology; `Device.pci_bus_id` is captured for Layer 3 but MUST be unused by the generator.
- **Everything offline-testable via injected seams** — `measure_fn` (search), `devices_reader`/`ram_reader` (rig). Only the `@pytest.mark.rig` test touches real GPUs (fleet down).
- **Winner = max `tok_s` among `status=="ok"`.** If none are `ok`, `winner=None` — never fake one.
- **One candidate raising must NOT kill the search** — record it as a `load_failed` `Measurement` and continue.
- **Candidate spread is capped** at `_MAX_CANDIDATES = 6` to bound search time; the always-include big-model paths (offload, KV-quant) are prioritized before the subset spread so the cap can't drop them.
- **v1 reports, does not auto-apply** to the router. CUDA backend only in practice.
- **Timeboxed:** parks the instant the Shepherd callback lands.

---

### Task 1: `backend` field on Candidate + backend-resolved binary in measure.py

**Files:**
- Modify: `soveryn/platform/tuner/candidate.py` (add `backend` field)
- Modify: `soveryn/platform/tuner/measure.py` (resolve binary from backend; thread it through the launcher seam)
- Modify: `tests/test_tuner_measure_unit.py` (fake launcher signature `(args, env)` → `(binary, args, env)`)
- Test: `tests/test_tuner_candidate.py` (backend default + resolver)

**Interfaces:**
- Produces: `Candidate.backend: str = "cuda"`; `measure._resolve_binary(backend: str) -> str` (raises `ValueError` on unknown); launcher seam is now `launcher(binary: str, args: list[str], env: dict)`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_tuner_candidate.py`:

```python
def test_candidate_backend_defaults_to_cuda():
    from soveryn.platform.tuner.candidate import Candidate
    c = Candidate(
        model_file="/m.gguf", device_map="CUDA0", ngl=99, ctx_size=4096,
        cache_type_k="f16", cache_type_v="f16", flash_attn=True,
    )
    assert c.backend == "cuda"


def test_resolve_binary_known_and_unknown():
    from soveryn.platform.tuner.measure import _resolve_binary
    assert _resolve_binary("cuda").endswith("llama-server")
    import pytest
    with pytest.raises(ValueError):
        _resolve_binary("vulkan")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tuner_candidate.py::test_candidate_backend_defaults_to_cuda tests/test_tuner_candidate.py::test_resolve_binary_known_and_unknown -v`
Expected: FAIL — `TypeError`/`AttributeError` (no `backend`) and `ImportError` (no `_resolve_binary`).

- [ ] **Step 3: Add the `backend` field** — in `soveryn/platform/tuner/candidate.py`, change the field block to:

```python
    flash_attn: bool
    tensor_split: str | None = None
    ot_offload: str | None = None
    backend: str = "cuda"      # which build/backend launches this config (quant-like: a field, not a constant)
```

- [ ] **Step 4: Resolve the binary from the backend** — in `soveryn/platform/tuner/measure.py`, replace the `_BINARY` constant (line ~27) with:

```python
_BACKEND_BINARY = {
    "cuda": os.path.expanduser("~/llama.cpp_head/build/bin/llama-server"),
}


def _resolve_binary(backend: str) -> str:
    """Map a candidate's backend to its llama-server binary. No silent fallback."""
    try:
        return _BACKEND_BINARY[backend]
    except KeyError:
        raise ValueError(
            f"unknown backend {backend!r}; known: {sorted(_BACKEND_BINARY)}"
        )
```

In `measure()`, resolve the binary and pass it to the launcher — change:
```python
    args = to_llama_server_args(candidate, host="127.0.0.1", port=port)
    h = launcher(args, _cuda_compat_env())
```
to:
```python
    args = to_llama_server_args(candidate, host="127.0.0.1", port=port)
    binary = _resolve_binary(candidate.backend)
    h = launcher(binary, args, _cuda_compat_env())
```

Change `_RealHandle.__init__` signature and its Popen line:
```python
    def __init__(self, binary, args, env, port):
        import pynvml
        ...
        self._proc = subprocess.Popen(
            [binary] + args, env=env,
            stderr=subprocess.PIPE, stdout=subprocess.DEVNULL, text=True, bufsize=1)
```

Change `_real_launcher`:
```python
def _real_launcher(binary, args, env):
    port = int(args[args.index("--port") + 1])
    return _RealHandle(binary, args, env, port)
```

- [ ] **Step 5: Update the existing fake launcher** — in `tests/test_tuner_measure_unit.py`, the injected `launcher` callable currently has signature `(args, env)`. Change every fake-launcher definition (def or lambda) to `(binary, args, env)` — the fake ignores `binary`. (Read the file; there is one fake-launcher factory used across the measure unit tests.)

- [ ] **Step 6: Run the tests**

Run: `pytest tests/test_tuner_candidate.py tests/test_tuner_measure_unit.py -v`
Expected: PASS (existing measure unit tests still green with the new signature; new backend tests pass).

- [ ] **Step 7: Commit**

```bash
git add soveryn/platform/tuner/candidate.py soveryn/platform/tuner/measure.py tests/test_tuner_candidate.py tests/test_tuner_measure_unit.py
git commit -m "feat(tuner): backend is a Candidate field; measure resolves binary per backend"
```

---

### Task 2: `rig.py` — Device, Rig, probe_rig

**Files:**
- Create: `soveryn/platform/tuner/rig.py`
- Test: `tests/test_tuner_rig.py`

**Interfaces:**
- Produces: `Device(index:int, backend:str, name:str, vram_bytes:int, pci_bus_id:str)`, `Rig(devices:tuple[Device,...], total_ram_bytes:int)`, `probe_rig(*, devices_reader=_pynvml_devices, ram_reader=_system_ram_bytes) -> Rig`.
- Consumed by: Task 4 (generate), Task 6 (CLI).

- [ ] **Step 1: Write the failing test** — `tests/test_tuner_rig.py`:

```python
"""Rig probe tests — injected readers, no GPU."""
from soveryn.platform.tuner.rig import Device, Rig, probe_rig

GB = 1024 ** 3


def test_probe_rig_builds_from_injected_readers():
    def devs():
        return [
            (0, "NVIDIA RTX PRO 5000 Blackwell", 48 * GB, "0000:45:00.0"),
            (1, "Quadro RTX 8000", 48 * GB, "0000:01:00.0"),
        ]
    rig = probe_rig(devices_reader=devs, ram_reader=lambda: 256 * GB)
    assert rig.total_ram_bytes == 256 * GB
    assert len(rig.devices) == 2
    d0 = rig.devices[0]
    assert (d0.index, d0.backend, d0.name, d0.vram_bytes, d0.pci_bus_id) == (
        0, "cuda", "NVIDIA RTX PRO 5000 Blackwell", 48 * GB, "0000:45:00.0")


def test_rig_and_device_are_frozen():
    d = Device(index=0, backend="cuda", name="x", vram_bytes=1, pci_bus_id="p")
    import dataclasses, pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.vram_bytes = 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tuner_rig.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.platform.tuner.rig'`.

- [ ] **Step 3: Write `soveryn/platform/tuner/rig.py`**

```python
"""The rig the tuner optimizes for. Rig/Device are pure data (the generator's
input); probe_rig() is the only hardware-touching bit and uses pynvml (already a
dependency of measure.py) so device numbering, VRAM, and PCIe bus IDs are read
robustly rather than by scraping nvidia-smi text.

pci_bus_id is captured for Layer 3's topology reasoning — it is NOT used by the
Layer-2 generator.
"""
from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    index: int
    backend: str
    name: str
    vram_bytes: int
    pci_bus_id: str


@dataclass(frozen=True)
class Rig:
    devices: tuple[Device, ...]
    total_ram_bytes: int


def _pynvml_devices() -> list[tuple[int, str, int, str]]:
    """(index, name, total_vram_bytes, pci_bus_id) for each CUDA device."""
    import pynvml
    pynvml.nvmlInit()
    out: list[tuple[int, str, int, str]] = []
    for i in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(i)
        name = pynvml.nvmlDeviceGetName(h)
        if isinstance(name, bytes):
            name = name.decode()
        vram = int(pynvml.nvmlDeviceGetMemoryInfo(h).total)
        bus = pynvml.nvmlDeviceGetPciInfo(h).busId
        if isinstance(bus, bytes):
            bus = bus.decode()
        out.append((i, name, vram, bus))
    return out


def _system_ram_bytes() -> int:
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def probe_rig(*, devices_reader=_pynvml_devices, ram_reader=_system_ram_bytes) -> Rig:
    devices = tuple(
        Device(index=i, backend="cuda", name=name, vram_bytes=vram, pci_bus_id=bus)
        for (i, name, vram, bus) in devices_reader()
    )
    return Rig(devices=devices, total_ram_bytes=ram_reader())
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_tuner_rig.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/tuner/rig.py tests/test_tuner_rig.py
git commit -m "feat(tuner): Rig/Device + pynvml probe_rig (captures bus IDs for Layer 3)"
```

---

### Task 3: `generate.py` — model_footprint

**Files:**
- Create: `soveryn/platform/tuner/generate.py` (footprint half; rules added in Task 4)
- Test: `tests/test_tuner_generate.py`

**Interfaces:**
- Produces: `model_footprint(model_file: str) -> int`.

- [ ] **Step 1: Write the failing test** — `tests/test_tuner_generate.py`:

```python
"""Generator tests — pure, no GPU."""
from soveryn.platform.tuner.generate import model_footprint


def test_model_footprint_sums_split_shards(tmp_path):
    for k in (1, 2, 3):
        (tmp_path / f"M-0000{k}-of-00003.gguf").write_bytes(b"x" * (10 * k))
    fp = model_footprint(str(tmp_path / "M-00001-of-00003.gguf"))
    assert fp == 10 + 20 + 30


def test_model_footprint_single_file(tmp_path):
    p = tmp_path / "solo.gguf"
    p.write_bytes(b"y" * 123)
    assert model_footprint(str(p)) == 123
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tuner_generate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.platform.tuner.generate'`.

- [ ] **Step 3: Write `soveryn/platform/tuner/generate.py` (footprint only for now)**

```python
"""Rule-based candidate generator (pure). Emits a spread of sensible configs and
lets measurement decide the winner. It must NOT reason about topology.
"""
from __future__ import annotations
import glob
import os
import re


def model_footprint(model_file: str) -> int:
    """Total on-disk bytes of the model. For a split GGUF
    (…-00001-of-000NN.gguf) sum all sibling shards; else the file's own size."""
    m = re.match(r"^(.*)-\d{5}-of-\d{5}\.gguf$", os.path.basename(model_file))
    if m:
        d = os.path.dirname(model_file)
        shards = glob.glob(os.path.join(d, m.group(1) + "-*-of-*.gguf"))
        return sum(os.path.getsize(s) for s in shards)
    return os.path.getsize(model_file)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_tuner_generate.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/tuner/generate.py tests/test_tuner_generate.py
git commit -m "feat(tuner): model_footprint (sums split-GGUF shards)"
```

---

### Task 4: `generate.py` — generate_candidates (the rules)

**Files:**
- Modify: `soveryn/platform/tuner/generate.py` (add the rules)
- Test: `tests/test_tuner_generate.py` (add spread assertions)

**Interfaces:**
- Consumes: `model_footprint` (Task 3), `Rig`/`Device` (Task 2), `Candidate` (Task 1).
- Produces: `generate_candidates(model_file: str, rig: Rig) -> list[Candidate]`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_tuner_generate.py`:

```python
from soveryn.platform.tuner.generate import generate_candidates
from soveryn.platform.tuner.rig import Rig, Device

GB = 1024 ** 3


def _rig3():
    return Rig(devices=(
        Device(0, "cuda", "Blackwell", 48 * GB, "0000:45:00.0"),
        Device(1, "cuda", "Quadro-A", 48 * GB, "0000:01:00.0"),
        Device(2, "cuda", "Quadro-B", 48 * GB, "0000:81:00.0"),
    ), total_ram_bytes=256 * GB)


def _write_model(tmp_path, gb):
    p = tmp_path / "m.gguf"
    p.write_bytes(b"\0")           # tiny file; footprint is monkeypatched below
    return str(p)


def test_generate_spread_for_fitting_model(tmp_path, monkeypatch):
    import soveryn.platform.tuner.generate as g
    monkeypatch.setattr(g, "model_footprint", lambda _f: 10 * GB)  # fits everything
    cands = generate_candidates(_write_model(tmp_path, 10), _rig3())
    assert len(cands) <= 6
    # always-include big-model paths survive the cap:
    assert any(c.ot_offload == "exps=CPU" for c in cands)
    assert any(c.cache_type_k == "q8_0" for c in cands)
    # topology-relevant single-device option is measured (Blackwell alone):
    assert any(c.device_map == "CUDA0" for c in cands)
    # every candidate is backend-consistent (cuda device names):
    assert all(c.backend == "cuda" and c.device_map.startswith("CUDA") for c in cands)


def test_generate_big_model_still_emits_offload(tmp_path, monkeypatch):
    import soveryn.platform.tuner.generate as g
    monkeypatch.setattr(g, "model_footprint", lambda _f: 400 * GB)  # fits nothing
    cands = generate_candidates(_write_model(tmp_path, 400), _rig3())
    assert any(c.ot_offload == "exps=CPU" for c in cands)   # the path that can actually run it
    assert all(c.device_map == "CUDA0,CUDA1,CUDA2" for c in cands)  # no fitting subset exists


def test_generator_ignores_pci_bus_id(tmp_path, monkeypatch):
    import soveryn.platform.tuner.generate as g
    monkeypatch.setattr(g, "model_footprint", lambda _f: 10 * GB)
    r1 = _rig3()
    r2 = Rig(devices=tuple(
        Device(d.index, d.backend, d.name, d.vram_bytes, "9999:99:99.9") for d in r1.devices
    ), total_ram_bytes=r1.total_ram_bytes)
    mf = _write_model(tmp_path, 10)
    assert generate_candidates(mf, r1) == generate_candidates(mf, r2)  # bus IDs must not change output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tuner_generate.py -k generate -v`
Expected: FAIL — `ImportError: cannot import name 'generate_candidates'`.

- [ ] **Step 3: Add the rules to `soveryn/platform/tuner/generate.py`**

Add imports at the top (below the existing ones):
```python
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.rig import Rig
```

Append:
```python
_HEADROOM = 1.15                    # weights need ~15% VRAM headroom for buffers
_FIXED_OVERHEAD = 2 * 1024 ** 3     # ~2 GiB CUDA context + KV allowance
_MAX_CANDIDATES = 6
_DEFAULT_CTX = 4096
_DEFAULT_NGL = 99


def _fits(footprint: int, vram_bytes: int) -> bool:
    return footprint * _HEADROOM + _FIXED_OVERHEAD <= vram_bytes


def _candidate(model_file, indices, *, ot=None, ck="f16", cv="f16") -> Candidate:
    return Candidate(
        model_file=model_file,
        device_map=",".join(f"CUDA{i}" for i in indices),
        ngl=_DEFAULT_NGL, ctx_size=_DEFAULT_CTX,
        cache_type_k=ck, cache_type_v=cv, flash_attn=True,
        tensor_split=",".join(["1"] * len(indices)),
        ot_offload=ot, backend="cuda",
    )


def generate_candidates(model_file: str, rig: Rig) -> list[Candidate]:
    fp = model_footprint(model_file)
    # largest-VRAM device first, so the topology-relevant single (e.g. Blackwell) leads the spread
    devs = sorted(rig.devices, key=lambda d: d.vram_bytes, reverse=True)
    all_idx = [d.index for d in devs]
    total_vram = sum(d.vram_bytes for d in devs)

    cands: list[Candidate] = []
    # --- core (always try the big-model paths; prioritized so the cap can't drop them) ---
    if _fits(fp, total_vram):
        cands.append(_candidate(model_file, all_idx))                     # all, no offload
    cands.append(_candidate(model_file, all_idx, ot="exps=CPU"))          # all, expert-offload
    cands.append(_candidate(model_file, all_idx, ck="q8_0", cv="q8_0"))   # all, KV-quant
    # --- subset spread (topology-relevant; the generator does NOT reason, it just emits) ---
    for d in devs:
        if _fits(fp, d.vram_bytes):
            cands.append(_candidate(model_file, [d.index]))               # each single that fits alone
    for i in range(len(devs)):
        for j in range(i + 1, len(devs)):
            pair = [devs[i].index, devs[j].index]
            if len(pair) != len(all_idx) and _fits(fp, devs[i].vram_bytes + devs[j].vram_bytes):
                cands.append(_candidate(model_file, pair))                # sensible pairs

    # dedup (device_map, offload, kv) preserving order, then cap
    seen, uniq = set(), []
    for c in cands:
        key = (c.device_map, c.ot_offload, c.cache_type_k, c.cache_type_v)
        if key not in seen:
            seen.add(key)
            uniq.append(c)
    return uniq[:_MAX_CANDIDATES]
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_tuner_generate.py -v`
Expected: PASS (all — footprint + the three spread tests).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/tuner/generate.py tests/test_tuner_generate.py
git commit -m "feat(tuner): generate_candidates — dumb spread, offload+KV-quant prioritized, bus-id-blind"
```

---

### Task 5: `search.py` — the search loop

**Files:**
- Create: `soveryn/platform/tuner/search.py`
- Test: `tests/test_tuner_search.py`

**Interfaces:**
- Consumes: `Candidate` (Task 1), `Measurement` (existing `result.py`), `measure` (existing `measure.py`).
- Produces: `Ranked(candidate, measurement)`, `SearchResult(ranked:list[Ranked], winner:Candidate|None)`, `run_search(candidates, *, devices, measure_fn=measure, on_progress=None) -> SearchResult`.

- [ ] **Step 1: Write the failing test** — `tests/test_tuner_search.py`:

```python
"""Search-loop tests — fake measure_fn, no GPU."""
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.result import Measurement
from soveryn.platform.tuner.search import run_search


def _c(name):
    return Candidate(model_file="/m.gguf", device_map=name, ngl=99, ctx_size=4096,
                     cache_type_k="f16", cache_type_v="f16", flash_attn=True)


def test_winner_is_highest_tok_s_among_ok():
    cands = [_c("CUDA0"), _c("CUDA1"), _c("CUDA2")]
    table = {"CUDA0": Measurement(status="ok", tok_s=9.0),
             "CUDA1": Measurement(status="oom"),
             "CUDA2": Measurement(status="ok", tok_s=14.0)}
    res = run_search(cands, devices=[0, 1, 2],
                     measure_fn=lambda c, *, devices: table[c.device_map])
    assert res.winner.device_map == "CUDA2"
    assert res.ranked[0].candidate.device_map == "CUDA2"     # ok, sorted desc
    assert res.ranked[-1].measurement.status == "oom"        # failures last


def test_no_ok_means_no_winner():
    cands = [_c("CUDA0"), _c("CUDA1")]
    res = run_search(cands, devices=[0, 1],
                     measure_fn=lambda c, *, devices: Measurement(status="oom"))
    assert res.winner is None


def test_raising_candidate_is_recorded_and_search_continues():
    cands = [_c("BAD"), _c("CUDA0")]

    def flaky(c, *, devices):
        if c.device_map == "BAD":
            raise RuntimeError("boom")
        return Measurement(status="ok", tok_s=5.0)

    res = run_search(cands, devices=[0], measure_fn=flaky)
    assert res.winner.device_map == "CUDA0"                  # search survived the raise
    bad = [r for r in res.ranked if r.candidate.device_map == "BAD"][0]
    assert bad.measurement.status == "load_failed"
    assert "boom" in bad.measurement.detail


def test_on_progress_called_per_candidate():
    cands = [_c("CUDA0"), _c("CUDA1")]
    seen = []
    run_search(cands, devices=[0, 1],
               measure_fn=lambda c, *, devices: Measurement(status="ok", tok_s=1.0),
               on_progress=lambda i, n, c: seen.append((i, n, c.device_map)))
    assert seen == [(0, 2, "CUDA0"), (1, 2, "CUDA1")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tuner_search.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.platform.tuner.search'`.

- [ ] **Step 3: Write `soveryn/platform/tuner/search.py`**

```python
"""The search loop: run each candidate through the measurement primitive
(sequential — shared GPUs), rank by tok_s, pick the empirical winner. A candidate
that raises is recorded as load_failed and the search continues. Never fakes a
winner: winner is None when nothing came back ok.
"""
from __future__ import annotations
from dataclasses import dataclass

from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.result import Measurement
from soveryn.platform.tuner.measure import measure as _default_measure


@dataclass
class Ranked:
    candidate: Candidate
    measurement: Measurement


@dataclass
class SearchResult:
    ranked: list          # list[Ranked]: ok (tok_s desc) first, then failures
    winner: Candidate | None


def run_search(candidates, *, devices, measure_fn=_default_measure, on_progress=None) -> SearchResult:
    results: list[Ranked] = []
    for idx, cand in enumerate(candidates):
        if on_progress is not None:
            on_progress(idx, len(candidates), cand)
        try:
            m = measure_fn(cand, devices=devices)
        except Exception as exc:                       # a bad candidate must not kill the search
            m = Measurement(status="load_failed", detail=f"measure raised: {exc}")
        results.append(Ranked(candidate=cand, measurement=m))

    oks = [r for r in results if r.measurement.status == "ok"]
    fails = [r for r in results if r.measurement.status != "ok"]
    oks.sort(key=lambda r: (r.measurement.tok_s or 0.0), reverse=True)
    return SearchResult(ranked=oks + fails, winner=(oks[0].candidate if oks else None))
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_tuner_search.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/tuner/search.py tests/test_tuner_search.py
git commit -m "feat(tuner): run_search — measure each, rank by tok_s, survive raises, never fake a winner"
```

---

### Task 6: `__main__.py` — the autotune CLI

**Files:**
- Create: `soveryn/platform/tuner/__main__.py`
- Test: `tests/test_tuner_cli.py`

**Interfaces:**
- Consumes: `probe_rig` (Task 2), `model_footprint`/`generate_candidates` (Tasks 3–4), `run_search`/`SearchResult` (Task 5).
- Produces: `format_ranked_table(result: SearchResult) -> str`; `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing test** — `tests/test_tuner_cli.py`:

```python
"""CLI formatting test — pure, no GPU."""
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.result import Measurement
from soveryn.platform.tuner.search import Ranked, SearchResult
from soveryn.platform.tuner.__main__ import format_ranked_table


def _c(name, ot=None):
    return Candidate(model_file="/m.gguf", device_map=name, ngl=99, ctx_size=4096,
                     cache_type_k="f16", cache_type_v="f16", flash_attn=True, ot_offload=ot)


def test_table_flags_winner_and_shows_statuses():
    win = _c("CUDA0")
    res = SearchResult(
        ranked=[Ranked(win, Measurement(status="ok", tok_s=14.2)),
                Ranked(_c("CUDA1"), Measurement(status="oom"))],
        winner=win)
    out = format_ranked_table(res)
    assert "WINNER" in out
    assert "14.2 tok/s" in out
    assert "oom" in out


def test_table_reports_no_working_config():
    res = SearchResult(
        ranked=[Ranked(_c("CUDA0"), Measurement(status="oom"))], winner=None)
    out = format_ranked_table(res)
    assert "NO WORKING CONFIG" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tuner_cli.py -v`
Expected: FAIL — `ModuleNotFoundError` (no `__main__`) / `ImportError` (no `format_ranked_table`).

- [ ] **Step 3: Write `soveryn/platform/tuner/__main__.py`**

```python
"""autotune CLI: python -m soveryn.platform.tuner <model_file>

Probe the rig, generate a candidate spread, measure each, print a ranked table.
Reports the winning config; does NOT auto-apply it to the router.
"""
from __future__ import annotations
import sys

from soveryn.platform.tuner.rig import probe_rig
from soveryn.platform.tuner.generate import generate_candidates, model_footprint
from soveryn.platform.tuner.search import run_search, SearchResult


def format_ranked_table(result: SearchResult) -> str:
    lines = []
    for r in result.ranked:
        c, m = r.candidate, r.measurement
        tag = "WINNER" if c is result.winner else "      "
        speed = f"{m.tok_s:.1f} tok/s" if (m.status == "ok" and m.tok_s) else m.status
        lines.append(f"{tag}  {c.device_map:<18} ot={c.ot_offload or '-':<9} "
                     f"kv={c.cache_type_k:<5} -> {speed}")
    if result.winner is None:
        lines.append("NO WORKING CONFIG — nothing ran ok (see statuses above)")
    return "\n".join(lines)


def _progress(i: int, n: int, cand) -> None:
    print(f"[{i + 1}/{n}] measuring {cand.backend}: {cand.device_map} "
          f"ot={cand.ot_offload or '-'} kv={cand.cache_type_k} …", flush=True)


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m soveryn.platform.tuner <model_file>", file=sys.stderr)
        return 2
    model_file = argv[0]
    rig = probe_rig()
    fp = model_footprint(model_file)
    print(f"model footprint: {fp / 1e9:.1f} GB | devices: {len(rig.devices)} | "
          f"RAM: {rig.total_ram_bytes / 1e9:.0f} GB", flush=True)
    cands = generate_candidates(model_file, rig)
    print(f"generated {len(cands)} candidates; measuring sequentially (blocking)…", flush=True)
    result = run_search(cands, devices=[d.index for d in rig.devices], on_progress=_progress)
    print(format_ranked_table(result))
    return 0 if result.winner else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests + full offline suite**

Run: `pytest tests/test_tuner_cli.py -v && pytest tests/ -k tuner -q`
Expected: PASS (CLI tests pass; all offline tuner tests green — the `@pytest.mark.rig` tests are skipped without the marker).

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/tuner/__main__.py tests/test_tuner_cli.py
git commit -m "feat(tuner): autotune CLI — ranked table + per-candidate progress (reports, no auto-apply)"
```

---

### Task 7: Real-rig end-to-end self-test

**Files:**
- Create: `tests/test_tuner_search_rig.py`

**Interfaces:**
- Consumes: everything above + the real `measure()`.

**PRECONDITION (verbatim in the test's docstring): the fleet must be DOWN — this launches real llama-server instances and needs the GPUs free. Run with `-m rig`.**

- [ ] **Step 1: Write the real-rig test** — `tests/test_tuner_search_rig.py`:

```python
"""End-to-end tuner self-test on the ACTUAL rack. Fleet must be DOWN.

Run: pytest tests/test_tuner_search_rig.py -m rig -v
Proves the whole loop: probe -> generate -> measure each -> pick a real winner.
"""
import os
import pytest

from soveryn.platform.tuner.rig import probe_rig
from soveryn.platform.tuner.generate import generate_candidates
from soveryn.platform.tuner.search import run_search

SMALL = "/mnt/soveryn_models/GGUF/gemma-4-E4B-it-Q8_0.gguf"


@pytest.mark.rig
def test_autotune_picks_a_real_winner_on_small_model():
    assert os.path.exists(SMALL), f"expected small test model at {SMALL}"
    rig = probe_rig()
    assert len(rig.devices) >= 1
    cands = generate_candidates(SMALL, rig)
    assert cands, "generator produced no candidates for a small model"
    result = run_search(cands, devices=[d.index for d in rig.devices])
    assert result.winner is not None, "no config ran ok on the real rig"
    win = [r for r in result.ranked if r.candidate is result.winner][0]
    assert win.measurement.status == "ok"
    assert (win.measurement.tok_s or 0) > 0
```

- [ ] **Step 2: Confirm it is collected but skipped without the marker**

Run: `pytest tests/test_tuner_search_rig.py -v`
Expected: the test is DESELECTED/skipped (no `-m rig`) — 0 run, no error. (The `rig` marker is already registered in `pyproject.toml` from the primitive.)

- [ ] **Step 3: Run it for real — REQUIRES FLEET DOWN (manual, human-gated)**

This step takes Aetheria + all agents offline. Do NOT run it as part of an automated pass — it is run deliberately, with the fleet stopped, exactly like the primitive's rig self-test. Command:
```bash
pytest tests/test_tuner_search_rig.py -m rig -v
```
Expected: PASS — the loop probes the rig, measures the candidate spread on the real GPUs, and picks an `ok` winner with `tok_s > 0`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_tuner_search_rig.py
git commit -m "test(tuner): real-rig end-to-end self-test — autotune picks a real winner (fleet-down, -m rig)"
```

---

## Self-Review notes (done)
- **Spec coverage:** rig+probe+bus_id (T2), backend field + binary resolution + unknown-backend error (T1), footprint (T3), generator spread incl. offload-always + subset spread + KV-quant + bus-id-blind + cap (T4), search + ranking + winner=None + survive-raise (T5), CLI ranked table + per-candidate progress (T6), real-rig e2e (T7). All spec sections mapped.
- **Type consistency:** `Candidate.backend`, `Device(index,backend,name,vram_bytes,pci_bus_id)`, `Rig(devices,total_ram_bytes)`, `run_search(candidates,*,devices,measure_fn,on_progress)`, `SearchResult(ranked,winner)`, `format_ranked_table(result)` — consistent across tasks.
- **measure_fn contract:** called as `measure_fn(cand, devices=devices)` — matches the real `measure(candidate, *, devices)` signature.
