"""Device bearer-token verification + revocation."""
from __future__ import annotations
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.pairing import mint_pairing_token, claim_pairing_token
from soveryn.app.messenger.auth import (
    verify_device_secret,
    revoke_device,
    AuthError,
)


@pytest.fixture
def store_with_device(tmp_path):
    store = MessengerStore(tmp_path / "messenger.db")
    token = mint_pairing_token(store, label="phone")
    device = claim_pairing_token(store, code=token.code, device_label="Pixel 9")
    return store, device


def test_verify_valid_secret_returns_device(store_with_device):
    store, device = store_with_device
    out = verify_device_secret(store, secret=device.secret)
    assert out.device_id == device.device_id
    assert out.label == "Pixel 9"


def test_verify_wrong_secret_raises(store_with_device):
    store, _ = store_with_device
    with pytest.raises(AuthError, match="invalid"):
        verify_device_secret(store, secret="not-a-real-secret")


def test_verify_revoked_device_raises(store_with_device):
    store, device = store_with_device
    revoke_device(store, device_id=device.device_id)
    with pytest.raises(AuthError, match="revoked"):
        verify_device_secret(store, secret=device.secret)


def test_revoke_idempotent(store_with_device):
    store, device = store_with_device
    revoke_device(store, device_id=device.device_id)
    revoke_device(store, device_id=device.device_id)  # no exception
