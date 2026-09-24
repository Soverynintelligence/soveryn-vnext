"""The delegation executor binds its server explicitly, not by persona route.

2026-09-24: Scotty was folded (Sep 22), his route left AGENT_TO_SERVER, and
every dispatch died with "No route for agent 'scotty'" — the engine, sandbox,
worktrees and acceptance gate were all fine; only the model binding was dead.
server_override is the seam. A folded worker lane needs a server, not a persona.
"""
from __future__ import annotations

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.delegation.scotty_runner import _delegation_server


def test_folded_agent_with_explicit_server_constructs(tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    loop = AgentLoop(
        "scotty",  # not in AGENT_TO_SERVER — must not raise with an override
        conv,
        server_override=_delegation_server(),
        soul_text="",
        system_prompt="",  # worker prompt is the runner's concern, not routing's
    )
    assert loop.server is not None
    assert loop.server.name == "vett_scotty_shared"


def test_folded_agent_without_override_still_raises(tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    with pytest.raises(Exception) as exc:
        AgentLoop("scotty", conv, soul_text="")
    assert "No route" in str(exc.value)


def test_delegation_server_resolves_and_declares_role():
    server = _delegation_server()
    assert server.host and server.port
    assert server.model_alias, "executor must know its alias"
