"""A delegated Scotty must be able to author a whole file in one tool call.

2026-07-27: a Cross-Rail dispatch failed with llama-server HTTP 500 —
"Failed to parse tool call arguments as JSON ... missing closing quote". The
write_file argument carried a test file that ran past AgentLoop's 2048-token
default; generation stopped mid-token, the JSON string never closed, and the
server rejected the call. Nothing was wrong with the code being written.

This is easy to regress: the cap lives in a keyword argument that reads as a
harmless default, and the symptom looks like a parser bug rather than a budget.
"""
from __future__ import annotations

import soveryn.agents.loop as loop_module
from soveryn.platform.delegation.scotty_runner import (
    DELEGATION_MAX_TOKENS,
    scotty_run,
)


def test_budget_is_large_enough_for_a_real_source_file():
    """~4 chars/token: 8192 tokens is roughly a 30KB file. 2048 was ~8KB."""
    assert DELEGATION_MAX_TOKENS >= 8192


def test_runner_raises_the_cap_off_the_agentloop_default(tmp_path, monkeypatch):
    """The runner must OVERRIDE AgentLoop's default, not inherit it."""
    seen: dict = {}

    class _CapturingLoop:
        def __init__(self, agent, conv_store, **kwargs):
            seen.update(kwargs)

        def process_message(self, session_id, directive):
            class _R:
                content = "done"
            return _R()

    monkeypatch.setattr(loop_module, "AgentLoop", _CapturingLoop)

    scotty_run(str(tmp_path), "objective", "scope", "pytest tests/test_x.py -q")

    assert seen.get("max_tokens") == DELEGATION_MAX_TOKENS, (
        "scotty_run inherited AgentLoop's 2048-token default; a delegated file "
        "write will be truncated mid-JSON and the server will 500."
    )
