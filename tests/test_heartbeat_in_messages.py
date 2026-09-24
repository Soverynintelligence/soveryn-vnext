"""Aetheria's heartbeat notes must show in the Messages DM, not only in
the hidden [heartbeat] session the phone never opens."""

from soveryn.app.heartbeat_in_messages import (
    HEARTBEAT_SESSION_TITLE,
    fold_heartbeat_notes,
)
from soveryn.memory.conversation_store import ConversationStore


def _dicts(turns):
    return [
        {
            "role": t.role,
            "content": t.content,
            "timestamp": t.timestamp,
            "source": t.source,
        }
        for t in turns
    ]


def test_fold_includes_heartbeat_assistant_note_in_aetheria_dm(tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    dm = conv.new_session("aetheria", title="[m] Aetheria — Sat Aug 22")
    hb = conv.new_session("aetheria", title=HEARTBEAT_SESSION_TITLE)
    conv.save_turn(dm, "aetheria", "user", "morning")
    conv.save_turn(dm, "aetheria", "assistant", "I'm here.")
    conv.save_turn(hb, "aetheria", "user", "[HEARTBEAT]\npulse")
    conv.save_turn(
        hb,
        "aetheria",
        "assistant",
        "I'm going to let it sit in the dark and focus on something else.",
        source="heartbeat",
    )
    session = conv.get_session(dm)
    out = fold_heartbeat_notes(conv, session, _dicts(conv.load_history(dm)))
    contents = [t["content"] for t in out]
    assert "I'm here." in contents
    assert any("sit in the dark" in c for c in contents)
    note = next(t for t in out if "sit in the dark" in t["content"])
    assert note["role"] == "assistant"
    assert note["source"] == "heartbeat"


def test_fold_skips_other_agents(tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    dm = conv.new_session("kernel", title="k")
    conv.save_turn(dm, "kernel", "user", "hi")
    session = conv.get_session(dm)
    out = fold_heartbeat_notes(conv, session, _dicts(conv.load_history(dm)))
    assert [t["content"] for t in out] == ["hi"]


def test_fold_does_not_duplicate_when_viewing_heartbeat_session(tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    hb = conv.new_session("aetheria", title=HEARTBEAT_SESSION_TITLE)
    conv.save_turn(hb, "aetheria", "assistant", "note once")
    session = conv.get_session(hb)
    out = fold_heartbeat_notes(conv, session, _dicts(conv.load_history(hb)))
    assert [t["content"] for t in out] == ["note once"]
