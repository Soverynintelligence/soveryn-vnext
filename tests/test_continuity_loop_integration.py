"""AgentLoop ↔ Cross-Surface Continuity integration tests.

Verifies Task 5: the Recent Activity Brief is injected as a system
message between persona and pinned memory, on both the sync and stream
paths, only when continuity is enabled, the agent is Aetheria, the
current session isn't autonomous, and cross-session activity actually
exists. All other paths must return zero injection — the brief layer
must be invisible to non-Aetheria agents and daemon sessions.
"""

from __future__ import annotations

import pytest

from soveryn.agents.loop import (
    AgentLoop,
    DoneEvent,
    TokenEvent,
)
from soveryn.inference.llama_server_client import (
    ChatResponse,
    StreamChunk,
)
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.continuity import BLOCK_HEADER, ContinuityConfig


# ─── Fixtures + fakes ────────────────────────────────────────────────────────

@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


class _CapturingChat:
    """Records every ChatRequest sent upstream so tests can inspect messages."""

    def __init__(self, *, content="OK", finish_reason="stop"):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        return ChatResponse(
            content=self.content,
            finish_reason=self.finish_reason,
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        )


class _CapturingStream:
    """Records every ChatRequest and emits a fixed chunk sequence."""

    def __init__(self, *, content="OK", finish_reason="stop"):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server, "timeout": timeout})
        content = self.content
        finish = self.finish_reason

        def _gen():
            yield StreamChunk(
                delta=content,
                finish_reason=None,
                tool_calls_delta=None,
                usage=None,
                raw={},
            )
            yield StreamChunk(
                delta="",
                finish_reason=finish,
                tool_calls_delta=None,
                usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                raw={},
            )

        return _gen()


def _seed_signal_session(
    store: ConversationStore,
    *,
    agent: str = "aetheria",
    title: str = "[signal] aetheria +19102489392",
    user_text: str = "earlier message on signal",
    assistant_text: str = "I noted it earlier",
) -> str:
    """Create a peer session with one user/assistant pair so it shows up
    in the brief. Returns the session_id."""
    sid = store.new_session(agent, title=title)
    store.save_turn(sid, agent, "user", user_text)
    store.save_turn(sid, agent, "assistant", assistant_text)
    return sid


def _make_loop(
    conv_store: ConversationStore,
    *,
    agent: str = "aetheria",
    chat_fn=None,
    stream_fn=None,
    continuity_config: ContinuityConfig | None = None,
    pinned_text: str = "PINNED",
    soul_text: str = "",
    coord_store=None,
) -> AgentLoop:
    return AgentLoop(
        agent_name=agent,
        conv_store=conv_store,
        chat_fn=chat_fn if chat_fn is not None else _CapturingChat(),
        stream_fn=stream_fn if stream_fn is not None else _CapturingStream(),
        system_prompt="PERSONA",
        pinned_text=pinned_text,
        soul_text=soul_text,
        continuity_config=continuity_config,
        coord_store=coord_store,
    )


def _system_contents(request) -> list[str]:
    return [m.content for m in request.messages if m.role == "system"]


# ─── 1. Brief is injected when cross-session activity exists ─────────────────

def test_agent_loop_injects_brief_when_cross_session_activity_exists(conv_store):
    current = conv_store.new_session("aetheria", title="ui chat about today")
    _seed_signal_session(conv_store)

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert any(BLOCK_HEADER in s for s in systems), (
        f"expected BLOCK_HEADER in one of the system messages; got {systems!r}"
    )
    # And the signal content is in the brief
    assert any("earlier message on signal" in s for s in systems)


# ─── 2. No brief in a daemon session ─────────────────────────────────────────

def test_agent_loop_no_brief_in_daemon_session(conv_store):
    current = conv_store.new_session("aetheria", title="[heartbeat] aetheria")
    _seed_signal_session(conv_store)

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
    )
    loop.process_message(current, "tick")

    systems = _system_contents(fake.calls[0]["request"])
    assert not any(BLOCK_HEADER in s for s in systems), (
        f"daemon session must not receive brief; got {systems!r}"
    )


# ─── 3. No brief when continuity disabled ────────────────────────────────────

def test_agent_loop_no_brief_when_config_disabled(conv_store):
    current = conv_store.new_session("aetheria", title="ui chat")
    _seed_signal_session(conv_store)

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=False, window_hours=24),
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert not any(BLOCK_HEADER in s for s in systems)


# ─── 4. No brief when continuity_config is None ──────────────────────────────

def test_agent_loop_no_brief_when_continuity_config_is_None(conv_store):
    current = conv_store.new_session("aetheria", title="ui chat")
    _seed_signal_session(conv_store)

    fake = _CapturingChat()
    loop = _make_loop(conv_store, chat_fn=fake, continuity_config=None)
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert not any(BLOCK_HEADER in s for s in systems)


