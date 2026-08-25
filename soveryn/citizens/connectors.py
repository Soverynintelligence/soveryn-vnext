"""Connectors — what a citizen is allowed to touch outside (or across) the house.

Tools already exist (web_search, fetch_url, signal, messenger, …). What was
missing was a **grant map**: which citizen holds which channel, whether it is
actually configured, and what sovereignty rule applies.

Connectors are *capabilities*, not cloud SaaS agent plugins. Default: house
network. Email is optional and **not production** until Jon sets SMTP/IMAP
*and* ``SOVERYN_EMAIL_PRODUCTION=1`` after DNS aliases + SPF/DKIM smoke. Web goes
through house SearXNG — content fetch, not vendor control-plane.

Board surfaces this so the roster answers "what can they actually do?" without
reading startup.py.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

# ── catalog ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConnectorDef:
    id: str
    title: str
    description: str
    tools: tuple[str, ...]
    # sovereignty class for the board
    class_: str  # house | channel | optional_egress
    sovereignty_note: str


CATALOG: dict[str, ConnectorDef] = {
    "web": ConnectorDef(
        id="web",
        title="Web",
        description="Search and read the public web via house SearXNG + fetch.",
        tools=("web_search", "fetch_url"),
        class_="house",
        sovereignty_note=(
            "Read-only through house SearXNG — no Gate click. "
            "Write egress (email/X/messenger) still needs Approval Gate."
        ),
    ),
    "email": ConnectorDef(
        id="email",
        title="Email",
        description=(
            "NOT PRODUCTION until SMTP + SOVERYN_EMAIL_PRODUCTION=1. "
            "Then: send as house-owned citizen/desk addresses; list house IMAP. "
            "Never Jon's personal Gmail."
        ),
        tools=("email_send", "email_list"),
        class_="channel",
        sovereignty_note=(
            "Per-citizen From aliases on house domains (soverynintelligence.com / "
            "carolinawatergardens.com). Not production by default — needs "
            "SOVERYN_SMTP_* plus SOVERYN_EMAIL_PRODUCTION=1 after DNS/SPF/DKIM. "
            "Never silent cloud mail SaaS (not AgentMail). Write egress stays Gate-approved."
        ),
    ),
    "signal": ConnectorDef(
        id="signal",
        title="Signal",
        description="Direct Line to Jon via the Signal bridge.",
        tools=("signal_send", "signal_status"),  # names may alias real tools
        class_="channel",
        sovereignty_note="Human report channel to Jon — not corporate call-home.",
    ),
    "messenger": ConnectorDef(
        id="messenger",
        title="Messenger",
        description="Local messenger surface for house notifications.",
        tools=("messenger_send",),
        class_="channel",
        sovereignty_note="House-local messenger bridge.",
    ),
    "x": ConnectorDef(
        id="x",
        title="X / Twitter",
        description="Read/post presence on X when the house X stack is armed.",
        tools=("x_post", "x_feed"),
        class_="optional_egress",
        sovereignty_note="Opt-in presence; not a control plane.",
    ),
    "files": ConnectorDef(
        id="files",
        title="Files",
        description="Read/list/write within granted paths and desks.",
        tools=("read_file", "list_directory", "write_file"),
        class_="house",
        sovereignty_note="Local disks only; stewards of house data.",
    ),
    "documents": ConnectorDef(
        id="documents",
        title="Documents",
        description="Author and manage deliverable documents in the house store.",
        tools=("document_create", "document_list", "document_read"),
        class_="house",
        sovereignty_note="House document store.",
    ),
    "system": ConnectorDef(
        id="system",
        title="System probe",
        description="Read-only live host inventory (GPU/CPU/mem) on allowlisted probes.",
        tools=("system_probe", "spark_status"),
        class_="house",
        sovereignty_note="Fixed command allowlist; no arbitrary shell.",
    ),
    "delegation": ConnectorDef(
        id="delegation",
        title="Delegation",
        description="Hand bounded implementation work to Scotty.",
        tools=("delegate_task", "query_delegation"),
        class_="house",
        sovereignty_note="In-house handoff rail COS uses for repair work.",
    ),
    "house_post": ConnectorDef(
        id="house_post",
        title="House Post",
        description="Inter-citizen mail and COS directives.",
        tools=("house_post_send", "house_post_list"),
        class_="house",
        sovereignty_note="House-local only; desks/inbox copies.",
    ),
    "git": ConnectorDef(
        id="git",
        title="Git (read)",
        description="Read-only git status/log/diff for verification.",
        tools=("git_status", "git_log", "git_diff"),
        class_="house",
        sovereignty_note="Read-only; no push from this connector.",
    ),
    "patrol": ConnectorDef(
        id="patrol",
        title="Patrol sources",
        description="Vett's recurring source-list patrol bookkeeping.",
        tools=("read_patrol_sources", "mark_source_visited"),
        class_="house",
        sovereignty_note="House patrol state + web via web connector.",
    ),
    "pondwright": ConnectorDef(
        id="pondwright",
        title="PondWright pricing",
        description=(
            "House Apex Distribution catalog (MAP/MSRP/WS), AKT Specialty dealer "
            "catalog, and estimator rate book for CWG quotes — not the public web."
        ),
        tools=(
            "apex_catalog_search",
            "akt_catalog_search",
            "pondwright_pricing_book",
        ),
        class_="house",
        sovereignty_note=(
            "Separate pickable catalogs: Apex (xlsx) and AKT Specialty. "
            "Wholesale stays house-only."
        ),
    ),



    "code": ConnectorDef(
        id="code",
        title="Local code exec",
        description="Bounded local repair: run commands/tests inside sandbox.",
        tools=("run_command", "run_pytest", "git_commit"),
        class_="house",
        sovereignty_note="Sandbox/jail; Scotty's mechanical surface.",
    ),
    "social": ConnectorDef(
        id="social",
        title="Social (draft-and-drop)",
        description=(
            "Compose Instagram/Facebook post drafts. In Messages, Gate Allow "
            "sends the pack to Signal for manual publishing."
        ),
        tools=("compose_post",),
        class_="channel",
        sovereignty_note=(
            "Interactive compose_post is Gate-approved (Allow → Signal). "
            "Scheduled Eve cadence may auto-drop. No Meta API."
        ),
    ),
}


# Founding grants — who may hold which connector (Jon’s grants).
# Status "armed" still depends on runtime config (SMTP, signal bridge, …).
FOUNDING_GRANTS: dict[str, tuple[str, ...]] = {
    "aetheria": (
        "web", "email", "signal", "messenger", "x", "files", "documents",
        "system", "delegation", "house_post", "pondwright",
    ),
    "vett": (
        "web", "email", "files", "documents", "system", "house_post",
        "git", "patrol", "pondwright",
    ),
    "scotty": (
        "files", "system", "house_post", "code", "email",
    ),
    "eve": (
        "social", "signal", "files", "documents", "house_post", "email",
    ),
    "kernel": (
        "files", "documents", "system", "house_post", "code", "git", "email",
    ),
}


@dataclass
class ConnectorStatus:
    id: str
    title: str
    description: str
    class_: str
    sovereignty_note: str
    tools: list[str]
    granted: bool
    armed: bool
    reason: str = ""
    email_from: str = ""
    email_aliases: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["class"] = d.pop("class_")
        if not d.get("email_from") and not d.get("email_aliases"):
            d.pop("email_from", None)
            d.pop("email_aliases", None)
        return d


# Read-only web via house SearXNG — always ungated. Research (Vett, chat,
# commissions) must not hang on a Gate click. Write egress stays gated.
WEB_AUTO_APPROVE_TOOLS: frozenset[str] = frozenset({
    "web_search",
    "fetch_url",
})

# House-local PondWright pricing — always ungated (no egress).
PONDWRIGHT_AUTO_APPROVE_TOOLS: frozenset[str] = frozenset({
    "apex_catalog_search",
    "akt_catalog_search",
    "pondwright_pricing_book",
})



# Read-only tools that scheduled/manual automations may use without blocking
# on the Approval Gate. Writes (email_send, x_post, messenger_send, …) stay
# gated even for source=automation — fail-safe egress still needs a yes.
AUTOMATION_AUTO_APPROVE_TOOLS: frozenset[str] = frozenset({
    "web_search",
    "fetch_url",
    "x_feed",
    "email_list",
    # Eve Mon/Thu cadence must not hang overnight waiting for Gate.
    "compose_post",
})


def requires_approval(tool_name: str, *, source: str | None = None) -> bool:
    """True when a tool call must pass the Approval Gate before egress.

    Gates every tool in the ``optional_egress`` sovereignty class plus the
    human-facing channels (email/messenger) — the set Jon locked in.
    ``signal_send`` is ungated: Signal is Jon's direct line to himself, so it
    bypasses the Approval Gate (he is already the approver).

    ``compose_post`` is gated for interactive Messages (Allow → Signal pack).
    Scheduled automations may auto-approve it via AUTOMATION_AUTO_APPROVE_TOOLS.

    ``web_search`` / ``fetch_url`` are always ungated (house SearXNG reads).
    When ``source="automation"``, additional tools in
    ``AUTOMATION_AUTO_APPROVE_TOOLS`` also bypass. Write egress stays gated.

    Fail-safe: unknown tools return False (house-local, never egress).
    """
    if tool_name in WEB_AUTO_APPROVE_TOOLS:
        return False
    if tool_name in PONDWRIGHT_AUTO_APPROVE_TOOLS:
        return False
    if source == "automation" and tool_name in AUTOMATION_AUTO_APPROVE_TOOLS:
        return False

    for defn in CATALOG.values():
        if defn.class_ != "optional_egress":
            continue
        if tool_name in defn.tools:
            return True
    # human-facing channels: outbound to the world — gated
    if tool_name in ("email_send", "messenger_send", "compose_post"):
        return True
    return False


def email_config() -> dict[str, str | None]:
    """Read house email config from env. Empty host ⇒ unarmed."""
    return {
        "smtp_host": os.environ.get("SOVERYN_SMTP_HOST") or os.environ.get("SMTP_HOST"),
        "smtp_port": os.environ.get("SOVERYN_SMTP_PORT") or os.environ.get("SMTP_PORT") or "587",
        "smtp_user": os.environ.get("SOVERYN_SMTP_USER") or os.environ.get("SMTP_USER"),
        "smtp_pass": os.environ.get("SOVERYN_SMTP_PASS") or os.environ.get("SMTP_PASS"),
        "smtp_from": os.environ.get("SOVERYN_SMTP_FROM") or os.environ.get("SMTP_FROM"),
        "imap_host": os.environ.get("SOVERYN_IMAP_HOST") or os.environ.get("IMAP_HOST"),
        "imap_port": os.environ.get("SOVERYN_IMAP_PORT") or os.environ.get("IMAP_PORT") or "993",
        "imap_user": os.environ.get("SOVERYN_IMAP_USER") or os.environ.get("IMAP_USER"),
        "imap_pass": os.environ.get("SOVERYN_IMAP_PASS") or os.environ.get("IMAP_PASS"),
    }


def email_production_enabled() -> bool:
    """Explicit production latch — SMTP alone must not ship citizen mail."""
    return os.environ.get("SOVERYN_EMAIL_PRODUCTION", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def email_armed() -> tuple[bool, str]:
    """Send is armed only when SMTP is configured *and* production is latched.

    Designed identities exist in code; live egress stays off until DNS aliases,
    SPF/DKIM, SMTP, and ``SOVERYN_EMAIL_PRODUCTION=1`` are all intentional.
    """
    cfg = email_config()
    if not cfg["smtp_host"] or not cfg["smtp_from"]:
        return False, "not production — SMTP unset (needs SOVERYN_SMTP_HOST/FROM + SOVERYN_EMAIL_PRODUCTION=1)"
    if not email_production_enabled():
        return False, (
            "not production — SMTP present but SOVERYN_EMAIL_PRODUCTION unset "
            "(set to 1 only after aliases + SPF/DKIM smoke)"
        )
    return True, "SMTP configured (production latch on)"


def email_list_armed() -> tuple[bool, str]:
    """Inbox list follows the same not-production latch as send."""
    cfg = email_config()
    if not email_production_enabled():
        return False, "not production — SOVERYN_EMAIL_PRODUCTION unset"
    if not cfg["imap_host"]:
        return False, "set SOVERYN_IMAP_HOST (and user/pass) to arm inbox list"
    return True, "IMAP configured (production latch on)"


def web_armed() -> tuple[bool, str]:
    # House SearXNG default; treat as armed if URL set (service may be down —
    # tools return errors then).
    url = os.environ.get("SOVERYN_SEARXNG_URL", "http://127.0.0.1:8095/")
    if not url:
        return False, "SOVERYN_SEARXNG_URL empty"
    return True, f"SearXNG at {url}"


def signal_armed() -> tuple[bool, str]:
    # Bridge is a systemd unit; presence of env or unit is enough for "granted path"
    if os.environ.get("SOVERYN_SIGNAL_DISABLED", "").lower() in ("1", "true", "yes"):
        return False, "SOVERYN_SIGNAL_DISABLED"
    return True, "signal bridge unit (house)"


def connector_armed(connector_id: str) -> tuple[bool, str]:
    if connector_id == "web":
        return web_armed()
    if connector_id == "email":
        return email_armed()
    if connector_id == "signal":
        return signal_armed()
    if connector_id == "messenger":
        return True, "messenger tools registered when bridge is up"
    if connector_id == "x":
        if os.environ.get("SOVERYN_X_DISABLED", "").lower() in ("1", "true", "yes"):
            return False, "X disabled"
        return True, "X stack when services armed"
    if connector_id == "social":
        # Draft-and-drop: armed when signal bridge is up (delivery channel)
        return signal_armed()
    # house connectors always "armed" as local
    if connector_id in (
        "files", "documents", "system", "delegation", "house_post", "git",
        "patrol", "code",
    ):
        return True, "house-local"
    return False, "unknown connector"


def for_citizen(citizen_id: str) -> list[ConnectorStatus]:
    from soveryn.platform.email.identities import allowed_from_addresses, identity_for

    grants = set(FOUNDING_GRANTS.get(citizen_id, ()))
    out: list[ConnectorStatus] = []
    for cid, defn in CATALOG.items():
        granted = cid in grants
        armed, reason = connector_armed(cid) if granted else (False, "not granted")
        if granted and not armed:
            reason = reason or "granted but not configured"
        email_from = ""
        email_aliases: list[str] = []
        if cid == "email" and granted:
            ident = identity_for(citizen_id) or {}
            email_from = str(ident.get("default") or "")
            email_aliases = allowed_from_addresses(citizen_id)
        out.append(
            ConnectorStatus(
                id=defn.id,
                title=defn.title,
                description=defn.description,
                class_=defn.class_,
                sovereignty_note=defn.sovereignty_note,
                tools=list(defn.tools),
                granted=granted,
                armed=bool(granted and armed),
                reason=reason if granted else "not granted to this citizen",
                email_from=email_from,
                email_aliases=email_aliases,
            )
        )
    return out


def board_payload() -> dict[str, Any]:
    from soveryn.platform.email.identities import board_identities

    by_citizen = {
        cid: [c.as_dict() for c in for_citizen(cid) if c.granted]
        for cid in FOUNDING_GRANTS
    }
    email_ok, email_why = email_armed()
    list_ok, list_why = email_list_armed()
    web_ok, web_why = web_armed()
    return {
        "catalog": [
            {
                "id": d.id,
                "title": d.title,
                "description": d.description,
                "class": d.class_,
                "sovereignty_note": d.sovereignty_note,
                "tools": list(d.tools),
            }
            for d in CATALOG.values()
        ],
        "by_citizen": by_citizen,
        "email_identities": board_identities(),
        "house": {
            "email_send_armed": email_ok,
            "email_send_note": email_why,
            "email_list_armed": list_ok,
            "email_list_note": list_why,
            "email_production": email_production_enabled(),
            "email_not_production": not email_ok,
            "web_armed": web_ok,
            "web_note": web_why,
        },
        "reading": (
            "Connectors are grants + configuration. Armed means the house can "
            "actually invoke the channel. Citizen email is NOT PRODUCTION until "
            "DNS aliases + SPF/DKIM + SOVERYN_SMTP_* + SOVERYN_EMAIL_PRODUCTION=1. "
            "Email From is a house citizen identity — never Jon's personal Gmail."
        ),
    }
