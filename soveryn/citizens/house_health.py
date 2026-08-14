"""House health — one JSON for "is the house up?" (charter-aligned).

Inspired by product health surfaces that name the *runtime path* (e.g. Rakazo's
`runtime` / `sandbox` / `wakeup`), but Soveryn-shaped:

  * residents come from census *evidence*, never self-declared green
  * workers are process residences (systemd units), optional live probe
  * connectors are grants + armed state, not a plugin marketplace
  * commissions queue is the work spine
  * vocabulary pins peer vs subagent so the board does not invent third kinds

GET /api/citizens/health assembles this. Pure functions here stay unit-testable
without Flask.
"""

from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from soveryn.citizens.census import CITIZENS as CENSUS_FOUNDING
from soveryn.citizens.census import DESK_DIRS
from soveryn.citizens.connectors import board_payload as connectors_board

# ── vocabulary (Rakazo steal #3, house language) ────────────────────────────

VOCABULARY = {
    "peer": {
        "name": "peer",
        "means": (
            "A founding or standing citizen with soul, desk, and residence. "
            "Survives the turn. Counted on the roster and in the census."
        ),
        "examples": ["aetheria", "vett", "scotty"],
    },
    "subagent": {
        "name": "subagent",
        "means": (
            "Ephemeral deputy for one job (usually under Aetheria's spawn). "
            "No soul, no desk, no standing. Dies with the session or job. "
            "Never reported as resident."
        ),
        "examples": ["spawn_specialist visitors on the Citizens board"],
    },
    "commission": {
        "name": "commission",
        "means": (
            "Discrete work queued for a peer. Drain claims one at a time per "
            "citizen; result lands in that citizen's outbox/."
        ),
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _unit_active(
    unit: str,
    *,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """systemctl is-active — present / absent / unknown (no systemd)."""
    try:
        r = runner(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=3,
        )
        state = (r.stdout or "").strip() or (r.stderr or "").strip()
        active = state == "active"
        return {
            "unit": unit,
            "state": state or "unknown",
            "active": active,
            "probed": True,
        }
    except FileNotFoundError:
        return {
            "unit": unit,
            "state": "no_systemctl",
            "active": None,
            "probed": False,
            "note": "systemctl not available on this host",
        }
    except Exception as exc:
        return {
            "unit": unit,
            "state": "error",
            "active": None,
            "probed": True,
            "note": str(exc)[:200],
        }


def desk_status(workspace_path: str | None) -> dict[str, Any]:
    """Whether a citizen's desk (charter §4) exists with the four drawers."""
    if not workspace_path:
        return {"ok": False, "path": None, "missing": list(DESK_DIRS), "note": "no workspace"}
    root = Path(workspace_path)
    missing = [d for d in DESK_DIRS if not (root / d).is_dir()]
    return {
        "ok": root.is_dir() and not missing,
        "path": str(root),
        "missing": missing,
    }


def commission_counts(conn: sqlite3.Connection) -> dict[str, int]:
    try:
        rows = conn.execute(
            "SELECT state, COUNT(*) AS n FROM commissions GROUP BY state"
        ).fetchall()
    except sqlite3.Error:
        return {"queued": 0, "running": 0, "done": 0, "failed": 0}
    out = {"queued": 0, "running": 0, "done": 0, "failed": 0}
    for r in rows:
        key = r["state"] if isinstance(r, sqlite3.Row) else r[0]
        n = r["n"] if isinstance(r, sqlite3.Row) else r[1]
        if key in out:
            out[key] = int(n)
    return out


def workers_from_census(
    *,
    probe: bool = True,
    runner: Callable[..., Any] = subprocess.run,
) -> dict[str, Any]:
    """Process residences declared in census.CITIZENS."""
    workers: dict[str, Any] = {}
    for citizen, units in CENSUS_FOUNDING:
        entry: dict[str, Any] = {
            "citizen_id": citizen.id,
            "display_name": citizen.display_name,
            "units": list(units),
            "residence": "process" if units else "none",
        }
        if not units:
            entry["note"] = (
                "No process unit to probe — on-demand or inference-only "
                "standing is Jon's call, not silent offline."
            )
            entry["active"] = None
            entry["probes"] = []
        elif probe:
            probes = [_unit_active(u, runner=runner) for u in units]
            entry["probes"] = probes
            # Resident process: any founding unit active counts present.
            actives = [p["active"] for p in probes if p.get("active") is not None]
            entry["active"] = any(actives) if actives else None
        else:
            entry["probes"] = [{"unit": u, "probed": False} for u in units]
            entry["active"] = None
            entry["note"] = "probe=0 — units listed only"
        workers[citizen.id] = entry
    return workers


def assemble_house_health(
    *,
    db_path: Path | None,
    agent_loops: list[str] | None = None,
    version: str = "0.0.0",
    spawned: dict[str, Any] | None = None,
    probe_workers: bool = True,
    runner: Callable[..., Any] = subprocess.run,
    now: str | None = None,
) -> dict[str, Any]:
    """Build the house health document.

    Never raises for missing registry — reports sections with notes instead.
    """
    as_of = now or _utc_now()
    loops = sorted(agent_loops or [])
    spawned = spawned or {
        "host_citizen": "aetheria",
        "kind": "specialist",
        "specialists": [],
        "count": 0,
    }

    residents: dict[str, Any] = {
        "citizens": [],
        "counts": {},
        "reading": "derived from last census + commission state; not re-probed here",
    }
    commissions: dict[str, Any] = {
        "queued": 0,
        "running": 0,
        "done": 0,
        "failed": 0,
        "note": None,
    }
    desks: dict[str, Any] = {}
    registry_ok = False
    registry_note = None

    if db_path is None or not Path(db_path).exists():
        registry_note = "no registry yet — run the census"
    else:
        try:
            conn = sqlite3.connect(
                f"file:{Path(db_path).resolve()}?mode=ro",
                uri=True,
                timeout=5.0,
            )
            conn.row_factory = sqlite3.Row
            try:
                from soveryn.citizens.registry import board_citizens

                rows = board_citizens(conn)
                residents["citizens"] = [
                    {
                        "id": r["id"],
                        "display_name": r.get("display_name"),
                        "status": r["status"],
                        "last_seen_at": r.get("last_seen_at"),
                        "model_server": r.get("model_server"),
                        "workspace_path": r.get("workspace_path"),
                    }
                    for r in rows
                ]
                for state in (
                    "resident",
                    "on_duty",
                    "blocked",
                    "offline",
                    "unobserved",
                    "retired",
                ):
                    residents["counts"][state] = sum(
                        1 for r in rows if r["status"] == state
                    )
                commissions.update(commission_counts(conn))
                for r in rows:
                    desks[r["id"]] = desk_status(r.get("workspace_path"))
                registry_ok = True
            finally:
                conn.close()
        except sqlite3.Error as exc:
            registry_note = f"registry unreadable: {exc}"

    # Desks from founding map if registry empty
    if not desks:
        for citizen, _units in CENSUS_FOUNDING:
            desks[citizen.id] = desk_status(citizen.workspace_path)

    workers = workers_from_census(probe=probe_workers, runner=runner)

    try:
        connectors = connectors_board()
    except Exception as exc:
        connectors = {"error": str(exc), "citizens": {}, "catalog": []}

    # House "ok" is conservative: loops up + registry readable + no hard worker
    # probe saying every unit failed when units exist. Unobserved is not fail.
    worker_failures = []
    for cid, w in workers.items():
        if w.get("residence") == "process" and w.get("active") is False:
            worker_failures.append(cid)

    problems: list[str] = []
    if not loops:
        problems.append("no_agent_loops")
    if registry_note:
        problems.append("registry:" + registry_note.split("—")[0].strip()[:40])
    if worker_failures:
        problems.append("workers_inactive:" + ",".join(worker_failures))
    if commissions.get("running", 0) > 3:
        problems.append("commissions_running_high")

    ok = len(problems) == 0 and (registry_ok or registry_note is None)

    return {
        "app": "soveryn",
        "surface": "house",
        "ok": ok and registry_ok,
        "as_of": as_of,
        "problems": problems,
        "reading": (
            "House health: loops + registry status + optional unit probes + "
            "connectors + desks. Residence remains evidence-derived."
        ),
        "runtime": {
            "kind": "soveryn_vnext",
            "version": version,
            "agent_loops": loops,
            "loops_ready": bool(loops),
            "wakeup": "scotty_worker_and_duties",
            "sandbox": "desk_workspace",  # not Docker-per-bot; charter desks
        },
        "residents": residents,
        "registry": {
            "ok": registry_ok,
            "path": str(db_path) if db_path else None,
            "note": registry_note,
        },
        "workers": workers,
        "commissions": commissions,
        "connectors": connectors,
        "desks": desks,
        "spawned": spawned,
        "vocabulary": VOCABULARY,
    }