# ─── 5. No brief for non-Aetheria agents ─────────────────────────────────────

def test_agent_loop_no_brief_for_non_aetheria_agents(conv_store):
    current = conv_store.new_session("eve", title="eve research")
    _seed_signal_session(conv_store, agent="eve", title="eve signal-like other")

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        agent="eve",
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        pinned_text="",  # Eve doesn't carry pinned in production
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert not any(BLOCK_HEADER in s for s in systems), (
        f"Eve must not receive brief; got {systems!r}"
    )


# ─── 6. No brief when no cross-session data exists ───────────────────────────

def test_agent_loop_no_brief_when_no_cross_session_data(conv_store):
    # Only the current session exists — no peer activity to surface.
    current = conv_store.new_session("aetheria", title="ui chat")

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert not any(BLOCK_HEADER in s for s in systems)


# ─── 7. Brief is placed between persona and pinned memory ────────────────────

def test_agent_loop_brief_placed_between_persona_and_pinned_memory(conv_store):
    current = conv_store.new_session("aetheria", title="ui chat")
    _seed_signal_session(conv_store)

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        pinned_text="PINNED_TOKEN",
        soul_text="SOUL_TOKEN",
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    # Find each marker's position.
    persona_idx = next(i for i, s in enumerate(systems) if s == "PERSONA")
    brief_idx = next(i for i, s in enumerate(systems) if BLOCK_HEADER in s)
    pinned_idx = next(i for i, s in enumerate(systems) if s == "PINNED_TOKEN")
    soul_idx = next(i for i, s in enumerate(systems) if s == "SOUL_TOKEN")
    assert persona_idx < brief_idx < pinned_idx < soul_idx, (
        f"expected persona < brief < pinned < soul; got "
        f"persona={persona_idx} brief={brief_idx} pinned={pinned_idx} soul={soul_idx}"
    )


# ─── 8. Brief failure does not break chat ────────────────────────────────────

def test_agent_loop_brief_failure_does_not_break_chat(conv_store, monkeypatch):
    current = conv_store.new_session("aetheria", title="ui chat")
    _seed_signal_session(conv_store)

    # Break the underlying store query so the brief helper hits its except clause.
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated continuity store failure")

    monkeypatch.setattr(
        "soveryn.platform.continuity.store.recent_cross_session_tails",
        _boom,
    )

    fake = _CapturingChat(content="reply ok")
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
    )
    response = loop.process_message(current, "hi")

    # Chat completed normally.
    assert response.content == "reply ok"
    # Brief absent (failure swallowed).
    systems = _system_contents(fake.calls[0]["request"])
    assert not any(BLOCK_HEADER in s for s in systems)
    # Assistant turn persisted.
    roles = [t.role for t in conv_store.load_history(current)]
    assert roles == ["user", "assistant"]


# ─── 9. Stream path also injects brief ───────────────────────────────────────

def test_agent_loop_stream_path_also_injects_brief(conv_store):
    current = conv_store.new_session("aetheria", title="ui chat")
    _seed_signal_session(conv_store)

    stream = _CapturingStream(content="streamed reply")
    loop = _make_loop(
        conv_store,
        stream_fn=stream,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
    )
    events = list(loop.process_message_stream(current, "hi"))

    # Final event is DoneEvent and TokenEvents fired in between.
    assert any(isinstance(e, TokenEvent) for e in events)
    assert isinstance(events[-1], DoneEvent)

    systems = _system_contents(stream.calls[0]["request"])
    assert any(BLOCK_HEADER in s for s in systems)
    assert any("earlier message on signal" in s for s in systems)


# ─── 10. Signal-prefixed peer session is the source of the brief content ─────

def test_agent_loop_signal_session_appears_in_brief(conv_store):
    """Positive end-to-end: a `[signal] aetheria +...` session IS surfaced —
    the prefix-filter test from Task 1 covered the autonomous-prefix denials;
    this test confirms the canonical Signal title flows through the loop and
    reaches the system messages."""
    current = conv_store.new_session("aetheria", title="ui chat")
    signal_title = "[signal] aetheria +19102489392"
    _seed_signal_session(
        conv_store,
        title=signal_title,
        user_text="reach me here later",
        assistant_text="I will hold the thread",
    )

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    brief = next((s for s in systems if BLOCK_HEADER in s), None)
    assert brief is not None
    assert signal_title in brief
    assert "reach me here later" in brief
    assert "I will hold the thread" in brief


# ─── 11. Active Focus block surfaces the coordination boards ─────────────────

def _coord_store(tmp_path):
    from soveryn.platform.lattice.legacy import LatticeStore
    from soveryn.platform.coordination.store import CoordinationStore
    db = tmp_path / "coord.db"
    LatticeStore(db)
    return CoordinationStore(db)


