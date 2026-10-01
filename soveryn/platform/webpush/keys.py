"""VAPID keypair for Web Push — generated once, stored under data/memory."""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_PATH = Path.home() / "soveryn_vnext" / "data" / "memory" / "vapid_keys.json"


def _keys_path() -> Path:
    raw = os.environ.get("SOVERYN_VAPID_KEYS_PATH", "").strip()
    return Path(raw) if raw else _DEFAULT_PATH


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _ensure_keys(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))

    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256R1())
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    pub_numbers = private_key.public_key().public_numbers()
    x = pub_numbers.x.to_bytes(32, "big")
    y = pub_numbers.y.to_bytes(32, "big")
    # Uncompressed EC point — Web Push public key form
    public_b64 = _b64url(b"\x04" + x + y)

    payload = {
        "publicKey": public_b64,
        "privateKeyPem": priv_pem,
        # Apple Web Push rejects .local mailto — use a real house contact.
        "subject": os.environ.get(
            "SOVERYN_VAPID_SUBJECT", "mailto:jon@soverynintelligence.com"
        ),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    logger.info("webpush: minted VAPID keys at %s", path)
    return payload


def load_vapid() -> dict[str, Any]:
    return _ensure_keys(_keys_path())


def get_vapid_public_key() -> str:
    return str(load_vapid()["publicKey"])
