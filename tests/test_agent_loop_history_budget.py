"""Tests for the history token budgeter + context_usage reporting.

Two layers:
  1. Pure-function tests against _estimate_tokens / _apply_history_budget
  2. AgentLoop tests verifying budget is applied in both process_message
     and process_message_stream, and that ChatResponse.context_usage /
     DoneEvent.context_usage are populated correctly.
"""

from __future__ import annotations

import pytest

from soveryn.agents.loop import (
    AgentLoop,
    DoneEvent,
    TokenEvent,
    _apply_history_budget,
    _estimate_message_tokens,
    _estimate_tokens,
)
from soveryn.inference.llama_server_client import (
    ChatMessage,
    ChatRequest,
    ChatResponse,
    StreamChunk,
)
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import Node
from soveryn.platform.continuity.config import ContinuityConfig


# ─── Estimator ──────────────────────────────────────────────────────────────

def test_estimate_tokens_empty_string_returns_at_least_one():
    assert _estimate_tokens("") == 1


def test_estimate_tokens_short_text_returns_at_least_one():
    assert _estimate_tokens("hi") == 1


def test_estimate_tokens_uses_char_quarter_heuristic():
    # 40 chars → 10 tokens
    assert _estimate_tokens("a" * 40) == 10


def test_estimate_message_tokens_includes_per_message_overhead():
    # 40 chars → 10 content tokens + 5 overhead = 15
    msg = ChatMessage(role="user", content="a" * 40)
    assert _estimate_message_tokens(msg) == 15


# ─── Estimator: list-content (vision) regression ─────────────────────────────
# After SI-T1, ChatMessage.content can be list[dict]. A naive len(text or "") // 4
# would treat the list as ~part-count tokens (typically 2), under-counting a
# multimodal turn by ~100x and breaking _apply_history_budget for vision turns.

def test_estimate_message_tokens_handles_list_content():
    """Vision messages: count text-part chars (//4) + per-image cost (512).
    A naive len(list) would return ~1 instead of hundreds — that bug elides
    history rows it shouldn't or fails to trim when it should."""
    from soveryn.agents.loop import _PER_MESSAGE_OVERHEAD_TOKENS

    # text-only vision message (no images)
    msg = ChatMessage(role="user", content=[
        {"type": "text", "text": "a" * 400},
    ])
    # 400 chars / 4 = 100 text tokens, 0 image tokens, + overhead
    assert _estimate_message_tokens(msg) == 100 + _PER_MESSAGE_OVERHEAD_TOKENS


def test_estimate_message_tokens_counts_image_parts_at_per_image_cost():
    """One image = 512 tokens; two images = 1024 tokens; text adds on top."""
    from soveryn.agents.loop import _PER_IMAGE_TOKEN_COST, _PER_MESSAGE_OVERHEAD_TOKENS

    msg = ChatMessage(role="user", content=[
        {"type": "text", "text": "x" * 40},  # 10 text tokens
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
    ])
    expected = 10 + (2 * _PER_IMAGE_TOKEN_COST) + _PER_MESSAGE_OVERHEAD_TOKENS
    assert _estimate_message_tokens(msg) == expected


def test_estimate_message_tokens_handles_str_content_unchanged():
    """Regression: str-content path unchanged."""
    from soveryn.agents.loop import _PER_MESSAGE_OVERHEAD_TOKENS
    msg = ChatMessage(role="user", content="x" * 400)
    assert _estimate_message_tokens(msg) == 100 + _PER_MESSAGE_OVERHEAD_TOKENS


# ─── Budgeter: pure function ────────────────────────────────────────────────

def _msg(role: str, chars: int) -> ChatMessage:
    return ChatMessage(role=role, content="x" * chars)


def test_budgeter_empty_history_returns_noop():
    prelude = (_msg("system", 40),)
    history: tuple[ChatMessage, ...] = ()
    trimmed, marker, elided = _apply_history_budget(prelude, history, budget=1000)
    assert trimmed == ()
    assert marker is None
    assert elided == 0


