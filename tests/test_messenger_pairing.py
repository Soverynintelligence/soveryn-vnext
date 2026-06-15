"""Pairing token mint, claim, expiry, single-use semantics."""
from __future__ import annotations
import time
from datetime import datetime, timedelta, timezone
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.pairing import (
    mint_pairing_token,
    claim_pairing_token,
    PairingError,
)


@pytest.fixture
def store(tmp_path):
    return MessengerStore(tmp_path / "messenger.db")


def test_mint_returns_short_code(store):
    token = mint_pairing_token(store, label="phone")
    # Format: ABCD-EFGH-1234 - 14 chars including dashes
    assert len(token.code) == 14
    assert token.label == "phone"


def test_claim_with_valid_token_mints_device(store):
    token = mint_pairing_token(store, label="phone")
    device = claim_pairing_token(store, code=token.code, device_label="Pixel 9")
    assert device.device_id
    assert device.secret  # plaintext, returned once
    assert device.label == "Pixel 9"


def test_claim_token_twice_fails(store):
    token = mint_pairing_token(store, label="phone")
    claim_pairing_token(store, code=token.code, device_label="Pixel 9")
    with pytest.raises(PairingError, match="already claimed"):
        claim_pairing_token(store, code=token.code, device_label="someone else")


def test_claim_expired_token_fails(store, monkeypatch):
    # Mint with a TTL we control
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    monkeypatch.setattr(
        "soveryn.app.messenger.pairing._now_iso",
        lambda: past_iso,
    )
    token = mint_pairing_token(store, label="phone", ttl_seconds=60)
    # Reset clock to current
    monkeypatch.undo()
    with pytest.raises(PairingError, match="expired"):
        claim_pairing_token(store, code=token.code, device_label="late")


def test_claim_unknown_token_fails(store):
    with pytest.raises(PairingError, match="unknown"):
        claim_pairing_token(store, code="WXYZ-1234-ABCD", device_label="x")
