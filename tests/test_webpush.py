"""Web Push store + Gate notify hook (Messages PWA)."""

from __future__ import annotations

from pathlib import Path

from soveryn.platform.webpush import store as push_store
from soveryn.platform.webpush.notify import should_notify_phone
from soveryn.platform.webpush.keys import get_vapid_public_key, load_vapid
from soveryn.platform.approval.store import ApprovalBroker, ApprovalStore


def test_parked_messages_peers_do_not_wake_phone():
    assert should_notify_phone("vett") is False
    assert should_notify_phone("scotty") is False
    assert should_notify_phone("eve") is True
    assert should_notify_phone("aetheria") is True
    assert should_notify_phone("kernel") is True


def test_vapid_keys_mint_once(tmp_path: Path, monkeypatch):
    path = tmp_path / "vapid.json"
    monkeypatch.setenv("SOVERYN_VAPID_KEYS_PATH", str(path))
    a = load_vapid()
    b = load_vapid()
    assert a["publicKey"] == b["publicKey"]
    assert "BEGIN PRIVATE KEY" in a["privateKeyPem"]
    assert get_vapid_public_key() == a["publicKey"]


def test_subscription_upsert_and_list(tmp_path: Path, monkeypatch):
    db = tmp_path / "webpush.db"
    monkeypatch.setenv("SOVERYN_WEBPUSH_DB", str(db))
    push_store.upsert_subscription(
        endpoint="https://push.example/x",
        p256dh="abc",
        auth="def",
        user_agent="test",
    )
    rows = push_store.list_subscriptions()
    assert len(rows) == 1
    assert rows[0]["endpoint"].endswith("/x")
    info = push_store.subscription_info(rows[0])
    assert info["keys"]["p256dh"] == "abc"
    assert push_store.remove_subscription("https://push.example/x") is True
    assert push_store.list_subscriptions() == []


def test_approval_broker_request_does_not_raise_without_subs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOVERYN_WEBPUSH_DB", str(tmp_path / "empty.db"))
    monkeypatch.setenv("SOVERYN_VAPID_KEYS_PATH", str(tmp_path / "vapid.json"))
    store = ApprovalStore(tmp_path / "approvals.db")
    broker = ApprovalBroker(store, ttl_seconds=5.0, poll_interval_seconds=0.05)
    req = broker.request(
        citizen="eve",
        tool="compose_post",
        args={"platform": "x", "content": "hi"},
        now="2026-08-25T12:00:00",
    )
    assert req.id
    assert req.citizen == "eve"


def test_webpush_send_during_tests_does_not_call_the_network(
    webpush_network_guard, monkeypatch
):
    """A push with a live-looking subscription must not open a socket.

    The autouse fixture stubs pywebpush.webpush and points the store at a
    temp data root. This exercises the real _send_all path so a regression
    that drops the stub would fail on the socket probe, not silently hit FCM.
    """
    import socket

    from soveryn.platform.webpush.notify import _send_all

    opened: list[object] = []

    def _forbid_connect(self, address):
        opened.append(address)
        raise AssertionError(f"outbound socket forbidden during tests: {address}")

    monkeypatch.setattr(socket.socket, "connect", _forbid_connect)

    push_store.upsert_subscription(
        endpoint="https://fcm.googleapis.com/fcm/send/test-subscription",
        p256dh="dGVzdC1wMjU2ZGg",
        auth="dGVzdC1hdXRo",
        user_agent="regression",
    )
    _send_all(title="needs you", body="ping", url="/messages", tag="regression")

    assert opened == []
    assert webpush_network_guard.calls, "expected the pywebpush stub to intercept the send"
    endpoint = webpush_network_guard.calls[0]["kwargs"].get("subscription_info", {}).get(
        "endpoint"
    )
    if endpoint is None and webpush_network_guard.calls[0]["args"]:
        info = webpush_network_guard.calls[0]["args"][0]
        endpoint = info.get("endpoint") if isinstance(info, dict) else None
    assert endpoint == "https://fcm.googleapis.com/fcm/send/test-subscription"


def test_webpush_db_follows_temp_data_root(tmp_path: Path, monkeypatch):
    """SOVERYN_DATA_ROOT must win over the checkout's live webpush.db."""
    monkeypatch.delenv("SOVERYN_WEBPUSH_DB", raising=False)
    data_root = tmp_path / "temp-data-root"
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(data_root))
    push_store.upsert_subscription(
        endpoint="https://push.example/isolated",
        p256dh="abc",
        auth="def",
    )
    assert (data_root / "memory" / "webpush.db").is_file()
    rows = push_store.list_subscriptions()
    assert len(rows) == 1
    assert rows[0]["endpoint"].endswith("/isolated")
