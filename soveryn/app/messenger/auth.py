"""Device bearer-token verification + revocation.

Every authenticated /m/* request carries `Authorization: Bearer <secret>`.
`verify_device_secret` looks up the device, recomputes the hash with the
stored salt, and constant-time compares. Revoked devices are distinguished
from invalid secrets so callers can surface a clearer error.
"""
from __future__ import annotations
import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from soveryn.app.messenger.store import MessengerStore


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class AuthedDevice:
    device_id: str
    label: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def verify_device_secret(
    store: MessengerStore,
    *,
    secret: str,
) -> AuthedDevice:
    """Look up every device, recompute hash, constant-time match.

    Distinguishes "invalid secret" from "valid secret on a revoked device" so
    the caller can surface a clearer error to the phone. Cost is O(N devices);
    fine for a single-user box, swap to a prefix index if multi-user lands.
    """
    with store._conn() as con:
        rows = con.execute(
            "SELECT device_id, secret_hash, label, revoked_at FROM m_devices"
        ).fetchall()
    for row in rows:
        salt, expected_hash = row["secret_hash"].split("$", 1)
        actual_hash = hashlib.sha256((salt + secret).encode()).hexdigest()
        if hmac.compare_digest(actual_hash, expected_hash):
            if row["revoked_at"]:
                raise AuthError(f"device revoked at {row['revoked_at']}")
            with store._conn() as con:
                con.execute(
                    "UPDATE m_devices SET last_seen_at=? WHERE device_id=?",
                    (_now_iso(), row["device_id"]),
                )
            return AuthedDevice(device_id=row["device_id"], label=row["label"])
    raise AuthError("invalid device secret")


def revoke_device(store: MessengerStore, *, device_id: str) -> None:
    """Mark device revoked. Subsequent verify calls will raise AuthError.

    Idempotent — second call (or a call against an unknown device_id) is a
    no-op.
    """
    with store._conn() as con:
        row = con.execute(
            "SELECT device_id, revoked_at FROM m_devices WHERE device_id=?",
            (device_id,),
        ).fetchone()
        if row is None:
            return  # never existed
        if row["revoked_at"]:
            return  # already revoked
        con.execute(
            "UPDATE m_devices SET revoked_at=? WHERE device_id=?",
            (_now_iso(), device_id),
        )
