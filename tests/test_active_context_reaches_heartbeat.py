"""A [heartbeat] session must receive the live thread.

The regression this locks down is the one that mattered most on 2026-07-28.
`_build_continuity_brief` returned "" for any session whose title matched
AUTONOMOUS_SESSION_PREFIXES, so a heartbeat wake got NO cross-rail context at
all. Her 09:01 pulse that morning concluded the Cross-Rail manager was the
system's biggest bottleneck — the same call Jon had made independently — and it
reached nobody, including her own later sessions.

Heartbeat CHATTER staying out of the transcript tails is deliberate and stays
that way: 26 wakes a day at ~344 tokens cannot fit a 1500-token budget. What
changed is that STATE crosses where transcript does not.
"""
from __future__ import annotations

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.context.service import BLOCK_HEADER, ActiveContextService
from soveryn.context.store import ActiveContextStore
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.continuity.config import ContinuityConfig


@pytest.fixture
def svc(tmp_path):
    return ActiveContextService(ActiveContextStore(tmp_path / "ctx.db"))


def _loop(tmp_path, svc, *, enabled=True):
    conv = ConversationStore(tmp_path / "conv.db")
    return AgentLoop(
        "aetheria",
        conv,
        continuity_config=ContinuityConfig(enabled=enabled),
        active_context=svc,
    ), conv


class TestHeartbeatReceivesTheThread:
    def test_autonomous_session_gets_the_block(self, tmp_path, svc):
        loop, conv = _loop(tmp_path, svc)
        sid = conv.new_session("aetheria", title="[heartbeat] aetheria")
        svc.record_exchange(rail="signal", user_text="what about the liner",
                            assistant_text="ordered, arrives Thursday")

        brief = loop._build_continuity_brief(sid)

        assert BLOCK_HEADER in brief, (
            "a heartbeat session received no cross-rail context; before "
            "2026-07-28 this returned '' and her thinking never crossed"
        )
        assert "ordered, arrives Thursday" in brief

    def test_autonomous_session_still_gets_no_transcript_tails(self, tmp_path, svc):
        """Chatter stays out. Only state crosses."""
        loop, conv = _loop(tmp_path, svc)
        other = conv.new_session("aetheria", title="a normal chat")
        conv.save_turn(other, "aetheria", "user", "a very distinctive user line")
        conv.save_turn(other, "aetheria", "assistant", "a very distinctive reply")
        sid = conv.new_session("aetheria", title="[heartbeat] aetheria")
        svc.record_thought(rail="heartbeat", note="a conclusion worth carrying")

        brief = loop._build_continuity_brief(sid)

        assert "a conclusion worth carrying" in brief
        assert "a very distinctive user line" not in brief

    def test_empty_context_yields_empty_brief_for_autonomous(self, tmp_path, svc):
        loop, conv = _loop(tmp_path, svc)
        sid = conv.new_session("aetheria", title="[heartbeat] aetheria")
        assert loop._build_continuity_brief(sid) == ""


class TestNormalSessionsAlsoGetIt:
    def test_block_is_appended_for_a_regular_session(self, tmp_path, svc):
        loop, conv = _loop(tmp_path, svc)
        sid = conv.new_session("aetheria", title="morning chat")
        svc.record_thought(rail="heartbeat", note="the bottleneck is cross-rail")

        brief = loop._build_continuity_brief(sid)

        assert BLOCK_HEADER in brief
        assert "the bottleneck is cross-rail" in brief


class TestFailureIsNeverFatal:
    def test_a_broken_service_does_not_break_the_turn(self, tmp_path):
        class Exploding:
            def render(self):
                raise RuntimeError("store is gone")

        loop, conv = _loop(tmp_path, Exploding())
        sid = conv.new_session("aetheria", title="[heartbeat] aetheria")
        assert loop._build_continuity_brief(sid) == ""

    def test_unwired_loop_behaves_as_before(self, tmp_path):
        conv = ConversationStore(tmp_path / "conv.db")
        loop = AgentLoop("aetheria", conv,
                         continuity_config=ContinuityConfig(enabled=True))
        sid = conv.new_session("aetheria", title="[heartbeat] aetheria")
        assert loop._build_continuity_brief(sid) == ""


class TestEveryAgentIsWhole:
    """A peer with no coord_store still carries its own thread."""

    def test_scotty_gets_his_thread_without_a_coord_store(self, tmp_path):
        store = ActiveContextStore(tmp_path / "team.db")
        scotty_ctx = ActiveContextService(store, agent="scotty")
        conv = ConversationStore(tmp_path / "conv.db")
        loop = AgentLoop(
            "scotty", conv,
            continuity_config=ContinuityConfig(enabled=True),
            active_context=scotty_ctx,
        )
        sid = conv.new_session("scotty", title="a scotty session")
        scotty_ctx.record_thought(rail="chat", note="the acceptance contract is fixed")

        brief = loop._build_continuity_brief(sid)
        assert BLOCK_HEADER in brief
        assert "the acceptance contract is fixed" in brief

    def test_a_peer_without_the_service_still_gets_nothing(self, tmp_path):
        conv = ConversationStore(tmp_path / "conv.db")
        loop = AgentLoop("scotty", conv,
                         continuity_config=ContinuityConfig(enabled=True))
        sid = conv.new_session("scotty", title="a scotty session")
        assert loop._build_continuity_brief(sid) == ""
