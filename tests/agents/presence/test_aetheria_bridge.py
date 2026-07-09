"""Tests for make_draft_fn — bridges presence drafting to Aetheria's real AgentLoop.

Everything is faked: no real model call, no real loop/session store. FakeLoop
mirrors the AgentLoop.process_message(session_id, user_message) -> ChatResponse
signature (soveryn/agents/loop.py:753); FakeConv mirrors
ConversationStore.new_session(agent, title=None) -> session_id
(soveryn/memory/conversation_store.py:172).
"""

from soveryn.agents.presence.aetheria_bridge import make_draft_fn


class FakeResp:  # mirrors ChatResponse fields used
    def __init__(self, content, finish="stop"):
        self.content, self.finish_reason = content, finish


class FakeLoop:
    def __init__(self, resp):
        self.resp = resp

    def process_message(self, sid, msg):
        return self.resp


class FakeConv:
    def new_session(self, agent, title=None):
        return "sess-1"


def test_tool_round_limit_becomes_skip():
    fn = make_draft_fn(FakeLoop(FakeResp("", "tool_round_limit")), FakeConv())
    assert '"skip":true' in fn("prompt")


def test_normal_returns_content():
    fn = make_draft_fn(
        FakeLoop(FakeResp('{"post":"hi","based_on":"x","skip":false}')), FakeConv()
    )
    assert '"post":"hi"' in fn("prompt")


def test_empty_content_becomes_skip():
    fn = make_draft_fn(FakeLoop(FakeResp("   ")), FakeConv())
    assert '"skip":true' in fn("prompt")


def test_fenced_json_is_unfenced():
    fenced = '```json\n{"post":"hi","based_on":"x","skip":false}\n```'
    fn = make_draft_fn(FakeLoop(FakeResp(fenced)), FakeConv())
    out = fn("prompt")
    assert out == '{"post":"hi","based_on":"x","skip":false}'
    assert "```" not in out
