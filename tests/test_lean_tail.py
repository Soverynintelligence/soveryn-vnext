"""32K lean-tail: spill fat tools, reap whole turns, cap old assistant bodies."""
from __future__ import annotations

from soveryn.agents.lean_tail import (
    LEAN_ASSISTANT_CHARS,
    SPILL_TRIGGER_CHARS,
    group_turns,
    maybe_spill_tool_content,
    reap_history,
)
from soveryn.agents.loop import (
    AgentLoop,
    ChatResponse,
    _apply_history_budget,
    _estimate_message_tokens,
)
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.inference.llama_server_client import ChatMessage
from soveryn.platform.tools.registry import ToolRegistry, ToolSpec


def _msg(role: str, text: str) -> ChatMessage:
    return ChatMessage(role=role, content=text)


def test_group_turns_pairs_user_assistant():
    history = (
        _msg("user", "a"),
        _msg("assistant", "b"),
        _msg("user", "c"),
        _msg("assistant", "d"),
    )
    turns = group_turns(history)
    assert len(turns) == 2
    assert [m.role for m in turns[0]] == ["user", "assistant"]
    assert [m.role for m in turns[1]] == ["user", "assistant"]


def test_spill_small_body_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    body = '{"ok": true}'
    assert maybe_spill_tool_content(
        body, tool_name="read_file", call_id="c1", session_id="s1"
    ) == body
    assert not (tmp_path / "tool_spill").exists()


def test_spill_fat_body_writes_file_and_stub(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    body = "HEAD" + ("x" * (SPILL_TRIGGER_CHARS + 1000)) + "TAIL"
    stub = maybe_spill_tool_content(
        body, tool_name="read_file", call_id="c1", session_id="sess-9"
    )
    assert stub != body
    assert "spilled" in stub
    assert "read_file" in stub
    assert stub.startswith("HEAD")
    assert stub.endswith("TAIL")
    spilled = list((tmp_path / "tool_spill" / "sess-9").glob("*.txt"))
    assert len(spilled) == 1
    assert spilled[0].read_text(encoding="utf-8") == body


def test_reaper_drops_whole_turn_not_one_message():
    history = (
        _msg("user", "old q"),
        _msg("assistant", "old a"),
        _msg("user", "new q"),
        _msg("assistant", "new a"),
    )
    # Tiny budget: must drop the first turn as a pair.
    trimmed, marker, elided = reap_history(
        (), history, budget=20, estimate_fn=_estimate_message_tokens
    )
    assert elided == 1
    assert marker is not None
    assert [m.content for m in trimmed] == ["new q", "new a"]


def test_lean_tail_caps_old_assistant_keeps_user_words():
    old_user = _msg("user", "keep my words")
    old_asst = _msg("assistant", "Z" * (LEAN_ASSISTANT_CHARS + 2000))
    new_user = _msg("user", "now")
    history = (old_user, old_asst, new_user)
    # Uncapped old assistant (~1500 tok) would force a turn drop. After cap
    # (~1000 tok) the whole history fits — user words stay.
    trimmed, marker, elided = _apply_history_budget((), history, budget=1_200)
    assert elided == 0
    assert trimmed[-1].content == "now"
    assert any(m.content == "keep my words" for m in trimmed)
    fat = [m for m in trimmed if m.role == "assistant"]
    assert fat
    assert len(fat[0].content) <= LEAN_ASSISTANT_CHARS + 80
    assert "capped for 32k" in fat[0].content
    assert marker is not None
    assert "capped" in marker.content


class _ToolThenAnswer:
    def __init__(self):
        self.calls = []
        self.n = 0

    def __call__(self, request, server, timeout=60.0):
        self.calls.append(request)
        self.n += 1
        if self.n == 1:
            return ChatResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=(
                    {
                        "id": "c-fat",
                        "type": "function",
                        "function": {"name": "dummy", "arguments": "{}"},
                    },
                ),
                usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
                raw={},
            )
        return ChatResponse(
            content="ok",
            finish_reason="stop",
            tool_calls=None,
            usage={"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11},
            raw={},
        )


def test_loop_spills_fat_tool_result_into_next_call(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path))
    store = ConversationStore(tmp_path / "conv.db")
    fat = "Y" * (SPILL_TRIGGER_CHARS + 500)
    registry = ToolRegistry(active_agents=("kernel",), audit_hook=None)
    registry.register(
        ToolSpec(
            name="dummy",
            owner="kernel",
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda args: {"blob": fat},
            description="dummy",
        )
    )
    chat = _ToolThenAnswer()
    loop = AgentLoop(
        "kernel",
        store,
        chat_fn=chat,
        tool_registry=registry,
        max_tool_rounds=4,
        history_token_budget=6_000,
        context_window=32_768,
        soul_text="",
    )
    sid = store.new_session("kernel")
    loop.process_message(sid, "read the blob")
    assert len(chat.calls) >= 2
    tool_msgs = [m for m in chat.calls[1].messages if m.role == "tool"]
    assert tool_msgs
    assert "spilled" in tool_msgs[0].content
    assert fat not in tool_msgs[0].content
    files = list((tmp_path / "tool_spill").rglob("*.txt"))
    assert files
    assert fat in files[0].read_text(encoding="utf-8")
