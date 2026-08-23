"""Citizen / desk email identities — house-owned From addresses.

Not AgentMail. Each founding hand (and the PondWright desk) gets allowlisted
From addresses on house domains. SMTP still arms via SOVERYN_SMTP_*; this
module only decides *who they may write as*.

Override with SOVERYN_EMAIL_IDENTITIES JSON, e.g.:
  {"aetheria":{"default":"aetheria@soverynintelligence.com",
               "aliases":["aetheria@soverynintelligence.com",
                          "aetheria@carolinawatergardens.com"]}}
"""
from __future__ import annotations

import json
import os
from typing import Any

# Domains Jon locked for v0 (AgentMail-wave steal, house-shaped).
SOVERYN_DOMAIN = "soverynintelligence.com"
CWG_DOMAIN = "carolinawatergardens.com"

DEFAULT_IDENTITIES: dict[str, dict[str, Any]] = {
    "aetheria": {
        "default": f"aetheria@{SOVERYN_DOMAIN}",
        "aliases": [
            f"aetheria@{SOVERYN_DOMAIN}",
            f"aetheria@{CWG_DOMAIN}",
        ],
        "note": "CoS — house + CWG voice",
    },
    "vett": {
        "default": f"vett@{SOVERYN_DOMAIN}",
        "aliases": [
            f"vett@{SOVERYN_DOMAIN}",
            f"vett@{CWG_DOMAIN}",
        ],
        "note": "Research — house + CWG",
    },
    "eve": {
        "default": f"eve@{SOVERYN_DOMAIN}",
        "aliases": [f"eve@{SOVERYN_DOMAIN}"],
        "note": "Presence / online",
    },
    "scotty": {
        "default": f"scotty@{SOVERYN_DOMAIN}",
        "aliases": [f"scotty@{SOVERYN_DOMAIN}"],
        "note": "Engineering",
    },
    "kernel": {
        "default": f"kernel@{SOVERYN_DOMAIN}",
        "aliases": [f"kernel@{SOVERYN_DOMAIN}"],
        "note": "Build / code (when resident)",
    },
    # Desk agent identity (not a citizens.db row yet) — Aetheria/Vett may
    # send-as PondWright for CWG customer-facing mail when Gate allows.
    "pondwright": {
        "default": f"pondwright@{CWG_DOMAIN}",
        "aliases": [f"pondwright@{CWG_DOMAIN}"],
        "note": "CWG desk agent status address",
        "desk": "cwg",
    },
}

# Who may send-as a desk identity (in addition to their own aliases).
DESK_SEND_AS: dict[str, tuple[str, ...]] = {
    "aetheria": ("pondwright",),
    "vett": ("pondwright",),
}


def _normalize_addr(addr: str) -> str:
    return (addr or "").strip().lower()


def load_identities() -> dict[str, dict[str, Any]]:
    """Merge defaults with optional SOVERYN_EMAIL_IDENTITIES JSON override."""
    out: dict[str, dict[str, Any]] = {
        k: {
            "default": v["default"],
            "aliases": list(v["aliases"]),
            "note": v.get("note") or "",
            **({"desk": v["desk"]} if v.get("desk") else {}),
        }
        for k, v in DEFAULT_IDENTITIES.items()
    }
    raw = (os.environ.get("SOVERYN_EMAIL_IDENTITIES") or "").strip()
    if not raw:
        return out
    try:
        overlay = json.loads(raw)
    except json.JSONDecodeError:
        return out
    if not isinstance(overlay, dict):
        return out
    for cid, spec in overlay.items():
        if not isinstance(spec, dict):
            continue
        key = str(cid).strip().lower()
        base = out.get(key, {"default": "", "aliases": [], "note": ""})
        aliases = spec.get("aliases")
        if isinstance(aliases, list):
            base["aliases"] = [_normalize_addr(a) for a in aliases if str(a).strip()]
        default = spec.get("default")
        if default:
            base["default"] = _normalize_addr(str(default))
            if base["default"] not in base["aliases"]:
                base["aliases"].insert(0, base["default"])
        if spec.get("note"):
            base["note"] = str(spec["note"])
        out[key] = base
    return out


def identity_for(citizen_id: str) -> dict[str, Any] | None:
    cid = (citizen_id or "").strip().lower()
    return load_identities().get(cid)


def allowed_from_addresses(citizen_id: str) -> list[str]:
    """Addresses this citizen may put in From (own + desk send-as)."""
    cid = (citizen_id or "").strip().lower()
    identities = load_identities()
    allowed: list[str] = []
    own = identities.get(cid)
    if own:
        for a in own.get("aliases") or []:
            n = _normalize_addr(a)
            if n and n not in allowed:
                allowed.append(n)
    for desk_id in DESK_SEND_AS.get(cid, ()):
        desk = identities.get(desk_id)
        if not desk:
            continue
        for a in desk.get("aliases") or []:
            n = _normalize_addr(a)
            if n and n not in allowed:
                allowed.append(n)
    return allowed


def resolve_from_address(
    citizen_id: str,
    requested: str | None = None,
) -> tuple[str | None, str | None]:
    """Pick From for a send. Returns (address, error).

    If ``requested`` is set it must be on the citizen allowlist.
    Otherwise use the citizen's default identity.
    """
    cid = (citizen_id or "").strip().lower()
    allowed = allowed_from_addresses(cid)
    if not allowed:
        return None, f"no email identity mapped for {cid!r}"
    req = _normalize_addr(requested or "")
    if req:
        if req not in allowed:
            return None, (
                f"from {req!r} not allowed for {cid}; "
                f"allowed: {', '.join(allowed)}"
            )
        return req, None
    ident = identity_for(cid)
    default = _normalize_addr((ident or {}).get("default") or "") or allowed[0]
    return default, None


def board_identities() -> dict[str, Any]:
    """Payload fragment for Citizens / connectors board."""
    identities = load_identities()
    by_citizen = {
        cid: {
            "default": identities[cid]["default"],
            "aliases": list(identities[cid]["aliases"]),
            "note": identities[cid].get("note") or "",
            "allowed_from": allowed_from_addresses(cid),
        }
        for cid in ("aetheria", "vett", "eve", "scotty", "kernel")
        if cid in identities
    }
    return {
        "domains": [SOVERYN_DOMAIN, CWG_DOMAIN],
        "by_citizen": by_citizen,
        "desk": {
            "pondwright": identities.get("pondwright"),
        },
        "reading": (
            "Citizens send as house-owned addresses — not Jon's personal Gmail. "
            "DNS aliases + SPF/DKIM on each domain, then arm SOVERYN_SMTP_*. "
            "email_send stays behind Approval Gate."
        ),
    }
