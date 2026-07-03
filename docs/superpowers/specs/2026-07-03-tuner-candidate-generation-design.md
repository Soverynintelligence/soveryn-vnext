# Heterogeneous Inference Tuner — Step 2: Candidate Generation + Search Loop (Design)

**Date:** 2026-07-03
**Status:** Design for review.
**Scope:** Layer 2 of the tuner — the **search loop** that uses the (already-built) measurement
primitive to *automatically* find the best run-config for a model on the mixed rig. A rule-based
candidate generator produces a sensible spread of configs; the loop measures each and picks the
empirical winner. **Backend is promoted to a Candidate field** so the design is heterogeneous-ready
(NVIDIA + AMD) without hardcoding, but v1 exercises **CUDA only** in practice.

Builds on: `2026-07-02-tuner-measurement-primitive-design.md` (Layer 1, DONE — `measure()` +
`classify()`, 21 offline + 4 rig tests green). Layer 3 (the analytical cost model) is a later spec.

## Why this, and the founding principle it inherits

The primitive answers "did *this one* config work, and how fast?" — honestly, with clean teardown.
Layer 2 turns that into "find me the best config," which is what makes the system *self-optimize*.

The generator is deliberately **dumb**: it emits a spread of sensible candidates and lets
**measurement decide the winner empirically.** It does not try to be right — precision is Layer 3's
job. This is the whole philosophy: you can't reason your way to the best config on a heterogeneous
rig (especially once AMD is involved — see below); you measure.

**Inherited rule — "a dimension that changes the search space must be a FIELD, not a constant."**
The primitive already made `model_file` (the quant) a field, not a fixed engine input, *because the
quant defines which configs fit at all.* The **identical logic applies to the backend**: which
binary/backend you launch determines *which configs even exist* (a CUDA build cannot see an AMD GPU;
spanning both needs Vulkan or RPC). So the backend cannot stay the hardcoded `_BINARY` constant it is
today. **We promote it to a field now** — v1 only ever resolves it to the CUDA build, but the seam is
there, so adding AMD later is "register a backend + widen the generator," never "tear out a hardcoded
assumption." (We watched exactly that hardcoded-constant trap bite last night: the M3 arch wasn't in
the fixed binary. Same lesson, applied ahead of time.)

## Components (each a pure unit or a thin probe — mirrors the primitive's purity split)

### `rig.py` — what hardware we're optimizing for
```
@dataclass(frozen=True)
class Device:
    index: int          # per-backend device index
    backend: str        # "cuda" (v1) | future: "vulkan" | "rocm" | "rpc"
    name: str           # e.g. "NVIDIA RTX PRO 5000 Blackwell"
    vram_bytes: int
    pci_bus_id: str     # e.g. "0000:45:00.0" — captured for Layer 3 topology reasoning
                        # (NOT used by the Layer-2 generator; see the topology note under generate.py)

@dataclass(frozen=True)
class Rig:
    devices: tuple[Device, ...]
    total_ram_bytes: int

def probe_rig() -> Rig            # builds a Rig from the live machine
```
- `Rig`/`Device` are **pure data** — the generator's input, so the rule logic is unit-testable with
  no GPU.
- `probe_rig()` is the only hardware-touching bit. v1 uses **`pynvml`** (already a dependency —
  `measure.py` imports it for VRAM/ECC telemetry) for CUDA devices + their VRAM + bus IDs, and `free`
  for RAM. Using pynvml (not regex over `nvidia-smi` text) is more robust across driver versions and
  costs nothing new. Extensible later to `rocminfo` / `vulkaninfo` for AMD — additive, no change to
  `Rig`'s shape.
- `pci_bus_id` is **captured but unused in Layer 2** — it exists so Layer 3's cost model can reason
  about PCIe topology (root complex / generation) later. The dumb generator must NOT use it.
- Device identity is **backend-aware from line one** (`backend` + `index`), so a future AMD device is
  just another `Device` with `backend="vulkan"` (or `"rocm"`).

