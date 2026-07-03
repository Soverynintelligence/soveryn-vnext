"""Candidate: one inference config for the tuner to measure.

`model_file` carries the quant — it is a FIELD, never a fixed engine input,
so quant-search is later just varying this field across a list.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    model_file: str            # absolute path to the GGUF — the quant lives here
    device_map: str            # e.g. "CUDA0,CUDA2"
    ngl: int
    ctx_size: int
    cache_type_k: str
    cache_type_v: str
    flash_attn: bool
    tensor_split: str | None = None
    ot_offload: str | None = None
    backend: str = "cuda"      # which build/backend launches this config (quant-like: a field, not a constant)


def to_llama_server_args(c: Candidate, *, host: str, port: int) -> list[str]:
    """Translate a Candidate into llama-server CLI flags.

    Flags use explicit values where the HEAD build requires them (`-fa on|off`).
    Optional fields (tensor_split, ot_offload) are omitted when None.
    """
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
