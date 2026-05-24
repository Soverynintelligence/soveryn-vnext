"""Tests for soveryn.agents.loop. tmp_path SQLite, injected fake chat_fn."""

import sqlite3
from dataclasses import dataclass
from typing import Any
import pytest

from soveryn.agents.loop import AgentLoop, AgentLoopError
from soveryn.inference.llama_server_client import (
    ChatRequest,
    ChatResponse,
    LlamaServerError,
    LlamaServerTimeout,
)
from soveryn.inference.routing import RoutingError
from soveryn.memory.conversation_store import ConversationStore


# ─── Fixtures + fakes ────────────────────────────────────────────────────────

@pytest.fixture
def conv_store(tmp_path):
    return ConversationStore(tmp_path / "conv.db")


class _CapturingChat:
    """Fake chat_fn that records every call and returns a configured response."""

    def __init__(self, *, content="OK", finish_reason="stop", raise_exc=None):
        self.calls: list[dict] = []
        self.content = content
        self.finish_reason = finish_reason
        self.raise_exc = raise_exc

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({
            "request": request,
            "server": server,
            "timeout": timeout,
        })
        if self.raise_exc is not None:
            raise self.raise_exc
        return ChatResponse(
            content=self.content,
            finish_reason=self.finish_reason,
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={"choices": [{"message": {"content": self.content}}]},
        )


# ─── Constructor: routing at construction ────────────────────────────────────

def test_construction_routes_aetheria_to_8085(conv_store):
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.server.port == 8085
    assert loop.agent_name == "aetheria"


def test_construction_routes_vett_to_8084(conv_store):
    loop = AgentLoop("vett", conv_store, chat_fn=_CapturingChat())
    assert loop.server.port == 8084


def test_construction_normalizes_name_case(conv_store):
    loop = AgentLoop("  Aetheria  ", conv_store, chat_fn=_CapturingChat())
    assert loop.agent_name == "aetheria"
    assert loop.server.name == "aetheria_primary"


@pytest.mark.parametrize("name", [
    "scout", "vision", "tinker", "forge",
    "ares_llm", "aetheria_public", "telegram", "chromadb",
])
def test_construction_rejects_retired_agents(conv_store, name):
    with pytest.raises(RoutingError, match="retired"):
        AgentLoop(name, conv_store, chat_fn=_CapturingChat())


def test_construction_rejects_unknown_agent(conv_store):
    with pytest.raises(RoutingError, match="No route"):
        AgentLoop("fnord", conv_store, chat_fn=_CapturingChat())


def test_construction_failure_never_calls_chat(conv_store):
    fake = _CapturingChat()
    with pytest.raises(RoutingError):
        AgentLoop("scout", conv_store, chat_fn=fake)
    assert fake.calls == []


# ─── Session validation (constraint 8) ───────────────────────────────────────

def test_missing_session_raises_before_chat(conv_store):
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(AgentLoopError, match="does not exist"):
        loop.process_message("not-a-real-session", "hi")
    # Constraint 8: no chat dispatched
    assert fake.calls == []
    # Constraint 8: no user turn saved (session doesn't exist anyway,
    # but a defensive INSERT would still write a row keyed on the bad id)
    with sqlite3.connect(str(conv_store.db_path)) as c:
        rows = c.execute(
            "SELECT COUNT(*) FROM conversations WHERE session_id = ?",
            ("not-a-real-session",),
        ).fetchone()
    assert rows[0] == 0


def test_session_for_other_agent_raises_before_chat(conv_store):
    """A Vett session can't be used by an Aetheria loop."""
    vett_session = conv_store.new_session("vett")
    fake = _CapturingChat()
    aetheria_loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(AgentLoopError, match="belongs to agent 'vett'"):
        aetheria_loop.process_message(vett_session, "hi")
    assert fake.calls == []
    # No user turn snuck into the wrong session
    assert conv_store.load_history(vett_session) == ()


# ─── Happy path ──────────────────────────────────────────────────────────────

def test_happy_path_returns_raw_chat_response(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="hi back")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    response = loop.process_message(sid, "hello")
    assert isinstance(response, ChatResponse)
    assert response.content == "hi back"
    assert response.finish_reason == "stop"


def test_user_turn_then_assistant_turn_saved(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="response text")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "user said this")
    history = conv_store.load_history(sid)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "user said this"
    assert history[1].role == "assistant"
    assert history[1].content == "response text"


