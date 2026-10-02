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
CWG_DOMAIN = "carolinawatergardens.com"  # plugin overlay; kept for import compatibility

DEFAULT_IDENTITIES: dict[str, dict[str, Any]] = {
    "aetheria": {
        "default": f"aetheria@{SOVERYN_DOMAIN}",
        "aliases": [
            f"aetheria@{SOVERYN_DOMAIN}",
        ],
        "note": "CoS — house voice",
    },
    "vett": {
        "default": f"vett@{SOVERYN_DOMAIN}",
        "aliases": [
            f"vett@{SOVERYN_DOMAIN}",
        ],
        "note": "FOLDED into Eve — not a live citizen (2026-08-23 note); row kept for design history only",
        "folded": True,
    },
    "eve": {
        "default": f"eve@{SOVERYN_DOMAIN}",
        "aliases": [
            f"eve@{SOVERYN_DOMAIN}",
        ],
        "note": "Presence / online",
    },
    "scotty": {
        "default": f"scotty@{SOVERYN_DOMAIN}",
        "aliases": [f"scotty@{SOVERYN_DOMAIN}"],
        "note": "FOLDED into Kernel — not a live citizen (2026-08-23 note); row kept for design history only",
        "folded": True,
    },
    "kernel": {
        "default": f"kernel@{SOVERYN_DOMAIN}",
        "aliases": [f"kernel@{SOVERYN_DOMAIN}"],
        "note": "Build / code (when resident)",
    },
}

# Who may send-as a desk identity (in addition to their own aliases).
# vett removed 2026-09-08 — folded into Eve, so no live citizen holds it.
DESK_SEND_AS: dict[str, tuple[str, ...]] = {
    "aetheria": ("pondwright",),
}


def _normalize_addr(addr: str) -> str:
    return (addr or "").strip().lower()


def _identity_domains() -> list[str]:
    domains = [SOVERYN_DOMAIN]
    try:
        from soveryn.plugins.loader import plugin_email_identities

        extra = plugin_email_identities()
    except Exception:
        extra = {}
    packed = extra.get("_domains") if isinstance(extra.get("_domains"), dict) else {}
    for item in packed.get("aliases") or []:
        name = str(item or "").strip().lower()
        if name and name not in domains:
            domains.append(name)
    if extra.get("pondwright") and CWG_DOMAIN not in domains:
        domains.append(CWG_DOMAIN)
    return domains


def _copy_identity(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "default": spec.get("default") or "",
        "aliases": list(spec.get("aliases") or []),
        "note": spec.get("note") or "",
        **({"desk": spec["desk"]} if spec.get("desk") else {}),
        **({"folded": True} if spec.get("folded") else {}),
    }


def _merge_identity(base: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    aliases = spec.get("aliases")
    if isinstance(aliases, list):
        extra = [_normalize_addr(a) for a in aliases if str(a).strip()]
        for addr in extra:
            if addr and addr not in base["aliases"]:
                base["aliases"].append(addr)
    default = spec.get("default")
    if default:
        base["default"] = _normalize_addr(str(default))
        if base["default"] and base["default"] not in base["aliases"]:
            base["aliases"].insert(0, base["default"])
    if spec.get("note"):
        base["note"] = str(spec["note"])
    if spec.get("desk"):
        base["desk"] = spec["desk"]
    if spec.get("folded"):
        base["folded"] = True
    return base


def load_identities() -> dict[str, dict[str, Any]]:
    """Merge defaults, plugin overlay, then SOVERYN_EMAIL_IDENTITIES (env wins)."""
    out: dict[str, dict[str, Any]] = {
        k: _copy_identity(v) for k, v in DEFAULT_IDENTITIES.items()
    }
    try:
        from soveryn.plugins.loader import plugin_email_identities

        overlay = plugin_email_identities()
    except Exception:
        overlay = {}
    for cid, spec in overlay.items():
        if cid.startswith("_") or not isinstance(spec, dict):
            continue
        key = str(cid).strip().lower()
        base = out.get(key, {"default": "", "aliases": [], "note": ""})
        out[key] = _merge_identity(base, spec)
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
    """Addresses this citizen may put in From (own + desk send-as).

    Folded rows (vett, scotty) yield no addresses — the allowlist must match
    the live roster per the 2026-08-23 citizen-email-identity note.
    """
    cid = (citizen_id or "").strip().lower()
    identities = load_identities()
    allowed: list[str] = []
    own = identities.get(cid)
    if own and not own.get("folded"):
        for a in own.get("aliases") or []:
            n = _normalize_addr(a)
            if n and n not in allowed:
                allowed.append(n)
    for desk_id in DESK_SEND_AS.get(cid, ()):
        desk = identities.get(desk_id)
        if not desk or desk.get("folded"):
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
    # Mirror connectors.email_armed without importing (avoid cycle).
    smtp_ready = bool(
        (os.environ.get("SOVERYN_SMTP_HOST") or os.environ.get("SMTP_HOST"))
        and (os.environ.get("SOVERYN_SMTP_FROM") or os.environ.get("SMTP_FROM"))
    )
    latch = os.environ.get("SOVERYN_EMAIL_PRODUCTION", "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    prod = bool(smtp_ready and latch)
    return {
        "domains": _identity_domains(),
        "by_citizen": by_citizen,
        "desk": {
            "pondwright": identities.get("pondwright"),
        },
        "reading": (
            "NOT PRODUCTION: identity map is designed; live send is off until "
            "DNS aliases + SPF/DKIM, SOVERYN_SMTP_*, and SOVERYN_EMAIL_PRODUCTION=1. "
            "Citizens will send as house-owned addresses — never Jon's personal Gmail. "
            "email_send stays behind Approval Gate."
            if not prod
            else (
                "Citizen email production latch is on — send as house-owned addresses "
                "(never Jon's personal Gmail). email_send stays behind Approval Gate."
            )
        ),
        "production": prod,
        "status": "production" if prod else "not_production",
    }
