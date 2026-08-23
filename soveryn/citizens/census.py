"""Take the census: create desks, seed the registry, and go and look.

This is the half of the Citizens layer that touches the real house. The registry
holds declarations and evidence; this module produces the evidence, by asking
systemd whether each Citizen's process residence is actually alive.

Residence has two halves (charter §3): where a Citizen *thinks* (a model
endpoint) and where its *process* lives (a unit on a machine). Only the second
can be observed from here, and only for Citizens whose process lives on this
machine. Everything else stays `unobserved` — which is a state, not a failure.

Scotty is the case that keeps this honest: he is invoked on demand and has no
unit at all. There is nothing to probe, so he is never observed, so he is never
reported resident. That is the correct outcome, and it is why §3 of the charter
now flags his standing as Jon's call rather than assuming it.

Usage:  python -m soveryn.citizens.census [--db PATH] [--workspaces ROOT]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from soveryn.citizens.registry import (
    Citizen,
    OBSERVED_ABSENT,
    OBSERVED_PRESENT,
    connect,
    list_citizens,
    observe,
    register,
)
from soveryn.config.runtime import MODEL_SERVERS

DEFAULT_DB = Path("data/citizens.db")
DEFAULT_WORKSPACES = Path.home() / "soveryn_citizens"
DESK_DIRS = ("inbox", "outbox", "work", "notes")


def _alias_of(server_name: str) -> str:
    """Current model alias for a ModelServer, so notes can't go stale.

    Added 2026-08-20. Vett's note read "Inference on Spark :8001 (qwen36-35b)"
    for eight days after the brain moved to Lightning — a hand-typed model name
    beside a switch (`resolve_vett_brain`) that had already changed. Same class
    as `qwen-serve.service` still being called qwen-serve: the label is not the
    model. Derive it, and it can never drift again.
    """
    for server in MODEL_SERVERS:
        if server.name == server_name:
            return server.model_alias or server_name
    return server_name

# Charter §3, corrected 2026-08-13. `units` is the PROCESS residence on this
# machine — the only thing this module can actually verify. An empty tuple means
# "nothing here to probe", not "broken".
CITIZENS: tuple[tuple[Citizen, tuple[str, ...]], ...] = (
    (
        Citizen(
            id="aetheria",
            display_name="Aetheria",
            soul_path="data/memory/souls/aetheria.md",
            model_server="aetheria_primary",
            workspace_path=str(DEFAULT_WORKSPACES / "aetheria"),
            notes=(
                "Chief of Staff of the house. Blackwell :8090, alone — never "
                "co-tenanted (charter §8). Routes House Post, assigns commissions "
                "to Vett/Scotty, holds the partnership surface with Jon."
            ),
        ),
        ("soveryn-heartbeat.service", "soveryn-dream.service",
         "soveryn-cognition-cycle.service", "soveryn-signal-bridge.service"),
    ),
    (
        Citizen(
            id="vett",
            display_name="V.E.T.T.",
            soul_path="data/memory/souls/vett.md",
            model_server="vett_scotty_shared",
            workspace_path=str(DEFAULT_WORKSPACES / "vett"),
            notes=(
                f"Inference on Spark :8001 ({_alias_of('vett_scotty_shared')}); "
                "patrols from the tower."
            ),
        ),
        ("soveryn-vett-patrol.service",),
    ),
    (
        Citizen(
            id="scotty",
            display_name="Scotty",
            soul_path="data/memory/souls/scotty.md",
            model_server="vett_scotty_shared",
            workspace_path=str(DEFAULT_WORKSPACES / "scotty"),
            notes=(
                "Repair / execution desk. Inference on Spark :8001 (shared with "
                "Vett). Process residence: soveryn-scotty-worker on the tower — "
                "drains commissions and keeps the desk warm."
            ),
        ),
        ("soveryn-scotty-worker.service",),
    ),
    (
        Citizen(
            id="eve",
            display_name="Eve",
            soul_path="data/memory/souls/eve.md",
            model_server="kernel_build",
            workspace_path=str(DEFAULT_WORKSPACES / "eve"),
            notes=(
                "Head of Marketing for the house. Inference on Quadros :8091 "
                "(shared with Kernel). Draft-and-drop marketing for SOVERYN, "
                "ActTruth, and Carolina Water Gardens — no Meta API, no "
                "credentials, Signal drop only."
            ),
        ),
        (),
    ),
    (
        Citizen(
            id="kernel",
            display_name="Kernel",
            soul_path="data/memory/souls/kernel.md",
            model_server="kernel_build",
            workspace_path=str(DEFAULT_WORKSPACES / "kernel"),
            notes=(
                "Build / code desk. Inference on Quadros :8091 "
                f"({_alias_of('kernel_build')}); shared with Eve. "
                "Jon assigns build work here — not Scotty's repair queue."
            ),
        ),
        (),  # no dedicated process unit on the tower yet — invoked on demand
    ),
)


def make_desk(root: Path, citizen_id: str) -> Path:
    """A desk on disk (charter §4). Idempotent — re-running disturbs nothing."""
    desk = root / citizen_id
    for sub in DESK_DIRS:
        (desk / sub).mkdir(parents=True, exist_ok=True)
    return desk


def _unit_is_active(unit: str, runner=subprocess.run) -> bool:
    """systemctl is-active, read literally.

    Anything other than a clean `active` is not active. `is-active` is a poor
    detector of a *stale* process — a unit up for days can be running code from
    an older deploy — so this answers only "is something running under that
    unit", which is exactly what residence claims.
    """
    try:
        done = runner(["systemctl", "--user", "is-active", unit],
                      capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    return done.stdout.strip() == "active"


def take_census(conn, *, workspaces: Path = DEFAULT_WORKSPACES,
                unit_check=_unit_is_active, now: str | None = None) -> list[dict]:
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for citizen, units in CITIZENS:
        make_desk(workspaces, citizen.id)
        register(conn, citizen)

        if not units:
            # Nothing to look at. Recording an `absent` here would assert a
            # failed process where there is no process at all.
            continue

        alive = [u for u in units if unit_check(u)]
        observe(
            conn,
            citizen.id,
            OBSERVED_PRESENT if alive else OBSERVED_ABSENT,
            at=stamp,
            detail=(", ".join(alive) if alive
                    else "no unit active: " + ", ".join(units)),
        )

    # Phase 3: register standing duties so the board can name them. Does not
    # rewire systemd — register first, rewire later (project §7).
    from soveryn.citizens.duties import seed_founding
    seed_founding(conn)

    from soveryn.citizens.registry import board_citizens
    return board_citizens(conn)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Take the SOVERYN Citizens census.")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--workspaces", default=str(DEFAULT_WORKSPACES))
    args = ap.parse_args(argv)

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    with connect(args.db) as conn:
        rows = take_census(conn, workspaces=Path(args.workspaces))

    width = max(len(r["id"]) for r in rows)
    for r in rows:
        obs = r["last_observation"]
        detail = f"  {obs['detail']}" if obs and obs.get("detail") else ""
        print(f"  {r['id']:<{width}}  {r['status']:<11}"
              f"{('last seen ' + r['last_seen_at']) if r['last_seen_at'] else '':<32}{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