def test_assistant_turn_stores_content_only_not_raw_metadata(conv_store):
    """Constraint 4: response.tool_calls / usage / raw must NOT land in conversations."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="just the text")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "hi")
    history = conv_store.load_history(sid)
    assistant_turn = history[1]
    assert assistant_turn.content == "just the text"
    # The saved content must not include any serialized metadata
    assert "tool_calls" not in assistant_turn.content
    assert "usage" not in assistant_turn.content
    assert "{" not in assistant_turn.content


def test_history_passed_to_chat_as_immutable_tuple(conv_store):
    """Constraint 7."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "msg one")
    request = fake.calls[0]["request"]
    assert isinstance(request, ChatRequest)
    assert isinstance(request.messages, tuple)
    with pytest.raises((TypeError, AttributeError)):
        request.messages.append(None)  # tuple has no .append


def test_history_includes_prior_turns_on_subsequent_calls(conv_store):
    """Multi-turn: each process_message should see the full prior history."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="reply-1")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "turn-1")
    fake.content = "reply-2"
    loop.process_message(sid, "turn-2")
    # The second call's request should carry: system, u1, a1, u2 (4 messages)
    second_request = fake.calls[1]["request"]
    # Extract just the user/assistant roles to verify history accumulation
    # (system is prepended each time, so we skip it for this assertion)
    contents = [m.content for m in second_request.messages if m.role != "system"]
    assert contents == ["turn-1", "reply-1", "turn-2"]


def test_routing_resolved_once_at_construction(conv_store):
    """Constraint 1: server is bound at __init__; the same one is passed to every chat call."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "a")
    loop.process_message(sid, "b")
    loop.process_message(sid, "c")
    servers = [c["server"] for c in fake.calls]
    assert all(s is loop.server for s in servers)


# ─── Failure modes ───────────────────────────────────────────────────────────

def test_chat_failure_leaves_user_turn_saved(conv_store):
    """Constraint 6: honest state. If chat blows up after we saved the user turn,
    that user turn stays in the DB. No rollback magic."""
    sid = conv_store.new_session("aetheria")
    err = LlamaServerError(status_code=500, detail="boom", server_name="vett_scotty_shared")
    fake = _CapturingChat(raise_exc=err)
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerError):
        loop.process_message(sid, "user message that survives")
    history = conv_store.load_history(sid)
    assert len(history) == 1
    assert history[0].role == "user"
    assert history[0].content == "user message that survives"


def test_chat_timeout_propagates_and_user_turn_stays(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(raise_exc=LlamaServerTimeout("vett_scotty_shared", 60.0))
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(LlamaServerTimeout):
        loop.process_message(sid, "user")
    history = conv_store.load_history(sid)
    assert len(history) == 1 and history[0].role == "user"


def test_assistant_save_failure_propagates(conv_store, monkeypatch):
    """Constraint 5: if the assistant-turn save fails (DB locked, FK violation,
    whatever), the error must propagate. Don't pretend success."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="will fail to save")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)

    # Make the SECOND save_turn call raise (assistant save).
    original_save = conv_store.save_turn
    call_count = {"n": 0}
    def flaky_save(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:  # the assistant turn
            raise sqlite3.OperationalError("simulated DB write failure")
        return original_save(*args, **kwargs)
    monkeypatch.setattr(conv_store, "save_turn", flaky_save)

    with pytest.raises(sqlite3.OperationalError, match="simulated DB write failure"):
        loop.process_message(sid, "hi")

    # User turn DID save (the first call). Assistant turn did NOT.
    history = conv_store.load_history(sid)
    assert len(history) == 1
    assert history[0].role == "user"


# ─── Persona / system_prompt tri-state ───────────────────────────────────────

from soveryn.agents.personas import AETHERIA_PERSONA, VETT_PERSONA


def test_default_system_prompt_loads_persona_for_agent(conv_store):
    """system_prompt=None (default) → loads the agent's canonical persona."""
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.system_prompt == AETHERIA_PERSONA


def test_default_system_prompt_loads_vett_persona(conv_store):
    loop = AgentLoop("vett", conv_store, chat_fn=_CapturingChat())
    assert loop.system_prompt == VETT_PERSONA


def test_custom_system_prompt_overrides_default(conv_store):
    custom = "You are a test stub. Reply with 'OK'."
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat(),
                     system_prompt=custom)
    assert loop.system_prompt == custom


def test_empty_system_prompt_means_no_system_message(conv_store):
    """system_prompt='' → no system message sent at all (tri-state)."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake, system_prompt="")
    loop.process_message(sid, "hello")
    request = fake.calls[0]["request"]
    # First (and only, for one turn) message should be the user — NO system.
    assert request.messages[0].role == "user"
    assert all(m.role != "system" for m in request.messages)


def test_default_persona_prepends_system_message_first(conv_store):
    """Default persona → system message is the FIRST message sent to chat_fn."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "hello")
    request = fake.calls[0]["request"]
    assert request.messages[0].role == "system"
    assert request.messages[0].content == AETHERIA_PERSONA
    assert request.messages[1].role == "user"
    assert request.messages[1].content == "hello"


