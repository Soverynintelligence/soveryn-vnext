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
