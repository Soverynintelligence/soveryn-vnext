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
