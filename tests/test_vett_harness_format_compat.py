"""Phase 1 blocker check: does Vett accept a harness-shaped message?

The vendored harness emits chat-completions messages tuned to
gpt-oss-20b. This test confirms our Vett (Qwen3.6-27B at the
llama-server router on :8090) accepts that shape and returns a
non-empty, non-error response. If this test fails, the entire
plan is blocked until the format question is resolved.

The test is GATED on the router being up; it is marked with
`@pytest.mark.integration` and skipped by default in unit runs.
"""
from __future__ import annotations
import os
import pytest

from soveryn.agents.vett.harness._format_probe import probe_vett_format_compat


@pytest.mark.integration
def test_vett_accepts_harness_message_shape():
    """Vett returns a non-empty, non-error response to a harness-shape probe."""
    router_url = os.environ.get("SOVERYN_ROUTER_URL", "http://127.0.0.1:8090")
    result = probe_vett_format_compat(router_url=router_url, model="vett-scotty")
    assert result.ok, f"Vett rejected harness message shape: {result.reason}"
    assert result.response_text, "Vett returned empty content"
    assert len(result.response_text) > 5, f"Vett response suspiciously short: {result.response_text!r}"