def test_budgeter_under_budget_returns_noop():
    prelude = (_msg("system", 40),)  # 15 tokens
    history = (_msg("user", 40), _msg("assistant", 40), _msg("user", 40))  # 45
    trimmed, marker, elided = _apply_history_budget(prelude, history, budget=1000)
    assert trimmed == history
    assert marker is None
    assert elided == 0


def test_budgeter_over_budget_drops_oldest_and_returns_marker():
    # PR5: default charge_prelude=False — only history counts against budget.
    # 4 history messages, each 40 chars → 15 tokens each → 60 total
    # budget 50 → drop oldest until history ≤ 50 (drop 1 → 45)
    prelude = (_msg("system", 40),)  # not charged by default
    history = (
        _msg("user", 40),       # oldest
        _msg("assistant", 40),
        _msg("user", 40),
        _msg("assistant", 40),  # newest (preserved)
    )
    trimmed, marker, elided = _apply_history_budget(prelude, history, budget=50)
    assert elided == 1
    assert marker is not None
    assert marker.role == "system"
    assert "elided" in marker.content
    assert trimmed[-1] is history[-1]  # newest always preserved
    # Turn-reaper drops the whole oldest user+assistant pair, not one message.
    assert trimmed == (history[2], history[3])
    assert len(trimmed) == 2


def test_budgeter_charge_prelude_true_legacy_envelope():
    """charge_prelude=True restores pre-PR5: prelude + history share budget."""
    prelude = (_msg("system", 40),)  # 15 tokens
    history = (
        _msg("user", 40),
        _msg("assistant", 40),
        _msg("user", 40),
        _msg("assistant", 40),
    )
    # 15 + 60 = 75; budget 50 → drop until charged ≤ 50
    trimmed, marker, elided = _apply_history_budget(
        prelude, history, budget=50, charge_prelude=True,
    )
    assert elided >= 1
    assert marker is not None
    assert trimmed[-1] is history[-1]


def test_budgeter_fat_prelude_does_not_elide_history_that_fits():
    """PR5 acceptance (a): huge prelude must not starve history under history-only."""
    prelude = (_msg("system", 40_000),)  # ~10k tokens of prelude — free under PR5
    history = (
        _msg("user", 40),
        _msg("assistant", 40),
        _msg("user", 40),
    )  # 45 history tokens
    trimmed, marker, elided = _apply_history_budget(
        prelude, history, budget=6_000, charge_prelude=False,
    )
    assert trimmed == history
    assert marker is None
    assert elided == 0


def test_budgeter_single_turn_over_budget_keeps_just_newest_no_marker():
    """When even the most recent turn alone blows budget, we can't help —
    keep just the newest turn, report 0 elided (we didn't trim — the
    overflow is a separate problem that surfaces via context_usage)."""
    # History-only: one huge user turn over budget with no older turns to drop.
    prelude = (_msg("system", 40),)
    history = (_msg("user", 4000),)  # ~1005 tokens alone
    trimmed, marker, elided = _apply_history_budget(prelude, history, budget=100)
    assert trimmed == history
    assert marker is None
    assert elided == 0


def test_budgeter_preserves_newest_when_multi_turn_overflow():
    """Multi-turn history where the just-saved newest turn alone fits but
    everything older doesn't: drop everything else, keep newest, add marker."""
    prelude = (_msg("system", 40),)  # not charged by default
    history = (
        _msg("user", 4000),       # 1005 tokens
        _msg("assistant", 4000),  # 1005 tokens
        _msg("user", 40),         # 15 tokens (newest)
    )
    trimmed, marker, elided = _apply_history_budget(prelude, history, budget=100)
    assert trimmed == (history[-1],)
    assert marker is not None
    assert elided == 1  # one older turn (user+assistant), not two messages


# ─── AgentLoop integration ──────────────────────────────────────────────────

class _CapturingChat:
    def __init__(self, *, content="OK", prompt_tokens=42):
        self.calls = []
        self.content = content
        self.prompt_tokens = prompt_tokens

    def __call__(self, request, server, timeout=60.0):
        self.calls.append(request)
        return ChatResponse(
            content=self.content,
            finish_reason="stop",
            tool_calls=None,
            usage={"prompt_tokens": self.prompt_tokens, "completion_tokens": 1, "total_tokens": self.prompt_tokens + 1},
            raw={},
        )


