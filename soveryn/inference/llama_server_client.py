"""SOVERYN vNext — llama-server HTTP client.

Thin async/sync client for the llama.cpp server OpenAI-compatible API
(POST /v1/chat/completions, POST /v1/embeddings). Handles streaming SSE,
retries on transient 503s, and raises loud on connection failure at startup
(no silent fallbacks — spec §14). One client instance per ModelServer entry
in soveryn.config.runtime.
Placeholder; implementation comes in a later vNext step.
"""
