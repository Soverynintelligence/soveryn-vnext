"""Pairing token mint + claim flow.

Pairing tokens are short-lived (5 min default), single-use, and bind
the device's public state (label) at first claim. Once claimed, the
token is dead - second claim attempts fail explicitly.

The claim returns the device's secret in plaintext ONCE. The secret
hash (sha256 + per-device salt) is stored; the secret itself is the
phone's bearer token for future requests.
"""
from __future__ import annotations
import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from soveryn.app.messenger.store import MessengerStore


_DEFAULT_TOKEN_TTL_SECONDS = 300  # 5 minutes
_TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes I,O,0,1 for readability


class PairingError(Exception):
    pass


@dataclass(frozen=True)
class PairingToken:
    code: str
    label: str
    expires_at: str


@dataclass(frozen=True)
class PairedDevice:
    device_id: str
    secret: str  # plaintext - returned ONCE on claim
    label: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_chunk(n: int = 4) -> str:
    return "".join(secrets.choice(_TOKEN_ALPHABET) for _ in range(n))


def mint_pairing_token(
    store: MessengerStore,
    *,
    label: str,
    ttl_seconds: int = _DEFAULT_TOKEN_TTL_SECONDS,
) -> PairingToken:
    """Generate a short pairing code (e.g. 'ABCD-EFGH-1234')."""
    code = f"{_random_chunk()}-{_random_chunk()}-{_random_chunk()}"
    created_at = _now_iso()
    expires_at = (
        datetime.fromisoformat(created_at) + timedelta(seconds=ttl_seconds)
    ).isoformat()
    with store._conn() as con:
        con.execute(
            "INSERT INTO m_pairing_tokens (token, label, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (code, label, created_at, expires_at),
        )
    return PairingToken(code=code, label=label, expires_at=expires_at)


def claim_pairing_token(
    store: MessengerStore,
    *,
    code: str,
    device_label: str | None = None,
) -> PairedDevice:
    """Atomically claim a token + mint a device secret.

    The client's label wins when it sends one — the device knows what it is.
    When it sends nothing, the label typed at mint time is used instead of the
    old "unknown device" placeholder, which was stored on the token and then
    discarded. That placeholder is why the device list read "Phone" or
    "unknown device" for every row, and why three superseded pairings sat
    active for six weeks looking identical to the live one.
    """
    with store._conn() as con:
        row = con.execute(
            "SELECT * FROM m_pairing_tokens WHERE token=?", (code,),
        ).fetchone()
        if row is None:
            raise PairingError(f"unknown pairing code {code!r}")
        if row["claimed_by"]:
            raise PairingError(f"pairing code {code!r} already claimed")
        if row["expires_at"] < _now_iso():
            raise PairingError(f"pairing code {code!r} expired at {row['expires_at']}")

        # Client label first (it knows the hardware), minted label second,
        # generic last. Never a placeholder that makes rows indistinguishable.
        label = (device_label or "").strip() or (row["label"] or "").strip() or "device"

        device_id = str(uuid.uuid4())
        secret = secrets.token_urlsafe(32)
        salt = os.urandom(16).hex()
        secret_hash = hashlib.sha256((salt + secret).encode()).hexdigest()
        stored = f"{salt}${secret_hash}"
        now = _now_iso()

        con.execute(
            "INSERT INTO m_devices (device_id, secret_hash, label, created_at) "
            "VALUES (?, ?, ?, ?)",
            (device_id, stored, label, now),
        )
        con.execute(
            "UPDATE m_pairing_tokens SET claimed_by=?, claimed_at=? WHERE token=?",
            (device_id, now, code),
        )

    return PairedDevice(device_id=device_id, secret=secret, label=label)
