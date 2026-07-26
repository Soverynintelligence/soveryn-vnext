"""Router auto-recovery watchdog.

Root cause it guards against (2026-07-04 incident): the llama-server router
(:8090) does NOT respawn a backend that crashed mid-inference. It keeps
proxying every request to the dead port forever, so one CUDA fault turned into
a 13-hour silent outage. This watchdog passively scans the router's own
journal for that dead-slot signature and restarts the router to clear it.

Passive by design: it never pings models (an active probe would force the
router to load every model, including MiniMax-M3 which can't load — the check
would itself cause outages). It only reads what real traffic already logged.

The decision logic (`parse_dead_models`, `decide_restart`, `in_cooldown`) is
pure and unit-tested; `run_once` is the thin journalctl/systemctl shell.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime

# The router lazily serves these; a crashed one leaves a dead slot. Scoped to
# the preset sections so a can't-load model (MiniMax-M3) never triggers a
# restart loop.
DEFAULT_GUARDED = {"aetheria", "vett-scotty", "cognition", "embeddings", "reflection"}

ROUTER_UNIT = "soveryn-router.service"
STATE_DIR = os.path.expanduser("~/soveryn_vnext/data/watchdog")
COOLDOWN_FILE = os.path.join(STATE_DIR, "last_restart")
LOG_FILE = os.path.join(STATE_DIR, "watchdog.jsonl")

# Journal lookback per tick. MUST exceed the slowest thing that knocks on a dead
# slot, or the watchdog cannot reach THRESHOLD and never fires.
# 2026-07-26: this was "2 min ago" and caused a 26-hour silent outage. Aetheria's
# backend died and the ONLY caller was the heartbeat, which knocks every 1800s —
# so each 2-minute window saw exactly ONE error, never the two THRESHOLD wants.
# The watchdog logged dead:[] action:"none" on every tick for two days while she
# was unreachable. It worked as designed under chat traffic (errors arrive fast)
# and was blind precisely when the box was quiet, which is when nobody notices.
# 40 min > 2 heartbeat intervals, so two consecutive misses now land together.
WINDOW_SECONDS = 2400.0
THRESHOLD = 2          # dead-slot errors for one model before we act
COOLDOWN_S = 300.0     # min seconds between restarts (anti-flap)

_PROXY_RE = re.compile(r"proxying request to model (\S+) on port")
# ONLY "Could not establish connection" — a TCP-connect failure, which means
# the child's port is truly dead. Deliberately NOT "Failed to read connection":
# that can fire on a healthy-but-BUSY parallel=1 child (router read-timeout
# during a long generation), and mistaking busy for dead is exactly the
# false-positive cascade that got the old active-probe watchdog killed
# (2026-06-11, 9 restarts/hour force-killing Aetheria mid-response).
_ERR_RE = re.compile(r"Could not establish connection")


# ── pure decision logic (unit-tested) ──────────────────────────────────────
def parse_dead_models(journal_text: str, guarded: set[str]) -> dict[str, int]:
    """Count dead-slot connection errors per guarded model.

    A connection error is attributed to the most recent `proxying to model X`
    line — the dead-slot error fires in the same millisecond as its proxy
    attempt, so last-seen model is a reliable attribution. Models outside
    `guarded` are ignored.
    """
    counts: dict[str, int] = {}
    last_model: str | None = None
    for line in journal_text.splitlines():
        m = _PROXY_RE.search(line)
        if m:
            last_model = m.group(1)
            continue
        if _ERR_RE.search(line) and last_model is not None and last_model in guarded:
            counts[last_model] = counts.get(last_model, 0) + 1
    return counts


def decide_restart(dead_counts: dict[str, int], threshold: int) -> list[str]:
    """Models whose error count meets the threshold — sorted for determinism."""
    return sorted(m for m, c in dead_counts.items() if c >= threshold)


def journal_since(now: float, last_restart_ts: float | None, window_s: float) -> float:
    """Start of the lookback window.

    Never reaches back past the last restart. Without this floor, widening the
    window would re-count the errors that CAUSED the previous restart and fire
    again the moment cooldown lapsed — a restart loop. After a restart the slate
    is genuinely clean, so only errors newer than it are evidence.
    """
    floor = now - window_s
    if last_restart_ts is not None and last_restart_ts > floor:
        return last_restart_ts
    return floor


def in_cooldown(last_restart_ts: float | None, now: float, cooldown_s: float) -> bool:
    """True if a restart happened within the last `cooldown_s` seconds."""
    if last_restart_ts is None:
        return False
    return (now - last_restart_ts) < cooldown_s


# ── I/O shell ───────────────────────────────────────────────────────────────
def _read_journal(since_ts: float) -> str:
    since = datetime.fromtimestamp(since_ts).strftime("%Y-%m-%d %H:%M:%S")
    try:
        out = subprocess.run(
            ["journalctl", "--user", "-u", ROUTER_UNIT, "--no-pager", "--since", since],
            capture_output=True, text=True, timeout=20,
        )
        return out.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _read_last_restart() -> float | None:
    try:
        with open(COOLDOWN_FILE) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_last_restart(ts: float) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(COOLDOWN_FILE, "w") as f:
        f.write(str(ts))


def _restart_router() -> None:
    subprocess.run(
        ["systemctl", "--user", "restart", ROUTER_UNIT], timeout=90, check=True,
    )


def _log(record: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


def run_once(now: float | None = None, guarded: set[str] | None = None) -> dict:
    """One watchdog tick: scan → decide → (maybe) restart → log."""
    now = time.time() if now is None else now
    guarded = DEFAULT_GUARDED if guarded is None else guarded

    last_restart = _read_last_restart()
    since_ts = journal_since(now, last_restart, WINDOW_SECONDS)
    counts = parse_dead_models(_read_journal(since_ts), guarded)
    dead = decide_restart(counts, THRESHOLD)
    cooling = in_cooldown(last_restart, now, COOLDOWN_S)

    action = "none"
    if dead and not cooling:
        _restart_router()
        _write_last_restart(now)
        action = "restarted"
    elif dead and cooling:
        action = "suppressed_cooldown"

    _log({"ts": now, "dead": dead, "counts": counts, "action": action})
    return {"dead": dead, "action": action, "counts": counts}