def test_custom_system_prompt_prepends_when_non_empty(conv_store):
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake,
                     system_prompt="test system prompt")
    loop.process_message(sid, "hello")
    request = fake.calls[0]["request"]
    assert request.messages[0].role == "system"
    assert request.messages[0].content == "test system prompt"
    assert request.messages[1].role == "user"


def test_system_message_not_saved_to_conversations_table(conv_store):
    """The system message reconstructs every turn from self.system_prompt;
    it does NOT appear in load_history()."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="reply")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "hi")
    history = conv_store.load_history(sid)
    # Only user + assistant — never system
    assert [t.role for t in history] == ["user", "assistant"]
    assert all(t.role != "system" for t in history)


def test_multi_turn_prepends_one_system_message_per_request(conv_store):
    """Each process_message call rebuilds the messages tuple with ONE
    system at position 0, regardless of turn number. The persisted history
    grows; the system prefix does not."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "turn 1")
    fake.content = "reply 2"
    loop.process_message(sid, "turn 2")

    # First call: system + user
    first_msgs = fake.calls[0]["request"].messages
    assert [m.role for m in first_msgs] == ["system", "user"]

    # Second call: system + user + assistant + user (history accumulated)
    second_msgs = fake.calls[1]["request"].messages
    assert [m.role for m in second_msgs] == ["system", "user", "assistant", "user"]
    # Exactly one system message — never duplicated.
    assert sum(1 for m in second_msgs if m.role == "system") == 1


def test_persona_immutable_after_construction(conv_store):
    """No setter discipline — but verify the attribute is just a string."""
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    # Can technically reassign self.system_prompt (Python doesn't prevent it),
    # but the contract is: don't. Verify the construction-time value sticks
    # absent explicit mutation.
    initial = loop.system_prompt
    fake = _CapturingChat()
    loop.chat_fn = fake  # ok to swap chat for testing
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = fake.calls[0]["request"]
    assert request.messages[0].content == initial


def test_retired_agent_persona_lookup_fails_at_construction(conv_store):
    """RoutingError fires first (already tested), but if someone bypassed
    routing somehow, get_persona would also reject. Test that path by
    constructing with an existing-but-misrouted scenario: the default
    construction already rejects retired names via routing, so this is
    really a defense-in-depth assertion that personas mirror the registry."""
    from soveryn.agents.personas import PersonaError, get_persona
    for retired in ["scout", "vision", "tinker", "forge"]:
        with pytest.raises(PersonaError):
            get_persona(retired)


# ─── Memory recall (opt-in, off by default) ──────────────────────────────────

from soveryn.memory.lattice import LatticeStore, Node


def _make_lattice_store(tmp_path):
    return LatticeStore(tmp_path / "lattice.db")


def _fake_embed_returning(vector):
    """Embed_fn fake. Returns the given vector regardless of input."""
    def _f(text):
        return tuple(vector)
    return _f


def test_recall_off_by_default_no_embed_no_lattice_call(conv_store, tmp_path):
    """recall_k=0 → embed_fn never called, no lattice access."""
    sid = conv_store.new_session("aetheria")
    fake_chat = _CapturingChat()
    embed_called = {"n": 0}
    def fake_embed(text):
        embed_called["n"] += 1
        return (1.0,)
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        # recall_k defaults to 0 — no lattice_store needed
        embed_fn=fake_embed,
    )
    loop.process_message(sid, "hi")
    assert embed_called["n"] == 0


def test_recall_enabled_requires_lattice_store(conv_store):
    """recall_k > 0 with lattice_store=None → constructor raises."""
    with pytest.raises(ValueError, match="recall_k > 0 requires lattice_store"):
        AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat(), recall_k=3)


def test_recall_k_negative_raises(conv_store, tmp_path):
    with pytest.raises(ValueError, match="recall_k must be >= 0"):
        AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat(), recall_k=-1)


@pytest.mark.parametrize("bad", [0.0, -0.1, 1.01, 2.0])
def test_recall_threshold_out_of_range_raises(conv_store, tmp_path, bad):
    """Threshold must be in (0.0, 1.0] when recall is enabled."""
    store = _make_lattice_store(tmp_path)
    with pytest.raises(ValueError, match="recall_threshold"):
        AgentLoop(
            "aetheria", conv_store, chat_fn=_CapturingChat(),
            lattice_store=store, recall_k=3, recall_threshold=bad,
        )


def test_recall_threshold_validation_skipped_when_disabled(conv_store, tmp_path):
    """recall_k=0 → threshold value is irrelevant, no validation."""
    # Even passing a bad threshold is fine when recall is off.
    AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat(),
              recall_k=0, recall_threshold=-1.0)