def test_agent_loop_injects_active_focus_from_coord_boards(conv_store, tmp_path):
    from soveryn.platform.continuity.active_focus import BLOCK_HEADER as AF_HEADER
    from soveryn.platform.coordination.types import CoordBoard

    current = conv_store.new_session("aetheria", title="ui chat")
    store = _coord_store(tmp_path)
    store.create_node(
        board=CoordBoard.BLUEPRINT, owner="aetheria",
        content="Hardware Moat audit: Quadro vs Blackwell vLLM optimization",
    )

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        coord_store=store,
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert any(AF_HEADER in s for s in systems), (
        f"expected ACTIVE FOCUS block; got {systems!r}"
    )
    assert any("Hardware Moat audit" in s for s in systems)


def test_agent_loop_no_active_focus_without_coord_store(conv_store):
    from soveryn.platform.continuity.active_focus import BLOCK_HEADER as AF_HEADER

    current = conv_store.new_session("aetheria", title="ui chat")
    _seed_signal_session(conv_store)

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        coord_store=None,
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert not any(AF_HEADER in s for s in systems)


def test_agent_loop_active_focus_cache_invalidates_on_board_change(conv_store, tmp_path):
    """A new coord node must appear on the NEXT turn — the continuity cache is
    fingerprinted on the active-focus render, so a board change busts it."""
    from soveryn.platform.continuity.active_focus import BLOCK_HEADER as AF_HEADER
    from soveryn.platform.coordination.types import CoordBoard

    current = conv_store.new_session("aetheria", title="ui chat")
    store = _coord_store(tmp_path)

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store,
        chat_fn=fake,
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        coord_store=store,
    )

    # Turn 1: empty boards → no active focus block.
    loop.process_message(current, "first")
    systems_1 = _system_contents(fake.calls[0]["request"])
    assert not any(AF_HEADER in s for s in systems_1)

    # A new directive lands on the boards between turns.
    store.create_node(
        board=CoordBoard.SIGNAL, owner="eve",
        content="New EU sovereign-AI funding window opened",
    )

    # Turn 2: cache is busted by the changed render → block appears.
    loop.process_message(current, "second")
    systems_2 = _system_contents(fake.calls[1]["request"])
    assert any(AF_HEADER in s for s in systems_2)
    assert any("EU sovereign-AI funding" in s for s in systems_2)


# ─── 12. Eve gets Active Focus (board awareness), not cross-session tails ────

def test_eve_gets_active_focus_but_not_cross_session_tails(conv_store, tmp_path):
    from soveryn.platform.continuity.active_focus import BLOCK_HEADER as AF_HEADER
    from soveryn.platform.coordination.types import CoordBoard

    current = conv_store.new_session("eve", title="eve research")
    # A peer (signal-like) session exists — Aetheria would surface it; Eve must NOT.
    _seed_signal_session(conv_store, agent="eve", title="[signal] eve other")
    store = _coord_store(tmp_path)
    store.create_node(board=CoordBoard.BLUEPRINT, owner="eve",
                      content="DeerFlow architecture comparison")

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store, agent="eve", chat_fn=fake, pinned_text="",
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        coord_store=store,
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    assert any(AF_HEADER in s for s in systems), "Eve should get Active Focus"
    assert any("DeerFlow architecture" in s for s in systems)
    # Cross-session recent-activity brief (Aetheria's multi-rail thing) stays off.
    assert not any(BLOCK_HEADER in s for s in systems), (
        "Eve must NOT get cross-session tails"
    )


def test_eve_active_focus_shows_her_delivery_state_to_aetheria(conv_store, tmp_path):
    """Eve's own node reads 'sent to aetheria, received' once the ledger shows
    Aetheria was triggered — the receipt mirror of Aetheria's dispatch view."""
    import sqlite3
    from soveryn.platform.continuity.active_focus import BLOCK_HEADER as AF_HEADER
    from soveryn.platform.coordination.types import CoordBoard

    current = conv_store.new_session("eve", title="eve research")
    store = _coord_store(tmp_path)
    n = store.create_node(board=CoordBoard.SIGNAL, owner="eve",
                          content="new EU funding lead")
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE coord_event_log SET triggered_agents='aetheria' WHERE node_id=?", (n.id,))

    fake = _CapturingChat()
    loop = _make_loop(
        conv_store, agent="eve", chat_fn=fake, pinned_text="",
        continuity_config=ContinuityConfig(enabled=True, window_hours=24),
        coord_store=store,
    )
    loop.process_message(current, "hi")

    systems = _system_contents(fake.calls[0]["request"])
    block = next((s for s in systems if AF_HEADER in s), None)
    assert block is not None
    assert "sent to aetheria, received" in block
