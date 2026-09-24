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
from soveryn.platform.lattice.provenance import ProvenanceClass


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

def test_construction_routes_aetheria_to_aetheria_primary(conv_store):
    """Phase 7 router cutover: assert agent → logical preset identity, not port.
    All ModelServers now share :8090; the routing distinction lives in name +
    model_alias, which is what the router dispatches on via the "model" field."""
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.server.name == "aetheria_primary"
    assert loop.server.model_alias == "aetheria"
    assert loop.agent_name == "aetheria"


def test_default_chat_timeout_is_120_seconds(conv_store):
    """Cold-start KV + 35B + thinking mode can exceed 60s on turn 1.
    Default bumped from 60 → 120 per validation finding 2026-05-24 (UI-11)."""
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.chat_timeout_seconds == 120.0


def test_construction_rejects_parked_vett(conv_store):
    """Fleet freeze: Vett is not a chat AgentLoop (folded into Eve)."""
    with pytest.raises(RoutingError, match="vett"):
        AgentLoop("vett", conv_store, chat_fn=_CapturingChat())


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
    """A Kernel session can't be used by an Aetheria loop."""
    kernel_session = conv_store.new_session("kernel")
    fake = _CapturingChat()
    aetheria_loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    with pytest.raises(AgentLoopError, match="belongs to agent 'kernel'"):
        aetheria_loop.process_message(kernel_session, "hi")
    assert fake.calls == []
    # No user turn snuck into the wrong session
    assert conv_store.load_history(kernel_session) == ()


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
    # Prior history (u1, a1) is clean — the temporal splice only touches the
    # CURRENT user turn. So u1+a1 are exact, and u2 ends with the user text.
    assert contents[:2] == ["turn-1", "reply-1"]
    assert contents[2].endswith("turn-2")


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

from soveryn.agents.personas import AETHERIA_PERSONA, get_persona


def test_default_system_prompt_loads_persona_for_agent(conv_store):
    """system_prompt=None (default) → loads the agent's canonical persona."""
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.system_prompt == AETHERIA_PERSONA


def test_default_system_prompt_loads_kernel_persona(conv_store):
    loop = AgentLoop("kernel", conv_store, chat_fn=_CapturingChat())
    assert loop.system_prompt == get_persona("kernel")


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
    # Temporal splice prefixes the current user turn; user text is the suffix.
    assert request.messages[1].content.endswith("hello")


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


def test_thinking_budget_tokens_default_none(conv_store):
    """Default AgentLoop sends ChatRequest with thinking_budget_tokens=None
    (server-side --reasoning-budget applies)."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "hello")
    assert fake.calls[0]["request"].thinking_budget_tokens is None


def test_thinking_budget_tokens_flows_to_chat_request(conv_store):
    """When AgentLoop is constructed with thinking_budget_tokens, that value
    reaches ChatRequest verbatim — per-agent reasoning cap (Aetheria-only)."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake,
                     thinking_budget_tokens=384)
    loop.process_message(sid, "hello")
    assert fake.calls[0]["request"].thinking_budget_tokens == 384


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


def test_agent_loop_accepts_tool_registry_and_exposes_schemas(conv_store):
    from soveryn.platform.tools.registry import ToolRegistry, ToolSpec

    registry = ToolRegistry(active_agents=("aetheria",), audit_hook=None)
    registry.register(ToolSpec(
        name="dummy",
        owner="aetheria",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=lambda args: {"ok": True},
        description="dummy",
    ))

    loop = AgentLoop(
        "aetheria",
        conv_store,
        chat_fn=_CapturingChat(),
        tool_registry=registry,
        max_tool_rounds=4,
    )
    schemas = loop._tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "dummy"
    assert "parameters" in schemas[0]["function"]