def test_recall_enabled_calls_embed_and_lattice(conv_store, tmp_path):
    """Happy path: recall on → embed user message → query lattice → format → prepend."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    # Seed the lattice with one node whose embedding matches our query.
    nid = store.write_node(
        "aetheria", "Jon prefers Signal over Telegram",
        intensity=0.8, embedding=(1.0, 0.0, 0.0),
    )
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=3, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0, 0.0)),
    )
    loop.process_message(sid, "remind me of my notification preference")

    # The chat_fn was called with: system=persona, system=recall, user
    msgs = fake_chat.calls[0]["request"].messages
    assert msgs[0].role == "system"  # persona
    assert "Aetheria" in msgs[0].content
    assert msgs[1].role == "system"  # recall
    assert "Recalled from memory" in msgs[1].content
    assert "Jon prefers Signal" in msgs[1].content
    assert msgs[2].role == "user"
    assert msgs[2].content == "remind me of my notification preference"


def test_recall_zero_matches_omits_recall_system_message(conv_store, tmp_path):
    """If no nodes meet threshold → no recall system message at all."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    # Seed a node with orthogonal embedding, threshold high → no match.
    store.write_node(
        "aetheria", "irrelevant", intensity=0.5,
        embedding=(0.0, 1.0, 0.0),
    )
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=3, recall_threshold=0.99,
        embed_fn=_fake_embed_returning((1.0, 0.0, 0.0)),
    )
    loop.process_message(sid, "hi")
    msgs = fake_chat.calls[0]["request"].messages
    # Persona + user only — no second system
    assert [m.role for m in msgs] == ["system", "user"]


def test_recall_empty_lattice_omits_recall_system_message(conv_store, tmp_path):
    """Empty lattice → no nodes → no recall message."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=5, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0, 0.0)),
    )
    loop.process_message(sid, "hi")
    msgs = fake_chat.calls[0]["request"].messages
    assert [m.role for m in msgs] == ["system", "user"]


def test_recall_embed_failure_propagates(conv_store, tmp_path):
    """Constraint 7: embed_fn raises → AgentLoop propagates loudly."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)

    def broken_embed(text):
        raise RuntimeError("embeddings server down")

    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=3, recall_threshold=0.5,
        embed_fn=broken_embed,
    )
    with pytest.raises(RuntimeError, match="embeddings server down"):
        loop.process_message(sid, "hi")
    # User turn DID save (it precedes recall in process_message order).
    assert len(conv_store.load_history(sid)) == 1
    # chat_fn never called
    assert fake_chat.calls == []


def test_recall_lattice_failure_propagates(conv_store, tmp_path, monkeypatch):
    """Constraint 7: lattice query raises → propagates."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    def broken_query(*args, **kwargs):
        raise RuntimeError("lattice DB locked")
    monkeypatch.setattr(store, "find_nodes_by_embedding", broken_query)
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=3, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0, 0.0)),
    )
    with pytest.raises(RuntimeError, match="lattice DB locked"):
        loop.process_message(sid, "hi")
    assert fake_chat.calls == []


def test_recall_does_not_write_to_lattice(conv_store, tmp_path):
    """Constraint 8: this commit is READ-ONLY. AgentLoop must not write nodes."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    fake_chat = _CapturingChat()
    write_calls = {"n": 0}
    original_write = store.write_node
    def counted_write(*args, **kwargs):
        write_calls["n"] += 1
        return original_write(*args, **kwargs)
    store.write_node = counted_write
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=3, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0, 0.0)),
    )
    loop.process_message(sid, "hi")
    assert write_calls["n"] == 0, "AgentLoop wrote to Lattice — read-only this commit"


def test_recall_placement_is_after_persona(conv_store, tmp_path):
    """Constraint 9: persona is index 0, recall is index 1, history follows."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    store.write_node("aetheria", "matched node", intensity=0.5,
                     embedding=(1.0, 0.0))
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=store, recall_k=2, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0)),
    )
    loop.process_message(sid, "hi")
    msgs = fake_chat.calls[0]["request"].messages
    assert msgs[0].role == "system" and "Aetheria" in msgs[0].content  # persona
    assert msgs[1].role == "system" and "Recalled from memory" in msgs[1].content
    assert msgs[2].role == "user"


def test_recall_with_empty_persona_still_works(conv_store, tmp_path):
    """system_prompt='' + recall enabled → just the recall system, then user."""
    sid = conv_store.new_session("aetheria")
    store = _make_lattice_store(tmp_path)
    store.write_node("aetheria", "matched node", intensity=0.5,
                     embedding=(1.0, 0.0))
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        system_prompt="",
        lattice_store=store, recall_k=2, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0)),
    )
    loop.process_message(sid, "hi")
    msgs = fake_chat.calls[0]["request"].messages
    assert [m.role for m in msgs] == ["system", "user"]
    assert "Recalled from memory" in msgs[0].content
