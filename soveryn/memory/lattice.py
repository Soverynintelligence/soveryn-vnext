"""SOVERYN vNext — Lattice semantic graph.

SQLite-backed graph with three layers: private (per-agent), global (shared),
library (RAG document chunks). Single embedding space via nomic-embed-text-v1.5
on the embeddings server (soveryn.config.runtime.embeddings_url()). Recall via
cosine-similarity node search with optional layer_filter.

Replaces ChromaDB entirely. No torch dependency for embeddings — HTTP only.
Placeholder; implementation comes in a later vNext step.
"""
