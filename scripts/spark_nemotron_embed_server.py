#!/usr/bin/env python3
"""Nemotron-3-Embed-8B on the Spark (Lattice librarian).

Runs beside Lightning (vLLM :8001) as a *separate* process — same Nemotron
family / same box, not the Lightning chat weights. Chat models do not produce
Lattice-compatible vectors.

Listens on 10.10.10.2:8096 so the tower reaches it over the CX-7 fabric.
"""

from __future__ import annotations

import os
import threading

import numpy as np
from flask import Flask, jsonify, request
from sentence_transformers import SentenceTransformer

MODEL = os.environ.get(
    "SOVERYN_EMBED_MODEL",
    os.path.expanduser("~/models/Nemotron-3-Embed-8B-BF16"),
)
HOST = os.environ.get("SOVERYN_EMBED_HOST", "10.10.10.2")
PORT = int(os.environ.get("SOVERYN_EMBED_PORT", "8096"))

_m = SentenceTransformer(
    MODEL,
    device="cuda",
    model_kwargs={"torch_dtype": "bfloat16"},
)
_lock = threading.Lock()
try:
    DIM = int(_m.get_embedding_dimension())
except Exception:
    DIM = int(_m.get_sentence_embedding_dimension())

app = Flask("nemotron-embed-spark")


@app.post("/v1/embeddings")
def embeddings():
    b = request.get_json(force=True)
    inp = b.get("input")
    texts = [inp] if isinstance(inp, str) else list(inp or [])
    if not texts:
        return jsonify({"error": "empty input"}), 400
    kind = (b.get("prompt") or "document").lower()
    with _lock:
        enc = _m.encode_query if kind == "query" else _m.encode_document
        vecs = np.asarray(enc(texts, normalize_embeddings=True))
    data = [
        {"object": "embedding", "index": i, "embedding": v.tolist()}
        for i, v in enumerate(vecs)
    ]
    return jsonify(
        {
            "object": "list",
            "data": data,
            "model": "nemotron-embed-8b",
            "host": "spark",
        }
    )


@app.get("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "dim": DIM,
            "host": "spark",
            "model": MODEL,
        }
    )


if __name__ == "__main__":
    # threaded=True: vNext can embed query + write in parallel
    app.run(host=HOST, port=PORT, threaded=True)
