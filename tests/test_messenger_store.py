"""Schema + CRUD for the messenger substrate."""
from __future__ import annotations
import pytest
from soveryn.app.messenger.store import MessengerStore


@pytest.fixture
def store(tmp_path):
    return MessengerStore(tmp_path / "messenger.db")


def test_store_creates_all_tables(store):
    expected = {
        "m_devices", "m_pairing_tokens", "m_threads",
        "m_outbound_queue", "m_outbound_delivery_per_device",
        "m_push_subscriptions", "m_message_idempotency",
    }
    actual = set(store.list_tables())
    assert expected <= actual, f"missing tables: {expected - actual}"


def test_devices_schema(store):
    cols = set(store.column_names("m_devices"))
    assert {"device_id", "secret_hash", "label", "created_at", "last_seen_at", "revoked_at"} <= cols


def test_threads_schema(store):
    cols = set(store.column_names("m_threads"))
    assert {"thread_id", "user_id", "agent", "session_id", "title",
            "created_at", "last_activity", "muted"} <= cols


def test_outbound_queue_schema(store):
    cols = set(store.column_names("m_outbound_queue"))
    assert {"intent_id", "user_id", "agent", "thread_id", "content",
            "context_hint", "urgency", "triggered_by", "created_at",
            "delivered_at", "delivery_state"} <= cols


def test_idempotency_first_call_records_and_returns_none(store):
    """First time we see client_msg_id, record it and return None — caller
    should proceed with the operation."""
    cached = store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    assert cached is None


def test_idempotency_second_call_returns_cached(store):
    """Second call with same client_msg_id returns the cached response —
    caller should NOT re-process."""
    store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    cached = store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    # First record had no response yet; cached is just an empty marker
    assert cached == {}


def test_idempotency_store_response(store):
    store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    store.idempotency_set_response(client_msg_id="abc", response={"ok": True})
    cached = store.idempotency_lookup_or_record(
        client_msg_id="abc", thread_id="t1", device_id="d1",
    )
    assert cached == {"ok": True}


def test_outbound_queue_has_why_and_stance_columns(tmp_path):
    from soveryn.app.messenger.store import MessengerStore
    store = MessengerStore(tmp_path / "m.db")
    cols = set(store.column_names("m_outbound_queue"))
    assert {"why", "stance"} <= cols


def test_outbound_queue_migration_is_idempotent_on_existing_db(tmp_path):
    """A pre-existing queue table without why/stance gains the columns."""
    import sqlite3
    from soveryn.app.messenger.store import MessengerStore
    db = tmp_path / "old.db"
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE m_outbound_queue ("
            "intent_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, agent TEXT NOT NULL, "
            "thread_id TEXT, content TEXT NOT NULL, context_hint TEXT NOT NULL, "
            "urgency TEXT NOT NULL, triggered_by TEXT NOT NULL, created_at TEXT NOT NULL, "
            "delivered_at TEXT, delivery_state TEXT NOT NULL DEFAULT 'pending')"
        )
    store = MessengerStore(db)  # init must add columns without error
    cols = set(store.column_names("m_outbound_queue"))
    assert {"why", "stance"} <= cols
