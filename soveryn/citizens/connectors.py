"""Connectors — what a citizen is allowed to touch outside (or across) the house.

Tools already exist (web_search, fetch_url, signal, messenger, …). What was
missing was a **grant map**: which citizen holds which channel, whether it is
actually configured, and what sovereignty rule applies.

Connectors are *capabilities*, not cloud SaaS agent plugins. Default: house
network. Email is optional and only arms when Jon sets SMTP/IMAP env. Web goes
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
        class_="optional_egress",
        sovereignty_note="Content only through house SearXNG; no vendor bot C2.",
    ),
    "email": ConnectorDef(
        id="email",
        title="Email",
        description="Send and list mail when SMTP/IMAP is configured for the house.",
        tools=("email_send", "email_list"),
        class_="channel",
        sovereignty_note="Arms only with house SMTP/IMAP env — never silent cloud mail SaaS.",
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
    "code": ConnectorDef(
        id="code",
        title="Local code exec",
        description="Bounded local repair: run commands/tests inside sandbox.",
        tools=("run_command", "run_pytest", "git_commit"),
        class_="house",
        sovereignty_note="Sandbox/jail; Scotty's mechanical surface.",
    ),
}


# Founding grants — who may hold which connector (Jon’s grants).
# Status "armed" still depends on runtime config (SMTP, signal bridge, …).
FOUNDING_GRANTS: dict[str, tuple[str, ...]] = {
    "aetheria": (
        "web", "email", "signal", "messenger", "x", "files", "documents",
        "system", "delegation", "house_post",
    ),
    "vett": (
        "web", "email", "files", "documents", "system", "house_post",
        "git", "patrol",
    ),
    "scotty": (
        "files", "system", "house_post", "code",
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

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["class"] = d.pop("class_")
        return d


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


def email_armed() -> tuple[bool, str]:
    cfg = email_config()
    if not cfg["smtp_host"] or not cfg["smtp_from"]:
        return False, "set SOVERYN_SMTP_HOST and SOVERYN_SMTP_FROM to arm send"
    return True, "SMTP configured"
    # list can still be unarmed without IMAP — handled in tool


def email_list_armed() -> tuple[bool, str]:
    cfg = email_config()
    if not cfg["imap_host"]:
        return False, "set SOVERYN_IMAP_HOST (and user/pass) to arm inbox list"
    return True, "IMAP configured"


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
    # house connectors always "armed" as local
    if connector_id in (
        "files", "documents", "system", "delegation", "house_post", "git",
        "patrol", "code",
    ):
        return True, "house-local"
    return False, "unknown connector"


def for_citizen(citizen_id: str) -> list[ConnectorStatus]:
    grants = set(FOUNDING_GRANTS.get(citizen_id, ()))
    out: list[ConnectorStatus] = []
    for cid, defn in CATALOG.items():
        granted = cid in grants
        armed, reason = connector_armed(cid) if granted else (False, "not granted")
        if granted and not armed:
            reason = reason or "granted but not configured"
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
            )
        )
    # only show granted by default for board compactness? show all with flags
    return out


def board_payload() -> dict[str, Any]:
    by_citizen = {
        cid: [c.as_dict() for c in for_citizen(cid) if c.granted]
        for cid in FOUNDING_GRANTS
    }
    email_ok, email_why = email_armed()
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
        "house": {
            "email_send_armed": email_ok,
            "email_send_note": email_why,
            "email_list_armed": email_list_armed()[0],
            "email_list_note": email_list_armed()[1],
            "web_armed": web_ok,
            "web_note": web_why,
        },
        "reading": (
            "Connectors are grants + configuration. Armed means the house can "
            "actually invoke the channel; granted-but-unarmed needs env (e.g. SMTP)."
        ),
    }
