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
