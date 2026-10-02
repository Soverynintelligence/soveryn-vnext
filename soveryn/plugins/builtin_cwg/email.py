"""CWG email identity overlay (aliases + pondwright desk)."""

from __future__ import annotations

from typing import Any

CWG_DOMAIN = "carolinawatergardens.com"


def identities() -> dict[str, dict[str, Any]]:
    return {
        "aetheria": {
            "aliases": [f"aetheria@{CWG_DOMAIN}"],
            "note": "CoS — house + CWG voice",
        },
        "vett": {
            "aliases": [f"vett@{CWG_DOMAIN}"],
        },
        "eve": {
            "aliases": [f"eve@{CWG_DOMAIN}"],
            "note": "Presence / online + CWG Zoho alias",
        },
        "pondwright": {
            "default": f"pondwright@{CWG_DOMAIN}",
            "aliases": [f"pondwright@{CWG_DOMAIN}"],
            "note": "CWG desk agent status address",
            "desk": "cwg",
        },
        "_domains": {"aliases": [CWG_DOMAIN]},
    }
