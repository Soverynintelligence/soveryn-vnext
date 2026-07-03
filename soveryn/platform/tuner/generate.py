"""Rule-based candidate generator (pure). Emits a spread of sensible configs and
lets measurement decide the winner. It must NOT reason about topology.
"""
from __future__ import annotations
import glob
import os
import re
from soveryn.platform.tuner.candidate import Candidate
from soveryn.platform.tuner.rig import Rig


def model_footprint(model_file: str) -> int:
    """Total on-disk bytes of the model. For a split GGUF
    (…-00001-of-000NN.gguf) sum all sibling shards; else the file's own size."""
    m = re.match(r"^(.*)-\d{5}-of-\d{5}\.gguf$", os.path.basename(model_file))
    if m:
        d = os.path.dirname(model_file)
        shards = glob.glob(os.path.join(d, m.group(1) + "-*-of-*.gguf"))
        return sum(os.path.getsize(s) for s in shards)
    return os.path.getsize(model_file)


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
    if not rig.devices:
        return []                       # no devices -> no candidates (total function; no phantom launches)
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