def test_agent_loop_default_no_tool_registry(conv_store):
    loop = AgentLoop("aetheria", conv_store, chat_fn=_CapturingChat())
    assert loop.tool_registry is None
    assert loop._tool_schemas() == ()


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
    assert "Uncertain context:" in msgs[1].content
    assert "Jon prefers Signal" not in msgs[1].content
    assert msgs[2].role == "user"
    # Temporal splice prefixes the current user turn; user text is the suffix.
    assert msgs[2].content.endswith("remind me of my notification preference")



def test_recall_cutover_includes_identity_spine_and_does_not_leak_channel_b_content(conv_store, tmp_path):
    sid = conv_store.new_session("aetheria")
    recall_store = _make_lattice_store(tmp_path)
    raw_claim = "raw legacy content must not be quoted"
    recall_store.write_node(
        "aetheria", raw_claim,
        intensity=0.8, embedding=(1.0, 0.0),
    )
    identity_store = LatticeStore(tmp_path / "identity.db")
    identity_store.write_node(
        "aetheria",
        "presence over performance is part of my identity",
        node_type="identity",
        intensity=1.0,
        provenance={
            "cls": ProvenanceClass.CONSOLIDATED.value,
            "source": "legacy_identity_review",
            "confidence": 1.0,
            "temporal_context": "fixture",
            "generator": "test",
            "chain": ["raw-attic-id"],
            "derived_from": [],
            "trigger": "migration_identity_review",
            "legacy_id": "legacy-id",
            "attic_id": "raw-attic-id",
        },
    )
    fake_chat = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store, chat_fn=fake_chat,
        lattice_store=recall_store, identity_spine_store=identity_store,
        recall_k=3, recall_threshold=0.5,
        embed_fn=_fake_embed_returning((1.0, 0.0)),
    )

    loop.process_message(sid, "what do you remember about yourself?")

    msgs = fake_chat.calls[0]["request"].messages
    # loop.py now builds identity spine and scored recall as SEPARATE system
    # messages: msg[1] = identity context ("Stateable recall:" + identity
    # nodes); msg[2] = scored recall ("Uncertain context:" + class-only render).
    # Verify the intended contract across all system messages rather than a
    # single index.
    system_contents = "\n".join(
        m.content for m in msgs if m.role == "system"
    )
    assert "Stateable recall:" in system_contents
    assert "From older reviewed notes, I carry presence over performance is part of my identity" in system_contents
    assert "Uncertain context:" in system_contents
    # Channel-B raw verbatim text must NOT appear anywhere
    assert raw_claim not in system_contents

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
    assert msgs[1].role == "system" and "Uncertain context:" in msgs[1].content
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
    assert "Uncertain context:" in msgs[0].content


# ─── Souls Step 3: soul_text wiring ──────────────────────────────────────────

def test_default_soul_text_skips_soul_message(conv_store):
    """Default behavior: soul_text='' means no soul system message added."""
    capturing = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=capturing)
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    # Inspect the messages sent to chat_fn — should have ONE system msg (persona), then user
    request = capturing.calls[0]["request"]
    system_count = sum(1 for m in request.messages if m.role == "system")
    assert system_count == 1, f"expected 1 system message, got {system_count}"


def test_soul_text_explicit_string_added_as_second_system_message(conv_store):
    """When soul_text is a non-empty string, it goes in as a SECOND system message
    immediately after the persona."""
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text="I am the soul of Aetheria.",
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 2, f"expected 2 system messages, got {len(system_msgs)}"
    # Persona first
    assert "Aetheria" in system_msgs[0].content or "coordinating" in system_msgs[0].content.lower()
    # Soul second, exact content
    assert system_msgs[1].content == "I am the soul of Aetheria."


def test_soul_text_none_loads_from_souls_dir(conv_store, tmp_path):
    """soul_text=None triggers get_soul() against the souls_dir param."""
    souls = tmp_path / "souls"
    souls.mkdir()
    (souls / "aetheria.md").write_text("loaded from disk\n", encoding="utf-8")
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text=None,
        souls_dir=souls,
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 2
    assert "loaded from disk" in system_msgs[1].content


