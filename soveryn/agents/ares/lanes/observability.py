"""Ares observability lane — readers pointed at channels nobody writes to.

2026-07-30: the Comms Bus panel had shown nothing for 18 days. Nothing was broken
and no data was lost — it read `edges WHERE relationship LIKE 'direct%'`, a
channel that produced NINE rows in two months, while 537 real agent-to-agent
events flowed through coord_event_log and delegation. Delegation had shipped as
its own subsystem and nobody asked what was still reading the old channel.

This is a DIFFERENT failure from the one tests/test_shared_context_wiring_contract.py
catches. That contract finds wiring never done. This finds wiring gone stale — a
reader faithfully querying a road nobody drives on. Same root cause, different
detector, because stale wiring looks exactly like a quiet week until you compare
it against everything else.

Severity is WARNING on purpose. Per router.route_finding, WARNING reaches the bus
(inbox + mission control) and returns BEFORE signal_sink — so a dry channel is
visible without paging Jon at 3am. A dry channel is a QUESTION, not an outage.

Detection only. Every probe fails safe: a bad query or a missing database returns
[] rather than crashing the daemon.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.agents.ares.findings import AresFinding, Severity

#: Days of silence before a channel is worth asking about. Set from the incident
#: that motivated this: the Comms Bus went unnoticed for 18 days, so 30 is a
#: threshold that would have caught it with room to spare while staying quiet
#: about genuinely slow channels.
DEFAULT_MAX_AGE_DAYS = 30.0

#: Canonical channel registry. `scripts/stale_readers.py` imports this rather
#: than keeping its own copy — a duplicated list would drift out of sync, which
#: is the exact bug class this lane exists to catch.
#:
#: `allow_empty` marks channels where "no rows" is the HEALTHY state. An empty
#: review queue means nothing is waiting on Jon. Nagging about a healthy
#: condition is how you train someone to ignore a tool, which is how the audit
#: tool's prose caveat came to be read and overridden on 2026-07-27.
#:
#: Tower-local stores only. The Pondwright CRM and Seneca's audit log live on the
#: Spark and have their own glance panels; reporting a remote service as
#: "database missing" every scan would be pure noise.
CHANNELS: tuple[dict[str, Any], ...] = (
    {"reader": "Comms Bus · legacy direct edges", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM edges WHERE relationship LIKE 'direct%'"},
    {"reader": "Comms Bus · board handoffs", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM coord_event_log "
            "WHERE triggered_agents IS NOT NULL AND triggered_agents != ''"},
    {"reader": "Comms Bus · delegation dispatches", "db": "delegation",
     "sql": "SELECT MAX(created_at) FROM delegation_tasks"},
    {"reader": "Scotty approvals · /api/delegation/pending", "db": "delegation",
     "sql": "SELECT MAX(updated_at) FROM delegation_tasks WHERE status='in_review'",
     "allow_empty": True},
    {"reader": "Coord boards · /api/coord/summary", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM coord_event_log"},
    {"reader": "Library writes · /api/memory/activity", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM nodes"},
    {"reader": "Cognition · reflections", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM nodes WHERE type='reflection'"},
    {"reader": "Dreams", "db": "lattice",
     "sql": "SELECT MAX(created_at) FROM edges "
            "WHERE relationship='dream_association'"},
    {"reader": "X presence · staged posts", "db": "x_staged",
     "sql": "SELECT MAX(proposed_at) FROM staged_posts"},
    {"reader": "Cross-rail active context", "db": "active_context",
     "sql": "SELECT MAX(updated_at) FROM active_context"},
)


def resolve_dbs() -> dict[str, Path]:
    """Map the registry's db keys to real paths. Fails safe to {}."""
    try:
        from soveryn.config.loader import load_env_config
        env = load_env_config()
        root = env.data_root
        return {
            "lattice": env.lattice_db,
            "conversations": env.conversations_db,
            "delegation": root / "delegation.db",
            "x_staged": root / "x_staged.db",
            "active_context": root / "active_context.db",
        }
    except Exception:
        return {}


def last_activity(db_path: Path, sql: str) -> tuple[str | None, str | None]:
    """Return (timestamp, error). Read-only; never raises."""
    try:
        if not Path(db_path).is_file():
            return None, "database missing"
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            row = con.execute(sql).fetchone()
        return (row[0] if row else None), None
    except sqlite3.Error as exc:
        return None, str(exc)
    except Exception as exc:  # noqa: BLE001 — a probe must never kill the daemon
        return None, str(exc)


def age_days(ts: str, now: datetime) -> float | None:
    """Age in days, tolerating the mixed tz-awareness of these stores.

    delegation.db writes naive local `datetime.now()`; the context store writes
    UTC with a Z. Subtracting one from the other raises, and did on 2026-07-28
    the first time this ran against real data instead of fixtures.
    """
    try:
        then = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if then.tzinfo is None:
        then = then.astimezone()
    if now.tzinfo is None:
        now = now.astimezone()
    return (now - then).total_seconds() / 86400


def survey_channels(
    *,
    # None, not CHANNELS: a default argument binds at import time, which freezes
    # the registry and makes it impossible to override in a test or at runtime.
    channels: tuple[dict[str, Any], ...] | None = None,
    dbs: dict[str, Path] | None = None,
    now: datetime | None = None,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
) -> list[dict[str, Any]]:
    """Survey every channel. Pure data — the shared core for lane and CLI."""
    now = now or datetime.now()
    channels = CHANNELS if channels is None else channels
    dbs = resolve_dbs() if dbs is None else dbs
    out: list[dict[str, Any]] = []
    for ch in channels:
        path = dbs.get(ch["db"])
        if path is None:
            ts, err = None, f"unknown db key {ch['db']!r}"
        else:
            ts, err = last_activity(path, ch["sql"])
        days = age_days(ts, now) if ts else None
        stale = bool(err) or (
            days is None and not ch.get("allow_empty")
        ) or (days is not None and days > max_age_days)
        out.append({
            "reader": ch["reader"], "db": ch["db"], "last_activity": ts,
            "age_days": round(days, 1) if days is not None else None,
            "error": err, "stale": stale,
            "allow_empty": bool(ch.get("allow_empty")),
        })
    return out


def collect_stale_readers_live(*, now: datetime | None = None) -> list[AresFinding]:
    """Ares collector. Still zero-arg callable, so it satisfies the Collector
    contract; `now` is injectable purely so tests are deterministic — asserting
    an age against the wall clock is a flaky test, learned three times over.

    One finding per dry channel, keyed by reader so it dedupes across scans and
    clears itself when traffic resumes.
    """
    try:
        rows = survey_channels(now=now)
    except Exception:  # noqa: BLE001
        return []
    findings: list[AresFinding] = []
    for r in rows:
        if not r["stale"]:
            continue
        findings.append(AresFinding(
            finding_type="observability.stale_reader",
            severity=Severity.WARNING,
            key=r["reader"],
            evidence={
                "reader": r["reader"],
                "database": r["db"],
                "last_activity": r["last_activity"],
                "age_days": r["age_days"],
                "error": r["error"],
                "note": (
                    "This reader's channel has produced nothing recently. Either "
                    "nobody writes there any more and the reader should be "
                    "repointed, or it has genuinely been quiet. The Comms Bus sat "
                    "18 days on the wrong answer to this question."
                ),
            },
        ))
    return findings
