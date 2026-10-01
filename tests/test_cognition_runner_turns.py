"""Regression: conversation-store turns must map to cognition Turn with turn_id."""
from pathlib import Path
import tempfile

from soveryn.agents.cognition.runner import make_conversation_sources
from soveryn.agents.cognition.types import Turn as CogTurn
from soveryn.memory.conversation_store import ConversationStore


def test_recent_turns_fn_maps_store_turns_to_cognition_turns():
    with tempfile.TemporaryDirectory() as d:
        store = ConversationStore(Path(d) / "c.db")
        sid = store.new_session("aetheria")
        store.save_turn(sid, "aetheria", "user", "skip the hedging please")
        store.save_turn(sid, "aetheria", "assistant", "noted")
        _, turns_fn = make_conversation_sources(store, "aetheria")
        turns = turns_fn()
        assert len(turns) >= 2
        assert all(isinstance(t, CogTurn) for t in turns)
        assert all(t.turn_id and t.content for t in turns)
        assert turns[0].role == "user"