def test_soul_text_none_raises_when_file_missing(conv_store, tmp_path):
    """soul_text=None with missing souls/<agent>.md raises at construction."""
    from soveryn.agents.souls import SoulMissingError
    empty_souls = tmp_path / "souls"
    empty_souls.mkdir()
    with pytest.raises(SoulMissingError):
        AgentLoop(
            "aetheria", conv_store,
            chat_fn=_CapturingChat(),
            soul_text=None,
            souls_dir=empty_souls,
        )


def test_soul_not_concatenated_into_persona(conv_store):
    """The persona text and the soul text must be DISTINCT messages, not joined."""
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text="UNIQUE_SOUL_TOKEN",
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    # The persona message must NOT contain the soul token
    assert "UNIQUE_SOUL_TOKEN" not in system_msgs[0].content
    # The soul message must contain ONLY the soul token (not the persona)
    assert system_msgs[1].content == "UNIQUE_SOUL_TOKEN"


def test_soul_kept_separate_at_agent_loop_for_kernel(conv_store):
    """AgentLoop produces semantic layers (persona / pinned / soul / recall)
    as SEPARATE ChatMessages regardless of the server's multi-system support.

    The transport adapter `prepare_wire_messages` (in llama_server_client.py)
    folds them into one system message at the HTTP boundary if the target
    server's chat template can't honor multi-system messages. The fold is a
    wire-format accommodation; the AgentLoop-level structure stays separate.

    See project_soveryn_three_tracks_workaround_capability_agency.
    """
    capturing = _CapturingChat()
    loop = AgentLoop(
        "kernel", conv_store,
        chat_fn=capturing,
        soul_text="KERNEL_SOUL_TOKEN",
    )
    sid = conv_store.new_session("kernel")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 2, (
        f"AgentLoop should keep persona + soul as separate ChatMessages even "
        f"when the server's template can't handle multi-system. "
        f"Wire folding happens at the transport adapter. Got {len(system_msgs)}."
    )
    # Persona first, then soul as its own message
    assert "KERNEL_SOUL_TOKEN" not in system_msgs[0].content
    assert system_msgs[1].content == "KERNEL_SOUL_TOKEN"


def test_soul_kept_separate_for_aetheria_whose_server_supports_multi_system(conv_store):
    """Aetheria's server supports multiple system messages — soul stays as its
    own system message after the persona (unchanged behavior from Step 3)."""
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text="AETHERIA_SOUL_TOKEN",
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 2, "aetheria should still get two system messages"
    assert "AETHERIA_SOUL_TOKEN" not in system_msgs[0].content
    assert system_msgs[1].content == "AETHERIA_SOUL_TOKEN"


# ─── Pinned memory: Aetheria-only third identity layer ───────────────────────

def test_default_pinned_text_skips_pinned_message(conv_store):
    """Default pinned_text='' means no pinned system message added.
    Vett/Scotty rely on this — they get nothing pinned-related."""
    capturing = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=capturing)
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    # With no soul_text and no pinned_text: just persona = 1 message
    assert len(system_msgs) == 1


def test_pinned_text_added_between_persona_and_soul_for_aetheria(conv_store):
    """Aetheria (multi-system server): 3 separate system messages in order
    persona, pinned, soul."""
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text="SOUL_TOKEN",
        pinned_text="PINNED_TOKEN",
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 3, (
        f"expected 3 system messages, got {len(system_msgs)}"
    )
    # Order: persona first, pinned second, soul third
    assert "PINNED_TOKEN" not in system_msgs[0].content  # persona
    assert "SOUL_TOKEN" not in system_msgs[0].content    # persona
    assert system_msgs[1].content == "PINNED_TOKEN"      # pinned
    assert system_msgs[2].content == "SOUL_TOKEN"        # soul