### `candidate.py` — ADD the backend field (only change to the existing primitive)
Add to the existing frozen `Candidate`:
```
    backend: str = "cuda"      # which build/backend launches this config
```
- Default `"cuda"` → 100% backward-compatible with the primitive's existing Candidates and tests.
- `device_map` names remain backend-scoped (`"CUDA0,CUDA2"` for cuda; a vulkan candidate would use
  vulkan device names). The generator produces names consistent with each candidate's `backend`.

### `measure.py` — resolve the binary from the backend (small change)
- Replace the hardcoded `_BINARY` constant's *sole* use with a lookup:
  `_BACKEND_BINARY = {"cuda": "~/llama.cpp_head/build/bin/llama-server"}` and resolve
  `_BACKEND_BINARY[candidate.backend]`. v1 has one entry. Unknown backend → a clear error (not a
  silent fall-through). Everything else in `measure()` is unchanged.

### `generate.py` — the rule-based generator (pure)
```
def model_footprint(model_file: str) -> int        # sum of the GGUF split shard bytes
def generate_candidates(model_file: str, rig: Rig) -> list[Candidate]
```
Rules (v1, CUDA devices only since the probe finds only CUDA today — but written against `rig.devices`
generically, so mixed-backend rigs would naturally yield backend-appropriate candidates later):
1. **All-devices, even split, no offload** — if `footprint` plausibly fits total VRAM.
2. **A SPREAD of device subsets that fit** — not just the VRAM-minimal one. Emit every single device
   that fits alone (e.g. Blackwell-only), plus sensible pairs, plus all-devices. **This is the correct
   answer to the topology concern:** the Blackwell (PCIe 5.0) alone may beat a Turing-split (PCIe 3.0)
   even with less total VRAM — so we *measure* both and let the winner emerge. We do NOT make the
   generator topology-aware (that would smuggle Layer-3 cost-model reasoning into the dumb generator,
   violating the founding principle). The generator stays dumb; it just emits the topology-relevant
   options so measurement can decide. Cap the spread (e.g. ≤ ~6 candidates total) to bound search time.
3. **Expert-offload (`-ot exps=CPU`), all devices** — emitted for the big-model path (attention on GPU,
   experts in RAM; how the 235B/M3 run). **Correct mechanism note:** `-ot` matches a *tensor-name
   pattern*; a dense model has no `*exps*` tensors, so this flag is a **no-op** on dense models — it is
   *not* extra overhead, it's simply a **redundant duplicate** of candidate #1 (one wasted ~60s run).
   v1 accepts that waste (dumb). Cheap future dedup: read the GGUF expert-count and skip this on dense
   models — deferred, not gold-plated here.
4. **One KV-quant variant** (`cache_type_k/v = "q8_0"`) of the winner-shaped config — buys VRAM/context.

The **fit heuristic is deliberately crude**: `footprint * HEADROOM + FIXED_OVERHEAD ≤ vram`. It only
prunes *obviously* doomed configs. A wrong guess is caught by `measure()` as an honest `oom` and that
candidate simply loses. No precision here by design.

### `search.py` — the loop
```
@dataclass
class Ranked:
    candidate: Candidate
    measurement: Measurement

@dataclass
class SearchResult:
    ranked: list[Ranked]          # all candidates, sorted: ok-by-tok_s desc, then failures
    winner: Candidate | None      # None if nothing came back ok

def run_search(candidates, *, devices, measure_fn=measure) -> SearchResult
```
- **Sequential** (shared GPUs force one-at-a-time). Each candidate → `measure_fn(candidate, devices=…)`.
- **`devices` = the full set of the rig's GPU indices** (e.g. `[0,1,2]`). It sets
  `CUDA_VISIBLE_DEVICES` for *every* launch so the `CUDA0/1/2` indices stay **stable across
  candidates**; the candidate's own `device_map` (`"CUDA0"` vs `"CUDA0,CUDA2"`) is what selects the
  *subset* actually used. So the single `devices` list and per-candidate `device_map` do not conflict —
  one fixes the visible numbering, the other picks among it.