@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


def test_process_message_returns_context_usage_when_budget_set(conv_store):
    chat = _CapturingChat(prompt_tokens=1234)
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=chat,
        history_token_budget=20_000, context_window=32_768,
        soul_text="stable soul",
    )
    sid = conv_store.new_session("aetheria")
    response = loop.process_message(sid, "hello")
    assert response.context_usage is not None
    assert response.context_usage["prompt_tokens"] == 1234
    assert response.context_usage["budget_tokens"] == 20_000
    assert response.context_usage["context_window"] == 32_768
    assert response.context_usage["elided_turns"] == 0
    # PR5 fields
    assert "prelude_tokens" in response.context_usage
    assert "history_tokens" in response.context_usage
    assert "total_input_tokens_est" in response.context_usage
    assert response.context_usage["prelude_soft_budget"] == 3500
    assert response.context_usage["total_input_soft_budget"] == 12_000
    assert response.context_usage["prelude_tokens"] >= 1
    assert response.context_usage["history_tokens"] >= 1


def test_process_message_context_usage_is_none_without_budget(conv_store):
    chat = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=chat)
    sid = conv_store.new_session("aetheria")
    response = loop.process_message(sid, "hello")
    assert response.context_usage is None


def test_process_message_elides_when_history_exceeds_budget(conv_store):
    """Seed conv_store with a long history; verify the chat call sees a
    trimmed message list with the elision marker present."""
    chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=chat,
        history_token_budget=200, context_window=32_768,
        soul_text="x" * 8000,  # fat prelude — must NOT force elision alone (PR5)
    )
    sid = conv_store.new_session("aetheria")
    # Seed 6 prior turns (3 user + 3 assistant) of ~400 chars each. With a
    # 200-token history-only budget the budgeter must drop most of them.
    for i in range(3):
        conv_store.save_turn(sid, "aetheria", "user", "u" * 400 + f" turn {i}")
        conv_store.save_turn(sid, "aetheria", "assistant", "a" * 400 + f" turn {i}")
    response = loop.process_message(sid, "newest question")
    assert response.context_usage["elided_turns"] > 0
    assert response.context_usage["history_tokens"] <= 200 + 50  # after trim, near budget
    # The request sent to chat_fn must contain the elision marker as a system msg
    request = chat.calls[-1]
    system_contents = [m.content for m in request.messages if m.role == "system"]
    assert any("elided" in c for c in system_contents), \
        f"elision marker missing from system messages: {system_contents}"


def test_process_message_history_only_budget_works_for_kernel(conv_store):
    """PR5 acceptance (d): same history-only semantics for a non-Aetheria agent."""
    chat = _CapturingChat()
    loop = AgentLoop(
        "kernel", conv_store, chat_fn=chat,
        history_token_budget=6_000, context_window=32_768,
        soul_text="kernel soul " * 200,  # non-empty prelude
    )
    sid = conv_store.new_session("kernel")
    # History that fits comfortably in 6000 tokens — must not elide.
    for i in range(3):
        conv_store.save_turn(sid, "kernel", "user", f"short user {i}")
        conv_store.save_turn(sid, "kernel", "assistant", f"short asst {i}")
    response = loop.process_message(sid, "hello kernel")
    assert response.context_usage is not None
    assert response.context_usage["budget_tokens"] == 6_000
    assert response.context_usage["elided_turns"] == 0
    assert response.context_usage["prelude_tokens"] >= 1
    assert response.context_usage["history_tokens"] >= 1