def test_pinned_and_soul_kept_separate_at_agent_loop_for_kernel(conv_store):
    """AgentLoop produces persona / pinned / soul as THREE separate
    ChatMessages even when the server's template can't honor multi-system.
    Wire folding happens at the transport adapter. (In production, Kernel gets
    pinned_text='' anyway; this verifies the safety net if pinned ever WERE
    passed.)
    """
    capturing = _CapturingChat()
    loop = AgentLoop(
        "kernel", conv_store,
        chat_fn=capturing,
        soul_text="KERNEL_SOUL",
        pinned_text="KERNEL_PINNED",
    )
    sid = conv_store.new_session("kernel")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 3, (
        f"expected 3 separate system messages at AgentLoop level (persona / "
        f"pinned / soul); transport adapter handles wire folding. "
        f"Got {len(system_msgs)}."
    )
    # Order: persona first, pinned second, soul third
    assert "KERNEL_PINNED" not in system_msgs[0].content  # persona
    assert "KERNEL_SOUL" not in system_msgs[0].content    # persona
    assert system_msgs[1].content == "KERNEL_PINNED"
    assert system_msgs[2].content == "KERNEL_SOUL"


def test_pinned_alone_without_soul_for_aetheria(conv_store):
    """pinned_text set but soul_text='' — just persona + pinned, no soul message."""
    capturing = _CapturingChat()
    loop = AgentLoop(
        "aetheria", conv_store,
        chat_fn=capturing,
        soul_text="",
        pinned_text="PINNED_ONLY",
    )
    sid = conv_store.new_session("aetheria")
    loop.process_message(sid, "hi")
    request = capturing.calls[0]["request"]
    system_msgs = [m for m in request.messages if m.role == "system"]
    assert len(system_msgs) == 2
    assert system_msgs[1].content == "PINNED_ONLY"


# ─── SI-T2: attachments kwarg (vision) ───────────────────────────────────────
# DB stores the user message as plain text (no schema migration). At wire build
# time, when attachments are passed, the current user turn's content becomes an
# OpenAI vision-format list. Aetheria-only — the vision guard fires BEFORE
# save_turn so guard rejections leave no state behind.

def test_process_message_with_attachments_splices_image_url_into_current_user_message(conv_store):
    """Live user-turn content is rewritten to OpenAI vision-format list when
    attachments are passed. The DB row still stores the text-only version."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="ok")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    img_url = "data:image/jpeg;base64,AAAA"
    loop.process_message(sid, "what's this?", attachments=(img_url,))

    # DB stores text-only
    history = conv_store.load_history(sid)
    assert history[0].role == "user"
    assert history[0].content == "what's this?"

    # Wire-level current user message is list-content with text + image parts.
    # The text part also carries the temporal-context prefix from the splice
    # ordering (temporal first, then vision wraps it), so we match by suffix.
    sent_user = fake.calls[0]["request"].messages[-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, list)
    text_parts = [p for p in sent_user.content if p.get("type") == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"].endswith("what's this?")
    assert {"type": "image_url", "image_url": {"url": img_url}} in sent_user.content


def test_process_message_without_attachments_unchanged(conv_store):
    """Regression: attachments=None preserves prior behavior (str content)."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "plain text")
    history = conv_store.load_history(sid)
    assert history[0].content == "plain text"
    # request messages stay str-typed; the temporal splice prepends a prefix
    # to the current user message, but the user text still ends with it.
    sent_user = fake.calls[0]["request"].messages[-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, str)
    assert sent_user.content.endswith("plain text")


def test_process_message_attachments_on_non_vision_agent_raises_before_save(conv_store):
    """Vision guard fires BEFORE save_turn so guard rejections don't pollute
    history with a phantom user turn. cognition is not in VISION_CAPABLE_AGENTS."""
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.agent_name = "cognition"
    sid = conv_store.new_session("cognition")
    with pytest.raises(AgentLoopError, match="attachments only supported"):
        loop.process_message(
            sid, "hi", attachments=("data:image/jpeg;base64,AAAA",),
        )
    # No user turn saved, no chat dispatched
    assert conv_store.load_history(sid) == ()
    assert fake.calls == []


