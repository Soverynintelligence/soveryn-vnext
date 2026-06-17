"""_fit_tool_loop_messages bounds the CURRENT turn's tool-result accumulation
so the prompt fits the context window (HTTP 400 exceed_context_size, hit
2026-06-17 when Vett read ~20 files in one turn → 198K tokens vs a 64K
window). Pairing-safe: never orphans a tool result from its assistant
tool_call; preserves the prelude through the last user turn.
"""
from soveryn.agents.loop import _fit_tool_loop_messages, _estimate_message_tokens
from soveryn.platform.inference.llama_server_client import ChatMessage


def _round(i, size):
    return [
        ChatMessage(role="assistant", content="", tool_calls=(
            {"id": f"c{i}", "type": "function",
             "function": {"name": "read_file", "arguments": "{}"}},
        )),
        ChatMessage(role="tool", content="x" * size, tool_call_id=f"c{i}"),
    ]


def _est(ms):
    return sum(_estimate_message_tokens(m) for m in ms)


def _no_orphan_tool_results(messages):
    seen_tc = False
    for m in messages:
        if m.role == "assistant" and m.tool_calls:
            seen_tc = True
        if m.role == "tool":
            assert seen_tc, "orphan tool result (no preceding assistant tool_call)"


def test_under_budget_unchanged():
    msgs = (ChatMessage(role="system", content="s"), ChatMessage(role="user", content="hi"))
    assert _fit_tool_loop_messages(msgs, 100_000) == msgs


def test_drops_oldest_rounds_to_fit():
    head = [ChatMessage(role="system", content="s" * 40),
            ChatMessage(role="user", content="read everything")]
    tail = []
    for i in range(20):
        tail += _round(i, 40 * 1024)  # ~10K tokens each → ~200K total
    msgs = tuple(head + tail)
    budget = 30_000
    out = _fit_tool_loop_messages(msgs, budget)
    assert _est(out) <= budget                       # fits
    assert out[0].role == "system" and out[1].role == "user"   # prelude preserved
    _no_orphan_tool_results(out)                     # pairing intact
    assert out[-1].role == "tool"                    # most recent round kept


def test_single_oversized_round_is_truncated():
    head = [ChatMessage(role="system", content="s"), ChatMessage(role="user", content="hi")]
    msgs = tuple(head + _round(0, 400 * 1024))        # one ~100K-token result
    budget = 20_000
    out = _fit_tool_loop_messages(msgs, budget)
    assert _est(out) <= budget
    _no_orphan_tool_results(out)
    tool_msgs = [m for m in out if m.role == "tool"]
    assert tool_msgs and "truncated to fit context" in tool_msgs[-1].content


def test_no_user_turn_returns_unchanged():
    # defensive: nothing to anchor on → leave as-is rather than corrupt pairing
    msgs = (ChatMessage(role="system", content="x" * 400_000),)
    assert _fit_tool_loop_messages(msgs, 10) == msgs
