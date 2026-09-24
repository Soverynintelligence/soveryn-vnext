"""Thread CRUD: agent binding immutable, session reuses ConversationStore."""
from __future__ import annotations
import pytest

from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.threads import (
    create_thread,
    get_thread,
    list_threads,
    set_thread_muted,
    ThreadError,
    VALID_AGENTS,
)


@pytest.fixture
def stores(tmp_path):
    return (
        MessengerStore(tmp_path / "messenger.db"),
        ConversationStore(tmp_path / "conv.db"),
    )


def test_create_thread_for_aetheria(stores):
    m, conv = stores
    thread = create_thread(m, conv, user_id="jon", agent="aetheria", title=None)
    assert thread.thread_id
    assert thread.agent == "aetheria"
    assert thread.session_id  # has a backing ConversationStore session
    # Session is actually registered in ConversationStore
    session = conv.get_session(thread.session_id)
    assert session is not None
    assert session.agent == "aetheria"


def test_create_thread_rejects_invalid_agent(stores):
    m, conv = stores
    with pytest.raises(ThreadError, match="invalid agent"):
        create_thread(m, conv, user_id="jon", agent="unknown", title=None)


def test_list_threads_returns_per_user_only(stores):
    m, conv = stores
    create_thread(m, conv, user_id="jon", agent="aetheria", title="A")
    create_thread(m, conv, user_id="jon", agent="kernel", title="B")
    create_thread(m, conv, user_id="someone-else", agent="aetheria", title="X")
    out = list_threads(m, user_id="jon")
    assert len(out) == 2
    agents = {t.agent for t in out}
    assert agents == {"aetheria", "kernel"}


def test_get_thread_returns_none_for_unknown(stores):
    m, _ = stores
    assert get_thread(m, thread_id="not-a-real-id") is None


def test_set_muted_toggles(stores):
    m, conv = stores
    thread = create_thread(m, conv, user_id="jon", agent="aetheria", title="T")
    set_thread_muted(m, thread_id=thread.thread_id, muted=True)
    out = get_thread(m, thread_id=thread.thread_id)
    assert out.muted is True
    set_thread_muted(m, thread_id=thread.thread_id, muted=False)
    out = get_thread(m, thread_id=thread.thread_id)
    assert out.muted is False


def test_valid_agents_matches_active_roster():
    # Must match the runtime ACTIVE_AGENTS list
    from soveryn.config.runtime import ACTIVE_AGENTS
    assert set(VALID_AGENTS) == set(ACTIVE_AGENTS)