def test_process_message_reuses_continuity_prelude_until_fingerprint_changes(conv_store, monkeypatch):
    import soveryn.platform.continuity.brief as brief_mod

    calls = []

    def fake_brief(tails, *, config, now=None):
        calls.append(tuple(t.session_id for t in tails))
        return f"continuity-render-{len(calls)}"

    monkeypatch.setattr(brief_mod, "build_recent_activity_brief", fake_brief)
    other_sid = conv_store.new_session("aetheria", title="other rail")
    conv_store.save_turn(other_sid, "aetheria", "user", "other question")
    conv_store.save_turn(other_sid, "aetheria", "assistant", "other answer")

    chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=chat,
        system_prompt="persona-anchor",
        pinned_text="stable pinned memory",
        soul_text="stable soul",
        continuity_config=ContinuityConfig(
            enabled=True,
            window_hours=6,
            token_budget=1500,
            per_session_cap=400,
        ),
    )
    sid = conv_store.new_session("aetheria", title="current rail")

    loop.process_message(sid, "first question")
    first_system = [m.content for m in chat.calls[-1].messages if m.role == "system"]
    loop.process_message(sid, "second question")
    second_system = [m.content for m in chat.calls[-1].messages if m.role == "system"]

    assert calls == [(other_sid,)]
    assert first_system == second_system
    assert first_system == [
        "persona-anchor",
        "continuity-render-1",
        "stable pinned memory",
        "stable soul",
    ]

    conv_store.save_turn(other_sid, "aetheria", "user", "new other question")
    loop.process_message(sid, "third question")
    third_system = [m.content for m in chat.calls[-1].messages if m.role == "system"]

    assert calls == [(other_sid,), (other_sid,)]
    assert third_system[1] == "continuity-render-2"


class _FakeLattice:
    def __init__(self):
        self.calls = 0

    def find_nodes_by_embedding(self, agent, embedding, *, limit, threshold):
        self.calls += 1
        node = Node(
            id=f"node-{self.calls}",
            type="fact",
            layer="private",
            agent=agent,
            content=f"cached recall {self.calls}",
            intensity=0.5,
            salience=0.5,
            access_count=0,
            tags=(),
            created_at="2026-06-11T00:00:00",
            updated_at="2026-06-11T00:00:00",
            embedding=(1.0,),
            intent=None,
            provenance={
                "cls": "told",
                "source": "jon",
                "confidence": 1.0,
                "temporal_context": "test",
                "generator": "test",
            },
        )
        return ((node, 0.99),)


def test_process_message_reuses_recall_prelude_for_short_thread_window(conv_store):
    chat = _CapturingChat()
    lattice = _FakeLattice()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=chat,
        system_prompt="persona-anchor",
        lattice_store=lattice,
        recall_k=5,
        recall_threshold=0.70,
        embed_fn=lambda _text: (1.0,),
    )
    sid = conv_store.new_session("aetheria")

    loop.process_message(sid, "first topic turn")
    first_system = [m.content for m in chat.calls[-1].messages if m.role == "system"]
    loop.process_message(sid, "second related turn")
    second_system = [m.content for m in chat.calls[-1].messages if m.role == "system"]

    assert lattice.calls == 1
    assert first_system == second_system
    assert any("cached recall 1" in c for c in first_system)




# ─── Streaming path ─────────────────────────────────────────────────────────

class _CapturingStream:
    """Fake stream_fn that emits one token + finish_reason + usage."""
    def __init__(self, *, content="OK", prompt_tokens=42):
        self.calls = []
        self.content = content
        self.prompt_tokens = prompt_tokens

    def __call__(self, request, server, timeout=60.0):
        self.calls.append(request)
        yield StreamChunk(
            delta=self.content,
            finish_reason="stop",
            tool_calls_delta=None,
            usage={"prompt_tokens": self.prompt_tokens, "completion_tokens": 1, "total_tokens": self.prompt_tokens + 1},
            raw={},
        )


def test_stream_done_event_carries_context_usage_when_budget_set(conv_store):
    stream = _CapturingStream(prompt_tokens=999)
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=_CapturingChat(),
        stream_fn=stream,
        history_token_budget=20_000, context_window=32_768,
    )
    sid = conv_store.new_session("aetheria")
    events = list(loop.process_message_stream(sid, "hi"))
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].context_usage is not None
    assert done[0].context_usage["prompt_tokens"] == 999
    assert done[0].context_usage["budget_tokens"] == 20_000
    assert done[0].context_usage["context_window"] == 32_768
    assert done[0].context_usage["elided_turns"] == 0


def test_stream_done_event_context_usage_none_without_budget(conv_store):
    stream = _CapturingStream()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=_CapturingChat(),
        stream_fn=stream,
    )
    sid = conv_store.new_session("aetheria")
    events = list(loop.process_message_stream(sid, "hi"))
    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].context_usage is None