def test_process_message_attachments_on_kernel_splices(conv_store):
    """GLM-5.3-Flash is natively multimodal — Kernel splices image_url."""
    fake = _CapturingChat()
    loop = AgentLoop("kernel", conv_store, chat_fn=fake)
    sid = conv_store.new_session("kernel")
    img = "data:image/jpeg;base64,AAAA"
    loop.process_message(sid, "what's this?", attachments=(img,))
    sent_user = fake.calls[0]["request"].messages[-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, list)
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == img
               for p in sent_user.content)


def test_process_message_attachments_on_vision_capable_agent_splices(conv_store):
    """Aetheria is vision-capable — the guard must NOT fire, and the
    wire-level current user message becomes a vision list."""
    fake = _CapturingChat()
    loop_a = AgentLoop("aetheria", conv_store, chat_fn=fake)
    sid = conv_store.new_session("aetheria")
    img = "data:image/jpeg;base64,AAAA"
    loop_a.process_message(sid, "what's this?", attachments=(img,))
    sent_user = fake.calls[0]["request"].messages[-1]
    assert sent_user.role == "user"
    assert isinstance(sent_user.content, list)
    assert any(p.get("type") == "image_url" and p["image_url"]["url"] == img
               for p in sent_user.content)


def test_process_message_multiple_attachments_all_spliced(conv_store):
    """All image URLs become image_url parts in order."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    urls = (
        "data:image/jpeg;base64,A",
        "data:image/png;base64,B",
        "data:image/webp;base64,C",
    )
    loop.process_message(sid, "compare these", attachments=urls)
    sent = fake.calls[0]["request"].messages[-1]
    assert isinstance(sent.content, list)
    img_parts = [p for p in sent.content if p.get("type") == "image_url"]
    assert len(img_parts) == 3
    assert [p["image_url"]["url"] for p in img_parts] == list(urls)
    # Text part still present — also carries the temporal-context prefix
    text_parts = [p for p in sent.content if p.get("type") == "text"]
    assert len(text_parts) == 1
    assert text_parts[0]["text"].endswith("compare these")


def test_process_message_empty_attachments_tuple_treated_as_none(conv_store):
    """attachments=() (falsy) → no splice, no guard fire — same as None."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat()
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(sid, "plain", attachments=())
    sent_user = fake.calls[0]["request"].messages[-1]
    assert isinstance(sent_user.content, str)
    # Empty attachments still triggers the temporal splice (vision splice is
    # the only thing skipped); the user text is the suffix.
    assert sent_user.content.endswith("plain")


def test_process_message_attachments_dont_pollute_next_turn_history(conv_store):
    """Text-only DB save means next-turn history doesn't carry image parts.
    The vision splice is in-flight only — intentional per SI-T2 spec."""
    sid = conv_store.new_session("aetheria")
    fake = _CapturingChat(content="r1")
    loop = AgentLoop("aetheria", conv_store, chat_fn=fake)
    loop.process_message(
        sid, "look", attachments=("data:image/jpeg;base64,AAAA",),
    )
    # Second turn, no attachments
    fake.content = "r2"
    loop.process_message(sid, "follow up")
    # History on second call should be: system + u1(str) + a1 + u2(str)
    second_msgs = fake.calls[1]["request"].messages
    # The prior user turn (now in history) must be str-content, not list
    user_turns_in_history = [
        m for m in second_msgs[:-1] if m.role == "user"
    ]
    assert len(user_turns_in_history) == 1
    assert isinstance(user_turns_in_history[0].content, str)
    assert user_turns_in_history[0].content == "look"
