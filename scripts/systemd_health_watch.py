#!/usr/bin/env python3
"""SOVERYN systemd health watch — deterministic crash-loop detector.

Scans user units (soveryn-*.service, tgthr*.service) for failure signals:
  - ActiveState failed / activating (stuck start-pre)
  - NRestarts >= threshold (default 10)

Healthy  -> writes an EMPTY watch file (stable hash, monitor skips the LLM).
Problems -> writes a deterministic report; any change wakes the
            `service_crash_watch` automation, which briefs Jon in Messages.

No volatile fields (timestamps) in the output: an unchanged problem does NOT
re-page; a changed or cleared problem pages exactly once.

Output: data/automations/watches/systemd_health.txt (relative to data root)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SOVERYN_DATA_ROOT", REPO_ROOT / "data"))
WATCH_REL = Path("automations/watches/systemd_health.txt")
RESTART_THRESHOLD = 10
UNIT_GLOBS = ["soveryn-*.service", "tgthr*.service"]


def list_units() -> list[str]:
    out = subprocess.run(
        ["systemctl", "--user", "list-units", "--all", "--no-legend", "--no-pager"]
        + UNIT_GLOBS,
        capture_output=True,
        text=True,
        timeout=20,
    )
    units = []
    for line in out.stdout.splitlines():
        # Failed units carry a "●"/"*" prefix; grab the .service token itself.
        for token in line.split():
            if token.endswith(".service"):
                units.append(token)
                break
    return sorted(set(units))


def unit_props(unit: str) -> dict[str, str]:
    out = subprocess.run(
        [
            "systemctl", "--user", "show", unit,
            "-p", "ActiveState", "-p", "SubState",
            "-p", "NRestarts", "-p", "Result",
        ],
        capture_output=True,
        text=True,
        timeout=20,
    )
    props: dict[str, str] = {}
    for line in out.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            props[k] = v
    return props


def problems_for(unit: str, props: dict[str, str]) -> list[str]:
    found = []
    state = props.get("ActiveState", "unknown")
    if state in ("failed", "activating"):
        found.append(
            f"{unit}: state={state} sub={props.get('SubState', '?')} "
            f"result={props.get('Result', '?')} restarts={props.get('NRestarts', '?')}"
        )
    try:
        if int(props.get("NRestarts", "0")) >= RESTART_THRESHOLD:
            found.append(
                f"{unit}: restart counter {props.get('NRestarts')} >= {RESTART_THRESHOLD} "
                f"(state={state})"
            )
    except ValueError:
        pass
    return found


def main() -> int:
    lines: list[str] = []
    for unit in list_units():
        try:
            props = unit_props(unit)
        except subprocess.TimeoutExpired:
            lines.append(f"{unit}: systemctl show timed out")
            continue
        lines.extend(problems_for(unit, props))

    out_path = DATA_ROOT / WATCH_REL
    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(lines)
    # Trailing newline only when there is content; empty file stays empty so
    # the healthy-state hash is stable.
    out_path.write_text(body + "\n" if body else "", encoding="utf-8")

    if body:
        print(f"PROBLEMS ({len(lines)}):")
        print(body)
    else:
        print("healthy: no failed / crash-looping user units")
    return 0


if __name__ == "__main__":
    sys.exit(main())
