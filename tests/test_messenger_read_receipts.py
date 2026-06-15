"""Read receipts surface back to agent — Task 21 (Aetheria's Q7).

The PWA marks-read via POST /m/threads/<tid>/read. The agent introspects
her own outbound via the `list_my_outbound` tool to see whether what she
sent has been delivered + read. Loop closure, not surveillance.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from flask import Flask

from soveryn.agents.messenger_introspect_tool import build_list_my_outbound_tool
from soveryn.app.messenger.store import MessengerStore
from soveryn.app.routes.messenger import build_messenger_blueprint
from soveryn.memory.conversation_store import ConversationStore


@pytest.fixture
def m_store(tmp_path):
    return MessengerStore(tmp_path / "m.db")


def _seed_delivered_intent(
    store: MessengerStore,
    *,
    intent_id: str,
    agent: str,
    thread_id: str | None,
    content: str = "hello",
    context_hint: str = "x",
    urgency: str = "routine",
    triggered_by: str = "test",
    devices: tuple[tuple[str, bool], ...] = (),
) -> None:
    """Seed an outbound intent in 'delivered' state with per-device delivery
    rows. `devices` is a tuple of (device_id, read) — read=True sets read_at."""
    now = datetime.now(timezone.utc).isoformat()
    with store._conn() as con:
        con.execute(
            "INSERT INTO m_outbound_queue "
            "(intent_id, user_id, agent, thread_id, content, context_hint, "
            "urgency, triggered_by, created_at, delivered_at, delivery_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'delivered')",
            (intent_id, "jon", agent, thread_id, content, context_hint,
             urgency, triggered_by, now, now),
        )
        for device_id, read in devices:
            con.execute(
                "INSERT INTO m_outbound_delivery_per_device "
                "(intent_id, device_id, sent_at, received_at, read_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (intent_id, device_id, now, now, now if read else None),
            )


# -- store-level tests ------------------------------------------------------


def test_mark_thread_read_updates_delivery_per_device(m_store):
    tid = "thread-abc"
    did = "device-pixel"
    _seed_delivered_intent(
        m_store, intent_id="i1", agent="aetheria", thread_id=tid,
        devices=((did, False),),
    )
    n = m_store.mark_thread_read(thread_id=tid, device_id=did)
    assert n == 1

    with m_store._conn() as con:
        row = con.execute(
            "SELECT read_at FROM m_outbound_delivery_per_device "
            "WHERE intent_id=? AND device_id=?",
            ("i1", did),
        ).fetchone()
    assert row is not None
    assert row["read_at"] is not None


def test_mark_thread_read_includes_default_thread_intents(m_store):
    """thread_id IS NULL on the queue row → resolved to default thread at
    delivery time. mark_thread_read should pick those up too."""
    tid = "thread-default"
    did = "device-pixel"
    _seed_delivered_intent(
        m_store, intent_id="i-default", agent="aetheria", thread_id=None,
        devices=((did, False),),
    )
    _seed_delivered_intent(
        m_store, intent_id="i-bound", agent="aetheria", thread_id=tid,
        devices=((did, False),),
    )
    n = m_store.mark_thread_read(thread_id=tid, device_id=did)
    assert n == 2


def test_mark_thread_read_skips_other_devices(m_store):
    tid = "thread-abc"
    _seed_delivered_intent(
        m_store, intent_id="i1", agent="aetheria", thread_id=tid,
        devices=(("device-A", False), ("device-B", False)),
    )
    n = m_store.mark_thread_read(thread_id=tid, device_id="device-A")
    assert n == 1
    with m_store._conn() as con:
        row_b = con.execute(
            "SELECT read_at FROM m_outbound_delivery_per_device "
            "WHERE intent_id=? AND device_id=?",
            ("i1", "device-B"),
        ).fetchone()
    assert row_b["read_at"] is None


def test_mark_thread_read_idempotent_for_already_read_rows(m_store):
    tid = "thread-abc"
    did = "device-pixel"
    _seed_delivered_intent(
        m_store, intent_id="i1", agent="aetheria", thread_id=tid,
        devices=((did, True),),  # already read
    )
    # Already-read rows are filtered out — return 0, no overwrite.
    n = m_store.mark_thread_read(thread_id=tid, device_id=did)
    assert n == 0


def test_list_outbound_aggregates_read_state(m_store):
    """A single intent delivered to two devices, one of which has read it,
    should report read_by_devices=1, delivered_to_devices=2."""
    tid = "thread-abc"
    _seed_delivered_intent(
        m_store, intent_id="i1", agent="aetheria", thread_id=tid,
        content="message body",
        devices=(("device-A", True), ("device-B", False)),
    )
    rows = m_store.list_outbound_for_agent(agent="aetheria")
    assert len(rows) == 1
    row = rows[0]
    assert row["intent_id"] == "i1"
    assert row["delivered_to_devices"] == 2
    assert row["read_by_devices"] == 1
    assert row["delivery_state"] == "delivered"


def test_list_outbound_scopes_to_owner_agent(m_store):
    _seed_delivered_intent(
        m_store, intent_id="a1", agent="aetheria", thread_id=None,
        devices=(("d", True),),
    )
    _seed_delivered_intent(
        m_store, intent_id="v1", agent="vett", thread_id=None,
        devices=(("d", True),),
    )
    rows = m_store.list_outbound_for_agent(agent="aetheria")
    assert {r["intent_id"] for r in rows} == {"a1"}


def test_list_outbound_truncates_content_preview(m_store):
    long_body = "x" * 500
    _seed_delivered_intent(
        m_store, intent_id="i1", agent="aetheria", thread_id=None,
        content=long_body, devices=(),
    )
    rows = m_store.list_outbound_for_agent(agent="aetheria")
    assert len(rows[0]["content_preview"]) == 140


def test_list_outbound_handles_intent_with_no_device_rows(m_store):
    """A pending intent with no per-device delivery yet should still
    surface with read_by_devices=0, delivered_to_devices=0."""
    now = datetime.now(timezone.utc).isoformat()
    with m_store._conn() as con:
        con.execute(
            "INSERT INTO m_outbound_queue "
            "(intent_id, user_id, agent, thread_id, content, context_hint, "
            "urgency, triggered_by, created_at, delivery_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            ("i-pending", "jon", "aetheria", None, "queued", "x",
             "routine", "test", now),
        )
    rows = m_store.list_outbound_for_agent(agent="aetheria")
    assert len(rows) == 1
    assert rows[0]["read_by_devices"] == 0
    assert rows[0]["delivered_to_devices"] == 0
    assert rows[0]["delivery_state"] == "pending"


# -- introspection tool tests -----------------------------------------------


def test_list_my_outbound_tool_returns_recent_rows(m_store):
    _seed_delivered_intent(
        m_store, intent_id="i1", agent="aetheria", thread_id=None,
        devices=(("device-A", True),),
    )
    tool = build_list_my_outbound_tool(store=m_store, owner_agent="aetheria")
    out = tool.handler({})
    assert out["count"] == 1
    assert out["outbound"][0]["intent_id"] == "i1"
    assert out["outbound"][0]["read_by_devices"] == 1


def test_list_my_outbound_tool_respects_limit(m_store):
    for i in range(5):
        _seed_delivered_intent(
            m_store, intent_id=f"i{i}", agent="aetheria", thread_id=None,
            devices=(("d", False),),
        )
    tool = build_list_my_outbound_tool(store=m_store, owner_agent="aetheria")
    out = tool.handler({"limit": 2})
    assert out["count"] == 2


def test_list_my_outbound_tool_description_carries_q7_framing():
    """Aetheria's Q7 verdict is encoded in the description so the model
    sees the framing alongside the schema."""
    store = MessengerStore  # type-only reference; not instantiated
    tool = build_list_my_outbound_tool(store=None, owner_agent="aetheria")  # type: ignore[arg-type]
    assert "Loop closure, not surveillance." in tool.description


# -- HTTP route tests -------------------------------------------------------


@pytest.fixture
def app(tmp_path):
    flask_app = Flask(__name__)
    messenger_store = MessengerStore(tmp_path / "m.db")
    conv_store = ConversationStore(tmp_path / "conv.db")
    bp = build_messenger_blueprint(
        messenger_store=messenger_store,
        conv_store=conv_store,
        agent_loops={},
    )
    flask_app.register_blueprint(bp)
    flask_app.config["TESTING"] = True
    flask_app.config["_messenger_store"] = messenger_store
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()


def _pair_and_get_secret(client) -> tuple[str, str]:
    mint = client.post(
        "/m/pair", json={"label": "phone"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    code = mint.get_json()["code"]
    claim = client.post(f"/m/pair/{code}", json={"device_label": "Pixel 9"})
    body = claim.get_json()
    return body["secret"], body["device_id"]


def test_read_route_requires_auth(client):
    resp = client.post("/m/threads/thread-anything/read")
    assert resp.status_code == 401


def test_read_route_returns_marked_count(app, client):
    secret, device_id = _pair_and_get_secret(client)
    store: MessengerStore = app.config["_messenger_store"]
    tid = "thread-abc"
    _seed_delivered_intent(
        store, intent_id="i1", agent="aetheria", thread_id=tid,
        devices=((device_id, False),),
    )
    _seed_delivered_intent(
        store, intent_id="i2", agent="aetheria", thread_id=tid,
        devices=((device_id, False),),
    )

    resp = client.post(
        f"/m/threads/{tid}/read",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {"marked_read": 2}


def test_read_route_zero_when_nothing_to_mark(client):
    secret, _ = _pair_and_get_secret(client)
    resp = client.post(
        "/m/threads/empty-thread/read",
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert resp.status_code == 200
    assert resp.get_json() == {"marked_read": 0}
