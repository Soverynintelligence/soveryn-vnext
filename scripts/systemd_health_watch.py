#!/usr/bin/env python3
"""SOVERYN systemd health watch — deterministic crash-loop detector.

Scans user units (soveryn-*.service, tgthr*.service) for failure signals:
  - ActiveState failed
  - ActiveState activating for longer than STUCK_ACTIVATING_SECONDS (stuck start)
  - NRestarts >= threshold (default 10)

`activating` is NOT a break by itself: Type=oneshot units (including this watch,
which scans itself mid-run) are legitimately `activating` while they work. That
false positive flapped the watch file every cycle until 2026-10-23.

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
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.environ.get("SOVERYN_DATA_ROOT", REPO_ROOT / "data"))
WATCH_REL = Path("automations/watches/systemd_health.txt")
RESTART_THRESHOLD = 10
UNIT_GLOBS = ["soveryn-*.service", "tgthr*.service"]

# A `Type=oneshot` unit is *always* ActiveState=activating while it runs, and
# the crash-watch scans itself while it is still starting. Reporting that as a
# problem made the watch file flap every 15 min (2026-10-23: 3 -> 5 -> 3 -> 4
# problems across consecutive cycles) and re-page Jon with a false alarm.
# `activating` only counts as a break when it has outlived a stuck-start budget.
STUCK_ACTIVATING_SECONDS = 600


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
            "-p", "Type", "-p", "ActiveEnterTimestampMonotonic",
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


def activating_seconds(props: dict[str, str], now_monotonic_us: int) -> int:
    """Seconds spent in `activating`, or 0 when the timestamp is unusable."""
    raw = props.get("ActiveEnterTimestampMonotonic", "")
    try:
        entered_us = int(raw)
    except (TypeError, ValueError):
        return 0
    if entered_us <= 0:
        return 0
    return max(0, (now_monotonic_us - entered_us) // 1_000_000)


def problems_for(
    unit: str,
    props: dict[str, str],
    now_monotonic_us: int | None = None,
) -> list[str]:
    found = []
    state = props.get("ActiveState", "unknown")
    if state == "failed":
        found.append(
            f"{unit}: state={state} sub={props.get('SubState', '?')} "
            f"result={props.get('Result', '?')} restarts={props.get('NRestarts', '?')}"
        )
    elif state == "activating":
        # oneshot units (and the watch itself) are legitimately `activating`
        # while they run. Only a stuck start is a break.
        elapsed = activating_seconds(
            props,
            now_monotonic_us if now_monotonic_us is not None
            else time.monotonic_ns() // 1000,
        )
        if elapsed >= STUCK_ACTIVATING_SECONDS:
            found.append(
                f"{unit}: state={state} sub={props.get('SubState', '?')} "
                f"stuck {elapsed}s (>= {STUCK_ACTIVATING_SECONDS}s) "
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