- `measure_fn` is **injectable** — the offline test seam (feed canned `Measurement`s; the real run
  uses the primitive).
- **A candidate that raises does not kill the search** — it's recorded as a failed `Ranked` (synthetic
  `Measurement(status="load_failed", detail=<exc>)`) and the loop continues.
- **Winner = max `tok_s` among `status=="ok"`.** If none are `ok`, `winner=None` — we do **not** fake
  one; the ranked table shows why each failed.

### `__main__` — the `autotune` CLI
`python -m soveryn.platform.tuner <model_file>` → `probe_rig()` → `model_footprint()` →
`generate_candidates()` → `run_search()` → print the ranked table + the winning flag line. Point it at
a model, it reports the best config (and *why* the others lost). v1 **reports**, it does not
auto-apply to the router.

**The search is a blocking operation** — sequential launches, each ~30–90s (load + benchmark +
teardown), so a ~6-candidate run is several minutes. The CLI **prints per-candidate progress as it
goes** (`[2/6] measuring cuda: CUDA0,CUDA2 -ot exps=CPU … ok 9.4 tok/s`) so it's never a silent
multi-minute hang. (This is the same class of "don't let a long operation look stalled" we care about
elsewhere.)

## Data flow
`model_file` → footprint (stat shards) + `probe_rig()` → `generate_candidates()` → list[Candidate] →
`run_search()` (each through `measure()`, sequential, clean teardown between) → `SearchResult` (ranked
+ winner) → printed table.

## Testing (the proof it works)
- **`test_tuner_generate.py`** (offline): feed a synthetic `Rig` + a footprint → assert the spread
  (fits → all-GPU **plus a subset spread**: every single device that fits alone, sensible pairs;
  big → offload always present; a KV-quant variant present; total candidates capped; every emitted
  candidate's `device_map` matches its `backend`). Assert the generator **ignores `pci_bus_id`**
  (topology is not a Layer-2 input — same output regardless of bus IDs).
- **`test_tuner_search.py`** (offline, fake `measure_fn`): max-tok_s-among-ok wins; `winner=None` when
  all fail; a candidate whose `measure_fn` *raises* is recorded and the search continues; ranking order
  (ok desc, then failures).
- **`test_tuner_rig.py`** (offline): `probe_rig` parses injected `nvidia-smi`/`free` output into the
  right `Rig`; `model_footprint` sums shard sizes correctly.
- **`test_tuner_search_rig.py`** (`@pytest.mark.rig`, fleet down): end-to-end on a real small model —
  `autotune` picks an `ok` winner with a plausible `tok_s`. The proof on the actual rack.

## Scope / out of scope
**IN:** `rig.py` (+probe), the `backend` field + binary resolution, `generate.py`, `search.py`, the CLI,
the tests above. CUDA backend only in practice.
**OUT (named, deferred):**
1. The analytical cost model (Layer 3).
2. Quant-search (varying `model_file` across quants — the field exists, not exercised here).
3. **Actually building/running non-CUDA backends** (Vulkan/ROCm/RPC). The design is AMD-*ready* (backend
   is a field, device identity is backend-aware); no AMD backend is registered, built, or tested until
   there's an AMD card to measure against. Claim status: *heterogeneous mixing via Vulkan/RPC is
   believed-possible, NOT verified — the tuner is how it would be verified.*
4. Auto-applying the winner to the router (v1 reports only).

## Project constraint (load-bearing, non-technical)
**This is "in the meantime" work — it parks the instant the Shepherd callback lands.** Shepherd revenue
is the higher-value event. Keep Layer 2 tight: the deliverable is the green real-rig end-to-end test
(autotune picks a real winner). No gold-plating.
