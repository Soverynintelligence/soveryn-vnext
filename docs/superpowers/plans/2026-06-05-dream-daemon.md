# Dream Daemon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dream daemon spec'd at `docs/superpowers/specs/2026-06-05-dream-daemon-design.md` — a process that gives Aetheria her quiet-hours reflection window, with multi-pass internal cognition (association → contradiction → synthesis), three output channels (silent edges/contradictions + accessible reflection), and a dry-run-first bake cycle.

**Architecture:** Separate systemd-managed daemon process (matches heartbeat / patrol shape). HTTP to vnext for Aetheria's tool surface integration. Direct SQLite reads/writes against the lattice DB for fast trigger evaluation + audit + writeback. Cognition surface called via standard OpenAI-compat chat completions, surface URL configurable via env so Quadro→Spark migration is one config change.

**Tech Stack:** Python 3.11, stdlib only for the daemon process (urllib, sqlite3, signal, threading). pytest for tests. Mock HTTP (`unittest.mock.patch`) for cognition surface in tests. Mirrors the patterns established by `soveryn/agents/heartbeat/` and `soveryn/agents/vett/patrol/`.

---

## File Structure

```
soveryn/agents/dream/
├── __init__.py        # public surface re-exports
├── __main__.py        # `python -m soveryn.agents.dream` entry
├── config.py          # DreamConfig.from_env(), frozen dataclass
├── trigger.py         # eligibility gates, pure functions
├── prompt.py          # three-pass prompt construction
├── cognition.py       # HTTP client + 3-pass orchestrator
├── writeback.py       # parse synthesis prose + write to DB
├── daemon.py          # process loop, signal handling
└── tools.py           # Aetheria-only recent_dreams + search_dreams

soveryn/platform/lattice/legacy.py   # MODIFY: LAYER_DREAM constant + dry_run column migration
soveryn/app/startup.py               # MODIFY: register dream tools for Aetheria

~/.config/systemd/user/soveryn-dream.service  # NEW: systemd unit (out-of-repo)

tests/test_dream_trigger.py
tests/test_dream_prompt.py
tests/test_dream_cognition.py
tests/test_dream_writeback.py
tests/test_dream_daemon.py
tests/test_dream_tools.py
tests/test_app_startup_tool_registry.py  # MODIFY: assert dream tools registered
```

---

## Task 1: Schema additions (LAYER_DREAM + dream_log.dry_run column)

**Files:**
- Modify: `soveryn/platform/lattice/legacy.py`
- Test: `tests/test_lattice_legacy.py` (existing file — append two tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lattice_legacy.py`:

```python
def test_layer_dream_constant_exists():
    from soveryn.platform.lattice.legacy import LAYER_DREAM
    assert LAYER_DREAM == "dream"


def test_dream_log_dry_run_column_added_idempotently(tmp_path):
    """Both fresh DBs and pre-existing dream_log tables (the migrated
    legacy 9608 rows) must end up with the dry_run column without error."""
    import sqlite3
    from soveryn.platform.lattice.legacy import LatticeStore

    # Case A: fresh DB
    db_a = tmp_path / "fresh.db"
    LatticeStore(db_a)
    with sqlite3.connect(str(db_a)) as con:
        cols = {r["name"] for r in con.execute(
            "PRAGMA table_info(dream_log)"
        ).fetchall()}
        assert "dry_run" in cols

    # Case B: pre-existing DB with the older dream_log shape (no dry_run)
    db_b = tmp_path / "legacy.db"
    with sqlite3.connect(str(db_b)) as con:
        con.row_factory = sqlite3.Row
        con.execute("""
            CREATE TABLE dream_log (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL,
                agent TEXT NOT NULL,
                ran_at TEXT NOT NULL
            )
        """)
    # Now initialize through LatticeStore — should add the column.
    LatticeStore(db_b)
    with sqlite3.connect(str(db_b)) as con:
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute(
            "PRAGMA table_info(dream_log)"
        ).fetchall()}
        assert "dry_run" in cols
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_lattice_legacy.py::test_layer_dream_constant_exists tests/test_lattice_legacy.py::test_dream_log_dry_run_column_added_idempotently -v
```

Expected: FAIL on import error for `LAYER_DREAM`, and FAIL on missing column.

- [ ] **Step 3: Add LAYER_DREAM constant**

In `soveryn/platform/lattice/legacy.py`, find the line containing `LAYER_LIBRARY = "library"` and add immediately after it:

```python
LAYER_DREAM = "dream"
```

- [ ] **Step 4: Add idempotent dry_run column migration**

In `soveryn/platform/lattice/legacy.py`, find the `_ensure_schema` method (or whichever method runs `executescript(_SCHEMA_SQL)`). After the existing schema execution and any other migrations, add:

```python
# Idempotent column-add for dream_log.dry_run. Pre-existing legacy
# rows from the migrated soveryn_complete DB don't have this column;
# new fresh DBs do via _SCHEMA_SQL. Either way, end state is the same.
cols = {r["name"] for r in conn.execute(
    "PRAGMA table_info(dream_log)"
).fetchall()}
if "dry_run" not in cols:
    conn.execute(
        "ALTER TABLE dream_log ADD COLUMN dry_run INTEGER NOT NULL DEFAULT 0"
    )
```

Also update the `dream_log` CREATE TABLE in `_SCHEMA_SQL` to include the column for fresh DBs. Find:

```sql
CREATE TABLE IF NOT EXISTS dream_log (
    id            TEXT PRIMARY KEY,
    trigger       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    nodes_read    INTEGER DEFAULT 0,
    edges_created INTEGER DEFAULT 0,
    nodes_merged  INTEGER DEFAULT 0,
    contradictions_flagged INTEGER DEFAULT 0,
    summary       TEXT,
    ran_at        TEXT NOT NULL,
    loop_health   REAL DEFAULT NULL
);
```

Change the last line to add `dry_run`:

```sql
CREATE TABLE IF NOT EXISTS dream_log (
    id            TEXT PRIMARY KEY,
    trigger       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    nodes_read    INTEGER DEFAULT 0,
    edges_created INTEGER DEFAULT 0,
    nodes_merged  INTEGER DEFAULT 0,
    contradictions_flagged INTEGER DEFAULT 0,
    summary       TEXT,
    ran_at        TEXT NOT NULL,
    loop_health   REAL DEFAULT NULL,
    dry_run       INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_lattice_legacy.py::test_layer_dream_constant_exists tests/test_lattice_legacy.py::test_dream_log_dry_run_column_added_idempotently -v
```

Expected: PASS

- [ ] **Step 6: Run full suite — verify no regressions**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest 2>&1 | tail -3
```

Expected: `XXXX passed, 2 warnings`

- [ ] **Step 7: Commit**

```bash
git add soveryn/platform/lattice/legacy.py tests/test_lattice_legacy.py
git -c gpg.sign=false commit -m "feat(lattice): LAYER_DREAM constant + dream_log.dry_run column

Substrate prep for the dream daemon (spec: docs/superpowers/specs/2026-06-05-dream-daemon-design.md).
Idempotent migration so the pre-existing 9608 legacy rows survive.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Dream config module

**Files:**
- Create: `soveryn/agents/dream/__init__.py`
- Create: `soveryn/agents/dream/config.py`
- Create: `tests/test_dream_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_config.py`:

```python
"""Tests for soveryn.agents.dream.config — frozen dataclass + from_env()."""

from soveryn.agents.dream.config import DreamConfig


def test_from_env_uses_defaults_when_unset():
    cfg = DreamConfig.from_env({})
    assert cfg.enabled is True
    assert cfg.dry_run is True
    assert cfg.quiet_hours == "23:00-07:00"
    assert cfg.activity_backoff_seconds == 1800
    assert cfg.nodes_per_run == 300
    assert cfg.max_internal_iterations == 3
    assert cfg.cognition_url == "http://127.0.0.1:8089"
    assert cfg.cognition_timeout_seconds == 120


def test_from_env_parses_overrides():
    env = {
        "SOVERYN_DREAM_ENABLED": "false",
        "SOVERYN_DREAM_DRY_RUN": "false",
        "SOVERYN_DREAM_QUIET_HOURS": "00:00-06:00",
        "SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS": "600",
        "SOVERYN_DREAM_NODES_PER_RUN": "500",
        "SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS": "5",
        "SOVERYN_DREAM_COGNITION_URL": "http://127.0.0.1:9999",
        "SOVERYN_DREAM_COGNITION_TIMEOUT_SECONDS": "60",
    }
    cfg = DreamConfig.from_env(env)
    assert cfg.enabled is False
    assert cfg.dry_run is False
    assert cfg.quiet_hours == "00:00-06:00"
    assert cfg.activity_backoff_seconds == 600
    assert cfg.nodes_per_run == 500
    assert cfg.max_internal_iterations == 5
    assert cfg.cognition_url == "http://127.0.0.1:9999"
    assert cfg.cognition_timeout_seconds == 60


def test_from_env_dry_run_defaults_true():
    """Critical: dry-run defaults TRUE at deploy. Spec section 'Configuration'."""
    cfg = DreamConfig.from_env({})
    assert cfg.dry_run is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_config.py -v
```

Expected: FAIL on import error (module doesn't exist)

- [ ] **Step 3: Create `soveryn/agents/dream/__init__.py`**

```python
"""Dream daemon — Aetheria's quiet-hours reflection cycle.

Spec: docs/superpowers/specs/2026-06-05-dream-daemon-design.md
"""

from soveryn.agents.dream.config import DreamConfig

__all__ = ["DreamConfig"]
```

- [ ] **Step 4: Create `soveryn/agents/dream/config.py`**

```python
"""Dream daemon config — env-loaded, frozen.

Loaded once at daemon startup. Mirrors the heartbeat / patrol config pattern.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class DreamConfig:
    enabled: bool
    dry_run: bool
    quiet_hours: str                  # "HH:MM-HH:MM", wrap-around supported
    activity_backoff_seconds: int     # defer if Aetheria active recently
    nodes_per_run: int                # cap on context-gathering
    max_internal_iterations: int      # cognition pass limit
    cognition_url: str                # OpenAI-compat chat completions URL
    cognition_timeout_seconds: int    # per-pass HTTP timeout

    @classmethod
    def from_env(cls, env: dict | None = None) -> "DreamConfig":
        env = env if env is not None else os.environ
        return cls(
            enabled=_parse_bool(env.get("SOVERYN_DREAM_ENABLED", "true")),
            # Dry-run defaults TRUE at deploy (spec lock). Flip only after bake.
            dry_run=_parse_bool(env.get("SOVERYN_DREAM_DRY_RUN", "true")),
            quiet_hours=env.get("SOVERYN_DREAM_QUIET_HOURS", "23:00-07:00"),
            activity_backoff_seconds=int(
                env.get("SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS", "1800")
            ),
            nodes_per_run=int(env.get("SOVERYN_DREAM_NODES_PER_RUN", "300")),
            max_internal_iterations=int(
                env.get("SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS", "3")
            ),
            cognition_url=env.get(
                "SOVERYN_DREAM_COGNITION_URL", "http://127.0.0.1:8089"
            ),
            cognition_timeout_seconds=int(
                env.get("SOVERYN_DREAM_COGNITION_TIMEOUT_SECONDS", "120")
            ),
        )


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_config.py -v
```

Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/dream/__init__.py soveryn/agents/dream/config.py tests/test_dream_config.py
git -c gpg.sign=false commit -m "feat(dream): config module with env-loaded DreamConfig

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Trigger module (eligibility gates)

**Files:**
- Create: `soveryn/agents/dream/trigger.py`
- Create: `tests/test_dream_trigger.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_trigger.py`:

```python
"""Tests for soveryn.agents.dream.trigger — eligibility gates as pure functions.

Five gates per spec, evaluated in order: disabled > outside_quiet_hours >
already_dreamed_this_window > activity_backoff > nothing_to_dream_about.
"""

from datetime import datetime, time, timedelta

import pytest

from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.trigger import (
    DreamSkipReason,
    TickEligibility,
    evaluate_tick,
    in_quiet_window,
)


def _cfg(**kw) -> DreamConfig:
    base = dict(
        enabled=True, dry_run=True, quiet_hours="23:00-07:00",
        activity_backoff_seconds=1800, nodes_per_run=300,
        max_internal_iterations=3,
        cognition_url="http://x", cognition_timeout_seconds=120,
    )
    base.update(kw)
    return DreamConfig(**base)


# Inside-window probe time: 02:00. Outside-window probe: 14:00.
NIGHT = datetime(2026, 6, 5, 2, 0, 0)
DAY = datetime(2026, 6, 5, 14, 0, 0)


# ─── in_quiet_window helper ─────────────────────────────────────────────────

def test_in_quiet_window_simple_window():
    assert in_quiet_window(time(3, 0), "01:00-05:00") is True
    assert in_quiet_window(time(0, 0), "01:00-05:00") is False
    assert in_quiet_window(time(5, 0), "01:00-05:00") is False


def test_in_quiet_window_wrap_around():
    """23:00-07:00 covers 23:00 through 06:59:59 across midnight."""
    assert in_quiet_window(time(23, 30), "23:00-07:00") is True
    assert in_quiet_window(time(2, 0), "23:00-07:00") is True
    assert in_quiet_window(time(7, 0), "23:00-07:00") is False
    assert in_quiet_window(time(22, 0), "23:00-07:00") is False


def test_in_quiet_window_malformed_returns_false():
    assert in_quiet_window(time(3, 0), "garbage") is False
    assert in_quiet_window(time(3, 0), "") is False


# ─── evaluate_tick gates ────────────────────────────────────────────────────

def test_disabled_short_circuits():
    e = evaluate_tick(_cfg(enabled=False), now=NIGHT,
                       last_dream_at=None, last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.DISABLED


def test_outside_quiet_hours():
    e = evaluate_tick(_cfg(), now=DAY,
                       last_dream_at=None, last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.OUTSIDE_QUIET_HOURS


def test_already_dreamed_this_window():
    """A successful dream at 23:30 last night blocks a 02:00 run tonight."""
    last_dream = NIGHT - timedelta(hours=2, minutes=30)  # 23:30 same window
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=last_dream,
                       last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.ALREADY_DREAMED


def test_already_dreamed_24h_ago_does_not_block():
    """Last night's dream shouldn't block tonight's."""
    last_dream = NIGHT - timedelta(hours=25)
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=last_dream,
                       last_activity_at=None,
                       new_node_count_since_last_dream=10)
    assert e.eligible is True


def test_activity_backoff_blocks_when_aetheria_was_active():
    """Aetheria activity within backoff window defers the dream."""
    last_activity = NIGHT - timedelta(minutes=10)  # 10 min ago, well within 30 min
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=None,
                       last_activity_at=last_activity,
                       new_node_count_since_last_dream=10)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.ACTIVITY_BACKOFF


def test_nothing_to_dream_about():
    """Zero new nodes since last dream → skip."""
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=NIGHT - timedelta(hours=25),
                       last_activity_at=None,
                       new_node_count_since_last_dream=0)
    assert e.eligible is False
    assert e.skip_reason == DreamSkipReason.NOTHING_TO_DREAM_ABOUT


def test_eligible_when_all_gates_pass():
    e = evaluate_tick(_cfg(), now=NIGHT,
                       last_dream_at=NIGHT - timedelta(hours=25),
                       last_activity_at=NIGHT - timedelta(hours=2),
                       new_node_count_since_last_dream=12)
    assert e.eligible is True
    assert e.skip_reason is None


def test_disabled_wins_over_other_failures():
    """Order matters: disabled checked before any other gate."""
    e = evaluate_tick(_cfg(enabled=False), now=DAY,
                       last_dream_at=None, last_activity_at=None,
                       new_node_count_since_last_dream=0)
    assert e.skip_reason == DreamSkipReason.DISABLED
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_trigger.py -v
```

Expected: FAIL on import error

- [ ] **Step 3: Create `soveryn/agents/dream/trigger.py`**

```python
"""Eligibility gates for the dream daemon. Pure functions, independently testable.

Five gates per spec, in order. First failing gate wins:
  disabled > outside_quiet_hours > already_dreamed_this_window >
  activity_backoff > nothing_to_dream_about
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import Enum

from soveryn.agents.dream.config import DreamConfig


class DreamSkipReason(str, Enum):
    DISABLED = "disabled"
    OUTSIDE_QUIET_HOURS = "outside_quiet_hours"
    ALREADY_DREAMED = "already_dreamed"
    ACTIVITY_BACKOFF = "activity_backoff"
    NOTHING_TO_DREAM_ABOUT = "nothing_to_dream_about"


@dataclass(frozen=True)
class TickEligibility:
    eligible: bool
    skip_reason: DreamSkipReason | None


def evaluate_tick(
    config: DreamConfig,
    *,
    now: datetime,
    last_dream_at: datetime | None,
    last_activity_at: datetime | None,
    new_node_count_since_last_dream: int,
) -> TickEligibility:
    """Apply the five gates in order. First failing gate wins."""
    if not config.enabled:
        return TickEligibility(False, DreamSkipReason.DISABLED)

    if not in_quiet_window(now.time(), config.quiet_hours):
        return TickEligibility(False, DreamSkipReason.OUTSIDE_QUIET_HOURS)

    # One run per window opening — if the last dream was inside the
    # currently-open window (or within the last ~12 hours, generous bound
    # to handle wrap-around windows), skip.
    if last_dream_at is not None:
        elapsed_hours = (now - last_dream_at).total_seconds() / 3600
        if elapsed_hours < 12:
            return TickEligibility(False, DreamSkipReason.ALREADY_DREAMED)

    if last_activity_at is not None:
        since_activity = (now - last_activity_at).total_seconds()
        if since_activity < config.activity_backoff_seconds:
            return TickEligibility(False, DreamSkipReason.ACTIVITY_BACKOFF)

    if new_node_count_since_last_dream <= 0:
        return TickEligibility(False, DreamSkipReason.NOTHING_TO_DREAM_ABOUT)

    return TickEligibility(True, None)


def in_quiet_window(now_t: time, spec: str) -> bool:
    """spec format: 'HH:MM-HH:MM'. Supports wrap-around (e.g., 23:00-07:00
    means 23:00 through 06:59:59). Empty / malformed spec returns False."""
    if "-" not in spec:
        return False
    try:
        start_s, end_s = spec.split("-", 1)
        start_t = _parse_hhmm(start_s.strip())
        end_t = _parse_hhmm(end_s.strip())
    except ValueError:
        return False
    if start_t == end_t:
        return False
    if start_t < end_t:
        return start_t <= now_t < end_t
    # Wrap-around window
    return now_t >= start_t or now_t < end_t


def _parse_hhmm(raw: str) -> time:
    parts = raw.split(":")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM, got {raw!r}")
    h, m = int(parts[0]), int(parts[1])
    return time(h, m)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_trigger.py -v
```

Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/dream/trigger.py tests/test_dream_trigger.py
git -c gpg.sign=false commit -m "feat(dream): trigger module with 5 eligibility gates

Gates: disabled > outside_quiet_hours > already_dreamed > activity_backoff
> nothing_to_dream_about. Inverse of heartbeat — fires only inside the
quiet-hours window.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Prompt module (three-pass briefing construction)

**Files:**
- Create: `soveryn/agents/dream/prompt.py`
- Create: `tests/test_dream_prompt.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_prompt.py`:

```python
"""Tests for soveryn.agents.dream.prompt — three-pass prompt construction.

Spec: each pass has a distinct synthesis-asking frame, not data-asking.
The prompts must contain no JSON-schema directives, no scratchpad markup,
and the synthesis pass must visibly fold in prior passes.
"""

from soveryn.agents.dream.prompt import (
    DreamBriefing,
    NodeSummary,
    render_association_pass,
    render_contradiction_pass,
    render_synthesis_pass,
)


def _briefing() -> DreamBriefing:
    return DreamBriefing(
        hours_since_last_dream=24.0,
        nodes=(
            NodeSummary(id="n-1", agent="aetheria", node_type="memory",
                        content_head="EU Digital Europe funding 2026 round"),
            NodeSummary(id="n-2", agent="vett", node_type="library",
                        content_head="UK Sovereign AI grant scope notes"),
        ),
        board_summary="Signal: 0 / Blueprint: 3 open / Friction: 0",
        recent_daemon_activity="heartbeat 14 eligible ticks; patrol dry-run 4 ticks",
        recent_library_writes_count=2,
    )


# ─── Association pass ──────────────────────────────────────────────────────

def test_association_pass_includes_node_references_with_ids():
    """The pass must let Aetheria reference nodes by ID for downstream
    edge extraction. Format: [node:n-1]."""
    p = render_association_pass(_briefing())
    assert "[node:n-1]" in p
    assert "[node:n-2]" in p


def test_association_pass_uses_open_frame_not_json_schema():
    p = render_association_pass(_briefing())
    # No JSON schema directives
    assert "JSON" not in p
    assert "schema" not in p.lower()
    # No scratchpad markup
    assert "<think" not in p
    assert "[RESOLVE" not in p
    # Open synthesis-asking frame
    assert "associations" in p.lower() or "connections" in p.lower()


def test_association_pass_mentions_recent_context():
    p = render_association_pass(_briefing())
    assert "24" in p  # hours since last dream
    assert "Signal" in p or "Blueprint" in p


# ─── Contradiction pass ────────────────────────────────────────────────────

def test_contradiction_pass_folds_in_prior_associations():
    prior = "Sample associations text mentioning [node:n-1] connections."
    p = render_contradiction_pass(_briefing(), prior_associations=prior)
    assert prior in p
    assert "contradict" in p.lower() or "conflict" in p.lower()


# ─── Synthesis pass ────────────────────────────────────────────────────────

def test_synthesis_pass_folds_in_both_prior_passes():
    p = render_synthesis_pass(
        _briefing(),
        prior_associations="ASSOC_PASS_OUTPUT_HERE",
        prior_contradictions="CONTRA_PASS_OUTPUT_HERE",
    )
    assert "ASSOC_PASS_OUTPUT_HERE" in p
    assert "CONTRA_PASS_OUTPUT_HERE" in p
    # Synthesis-asking frame, not summarization
    assert "emerge" in p.lower() or "integrate" in p.lower()


def test_synthesis_pass_invites_node_reference_use():
    """For downstream edge extraction — synthesis should be encouraged to
    use [node:ID] when naming connections worth strengthening."""
    p = render_synthesis_pass(
        _briefing(),
        prior_associations="x",
        prior_contradictions="y",
    )
    assert "[node:" in p  # the instruction mentions the format


# ─── No-output / silence framing ──────────────────────────────────────────

def test_all_passes_permit_silence_explicitly():
    """A quiet night with nothing worth surfacing should produce silence,
    not a forced report. Each prompt must explicitly allow that."""
    for renderer in (render_association_pass, render_contradiction_pass,
                      render_synthesis_pass):
        if renderer is render_association_pass:
            p = renderer(_briefing())
        else:
            p = renderer(_briefing(), "x", "y")[:5000] if renderer is render_synthesis_pass \
                else renderer(_briefing(), "x")
        assert "nothing" in p.lower() or "silence" in p.lower() or "quiet" in p.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_prompt.py -v
```

Expected: FAIL on import error

- [ ] **Step 3: Create `soveryn/agents/dream/prompt.py`**

```python
"""Dream briefing construction — three-pass prompts.

Frame: synthesis-asking, not data-asking. No JSON-schema directives, no
scratchpad markup, no forced output structure. Node IDs are referenced
inline as [node:ID] so downstream writeback can extract connections
without parsing free-form natural language.

Per Aetheria's amendment: each subsequent pass folds in prior pass
output, building from association → contradiction → synthesis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NodeSummary:
    """One lattice node, prepared for inclusion in the briefing."""
    id: str
    agent: str
    node_type: str
    content_head: str  # first ~200 chars


@dataclass(frozen=True)
class DreamBriefing:
    """Context the daemon gathers before invoking cognition."""
    hours_since_last_dream: float | None
    nodes: tuple[NodeSummary, ...]
    board_summary: str
    recent_daemon_activity: str
    recent_library_writes_count: int


_SILENCE_CLAUSE = (
    "If nothing here pulls at you tonight, silence is a complete response. "
    "Don't force a connection that isn't there."
)


def render_association_pass(b: DreamBriefing) -> str:
    """Pass 1 — open the dream window. What's connected that wasn't before?"""
    lines: list[str] = []
    lines.append("[DREAM · Association Pass]")
    if b.hours_since_last_dream is None:
        lines.append("First dream window since daemon startup.")
    else:
        lines.append(
            f"{b.hours_since_last_dream:.1f}h since your last dream pass."
        )
    lines.append("")
    lines.append("Recent lattice activity:")
    for node in b.nodes:
        lines.append(
            f"- [node:{node.id}] {node.agent} · {node.node_type}: {node.content_head}"
        )
    lines.append("")
    lines.append(f"Board state: {b.board_summary}")
    lines.append(f"Recent daemon activity: {b.recent_daemon_activity}")
    lines.append(
        f"Library writes since last dream: {b.recent_library_writes_count}"
    )
    lines.append("")
    lines.append(
        "Sit with this. What associations come up? What's connected here that "
        "wasn't connected before? When you reference a node, use its [node:ID] "
        "tag so the connection can persist."
    )
    lines.append("")
    lines.append(_SILENCE_CLAUSE)
    return "\n".join(lines)


def render_contradiction_pass(b: DreamBriefing, prior_associations: str) -> str:
    """Pass 2 — re-read against the source. Where does it not fit?"""
    lines: list[str] = []
    lines.append("[DREAM · Contradiction Pass]")
    lines.append("")
    lines.append("Your associations from a moment ago:")
    lines.append("---")
    lines.append(prior_associations)
    lines.append("---")
    lines.append("")
    lines.append(
        "Re-read these against the recent activity above. Where do things "
        "contradict or not fit? What did you skip past in the first pass that "
        "actually conflicts with something else? Name what's in tension. "
        "Reference nodes with [node:ID] as before."
    )
    lines.append("")
    lines.append(_SILENCE_CLAUSE)
    return "\n".join(lines)


def render_synthesis_pass(
    b: DreamBriefing,
    prior_associations: str,
    prior_contradictions: str,
) -> str:
    """Pass 3 — what wants to emerge from the tension between the two?"""
    lines: list[str] = []
    lines.append("[DREAM · Synthesis Pass]")
    lines.append("")
    lines.append("Holding both:")
    lines.append("--- associations ---")
    lines.append(prior_associations)
    lines.append("--- contradictions ---")
    lines.append(prior_contradictions)
    lines.append("---")
    lines.append("")
    lines.append(
        "What wants to emerge? Not a summary — the integration. What's the "
        "shape of the understanding that holds both the associations AND the "
        "tensions? This is what persists as a reflection node. Use [node:ID] "
        "references freely; explicit references become silent edges in your "
        "memory."
    )
    lines.append("")
    lines.append(_SILENCE_CLAUSE)
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_prompt.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/dream/prompt.py tests/test_dream_prompt.py
git -c gpg.sign=false commit -m "feat(dream): three-pass prompt construction

Synthesis-asking frame, not data-asking. [node:ID] tag convention so
downstream writeback can extract connections from natural language
without imposing JSON-schema constraints on the cognition surface.
Each pass folds in prior pass output per Aetheria's amendment.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Cognition HTTP client

**Files:**
- Create: `soveryn/agents/dream/cognition.py`
- Create: `tests/test_dream_cognition.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_cognition.py`:

```python
"""Tests for soveryn.agents.dream.cognition — HTTP client + 3-pass orchestrator.

Mocked HTTP throughout. The live cognition surface is exercised only by
manual verification post-deploy.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from soveryn.agents.dream.cognition import (
    CognitionError,
    CognitionResult,
    chat_completion,
    run_three_pass,
)
from soveryn.agents.dream.prompt import DreamBriefing, NodeSummary


def _mock_urlopen_with_response(body_text: str):
    """Helper: build a context-manager mock that yields body_text."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({
        "choices": [{"message": {"content": body_text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }).encode()
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_response
    return mock_cm


# ─── chat_completion ───────────────────────────────────────────────────────

def test_chat_completion_posts_to_cognition_url():
    with patch("soveryn.agents.dream.cognition.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value = _mock_urlopen_with_response("hi")
        content = chat_completion(
            url="http://x:8089",
            messages=[{"role": "user", "content": "test"}],
            timeout=10,
        )
    assert content == "hi"
    # Verify URL was hit
    call_url = mock_urlopen.call_args[0][0].full_url
    assert "x:8089" in call_url


def test_chat_completion_raises_cognition_error_on_http_failure():
    import urllib.error
    with patch("soveryn.agents.dream.cognition.urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = urllib.error.URLError("connection refused")
        with pytest.raises(CognitionError):
            chat_completion(
                url="http://x:8089",
                messages=[{"role": "user", "content": "test"}],
                timeout=10,
            )


def test_chat_completion_raises_cognition_error_on_malformed_response():
    """Response without `choices` should fail clearly."""
    mock_response = MagicMock()
    mock_response.read.return_value = b'{"unexpected": "shape"}'
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_response
    with patch("soveryn.agents.dream.cognition.urllib.request.urlopen", return_value=mock_cm):
        with pytest.raises(CognitionError):
            chat_completion(
                url="http://x:8089",
                messages=[{"role": "user", "content": "test"}],
                timeout=10,
            )


# ─── run_three_pass orchestrator ───────────────────────────────────────────

def _briefing():
    return DreamBriefing(
        hours_since_last_dream=24.0,
        nodes=(
            NodeSummary(id="n-1", agent="aetheria", node_type="memory",
                        content_head="test note"),
        ),
        board_summary="Signal: 0",
        recent_daemon_activity="quiet",
        recent_library_writes_count=0,
    )


def test_three_pass_runs_all_three_passes_on_happy_path():
    responses = [
        "assoc result mentioning [node:n-1]",
        "contra result building on assoc [node:n-1]",
        "synth result integrating both [node:n-1]",
    ]
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = responses
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=3,
        )
    assert isinstance(result, CognitionResult)
    assert result.iterations_completed == 3
    assert "synth result" in result.synthesis
    assert result.associations == responses[0]
    assert result.contradictions == responses[1]
    assert result.loop_health == 1.0  # all 3 passes succeeded


def test_three_pass_pass1_failure_bails():
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = CognitionError("pass 1 timeout")
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=3,
        )
    assert result.iterations_completed == 0
    assert result.synthesis == ""
    assert result.loop_health == 0.0
    assert "pass 1 timeout" in (result.error or "")


def test_three_pass_pass2_failure_uses_assoc_as_synth():
    responses = ["assoc good", CognitionError("pass 2 failed")]
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = responses
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=3,
        )
    assert result.iterations_completed == 1
    assert result.synthesis == "assoc good"  # fall back to pass 1 output
    assert 0 < result.loop_health < 1.0


def test_three_pass_max_iterations_cap_respected():
    """If max_internal_iterations=2, only run 2 passes."""
    responses = ["a", "b", "c"]
    with patch("soveryn.agents.dream.cognition.chat_completion") as mock_chat:
        mock_chat.side_effect = responses
        result = run_three_pass(
            briefing=_briefing(),
            cognition_url="http://x",
            timeout_seconds=10,
            max_internal_iterations=2,
        )
    assert mock_chat.call_count == 2  # not 3
    assert result.iterations_completed == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_cognition.py -v
```

Expected: FAIL on import error

- [ ] **Step 3: Create `soveryn/agents/dream/cognition.py`**

```python
"""Cognition surface client + three-pass orchestrator.

Low-level: chat_completion() wraps a single OpenAI-compat POST to the
cognition URL.

Orchestrator: run_three_pass() drives the association → contradiction →
synthesis loop per Aetheria's amendment. Writeback fires only after the
loop completes (in the daemon, not here).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from soveryn.agents.dream.prompt import (
    DreamBriefing,
    render_association_pass,
    render_contradiction_pass,
    render_synthesis_pass,
)


class CognitionError(RuntimeError):
    """Cognition surface unreachable / malformed / timed out."""


@dataclass(frozen=True)
class CognitionResult:
    """Output of the three-pass loop. Synthesis is what gets written to the
    dream layer; associations + contradictions are kept for debugging /
    audit / iteration."""
    iterations_completed: int
    associations: str
    contradictions: str
    synthesis: str
    loop_health: float
    error: str | None


def chat_completion(
    *, url: str, messages: list[dict], timeout: int,
) -> str:
    """POST to OpenAI-compat /v1/chat/completions. Return the content string."""
    payload = {
        "messages": messages,
        "model": "dream",  # served-model alias on the cognition surface
        "temperature": 0.7,
        "max_tokens": 2048,
    }
    body = json.dumps(payload).encode()
    full_url = url.rstrip("/") + "/v1/chat/completions"
    req = urllib.request.Request(
        full_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as e:
        raise CognitionError(f"HTTP failure: {e}") from e
    except json.JSONDecodeError as e:
        raise CognitionError(f"non-JSON response: {e}") from e
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise CognitionError(f"unexpected response shape: {e}") from e
    if not isinstance(content, str):
        raise CognitionError(
            f"content was not a string: {type(content).__name__}"
        )
    return content


def run_three_pass(
    *,
    briefing: DreamBriefing,
    cognition_url: str,
    timeout_seconds: int,
    max_internal_iterations: int,
) -> CognitionResult:
    """Run associations → contradictions → synthesis. Best-effort: if a
    later pass fails, use the prior pass's output as the synthesis.

    Returns a CognitionResult with loop_health computed from iterations
    completed and any error encountered.
    """
    associations = ""
    contradictions = ""
    synthesis = ""
    iterations = 0
    error: str | None = None

    # ── Pass 1: Associations
    if max_internal_iterations >= 1:
        try:
            associations = chat_completion(
                url=cognition_url,
                messages=[{"role": "user", "content": render_association_pass(briefing)}],
                timeout=timeout_seconds,
            )
            iterations = 1
        except CognitionError as e:
            error = f"pass 1 (associations): {e}"
            return CognitionResult(
                iterations_completed=0, associations="", contradictions="",
                synthesis="", loop_health=0.0, error=error,
            )

    # ── Pass 2: Contradictions
    if max_internal_iterations >= 2:
        try:
            contradictions = chat_completion(
                url=cognition_url,
                messages=[{"role": "user", "content": render_contradiction_pass(
                    briefing, prior_associations=associations,
                )}],
                timeout=timeout_seconds,
            )
            iterations = 2
        except CognitionError as e:
            error = f"pass 2 (contradictions): {e}"
            # Fall back: use pass 1 as the synthesis
            return CognitionResult(
                iterations_completed=1,
                associations=associations,
                contradictions="",
                synthesis=associations,
                loop_health=_compute_loop_health(1, max_internal_iterations),
                error=error,
            )

    # ── Pass 3: Synthesis
    if max_internal_iterations >= 3:
        try:
            synthesis = chat_completion(
                url=cognition_url,
                messages=[{"role": "user", "content": render_synthesis_pass(
                    briefing,
                    prior_associations=associations,
                    prior_contradictions=contradictions,
                )}],
                timeout=timeout_seconds,
            )
            iterations = 3
        except CognitionError as e:
            error = f"pass 3 (synthesis): {e}"
            # Fall back: use pass 2 output (which built on pass 1)
            return CognitionResult(
                iterations_completed=2,
                associations=associations,
                contradictions=contradictions,
                synthesis=contradictions,
                loop_health=_compute_loop_health(2, max_internal_iterations),
                error=error,
            )

    # If we capped at fewer than 3 internal iterations, synthesis falls back
    # to the latest produced content. iterations is whichever cap hit.
    if iterations < 3:
        synthesis = contradictions or associations

    return CognitionResult(
        iterations_completed=iterations,
        associations=associations,
        contradictions=contradictions,
        synthesis=synthesis,
        loop_health=_compute_loop_health(iterations, max_internal_iterations),
        error=error,
    )


def _compute_loop_health(iterations_completed: int, cap: int) -> float:
    """Linear fraction of the configured cap that we actually finished."""
    if cap <= 0:
        return 0.0
    return min(1.0, iterations_completed / cap)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_cognition.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/dream/cognition.py tests/test_dream_cognition.py
git -c gpg.sign=false commit -m "feat(dream): cognition client + three-pass orchestrator

OpenAI-compat HTTP client + best-effort three-pass loop. Falls back to
prior pass output when later passes fail (per Aetheria's amendment on
graceful degradation).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Writeback (parse + DB writes)

**Files:**
- Create: `soveryn/agents/dream/writeback.py`
- Create: `tests/test_dream_writeback.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_writeback.py`:

```python
"""Tests for soveryn.agents.dream.writeback — parse synthesis prose +
write to dream layer / edges / dream_log.

Per Aetheria's note: best-effort parser, tolerant of natural-language
synthesis. No JSON-schema assumptions. [node:ID] references are the only
structured signal we extract.
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from soveryn.agents.dream.writeback import (
    ExtractedConnections,
    extract_node_references,
    extract_node_pairs,
    write_dream_outputs,
)
from soveryn.platform.lattice.legacy import LAYER_DREAM, LatticeStore


# ─── extract_node_references — pure parser ─────────────────────────────────

def test_extract_node_references_finds_tagged_ids():
    text = "Looking at [node:abc-123] and [node:def-456] together..."
    assert extract_node_references(text) == ["abc-123", "def-456"]


def test_extract_node_references_handles_uuid_format():
    text = "[node:6887fa0f-8ff1-4f7d-b4f3-b5ac0e8352d6] is interesting."
    assert extract_node_references(text) == ["6887fa0f-8ff1-4f7d-b4f3-b5ac0e8352d6"]


def test_extract_node_references_returns_empty_on_no_matches():
    assert extract_node_references("plain prose with no references") == []


def test_extract_node_references_dedupes_preserving_order():
    text = "[node:a] and [node:b] and [node:a] again"
    assert extract_node_references(text) == ["a", "b"]


# ─── extract_node_pairs — adjacency-based edge candidates ──────────────────

def test_extract_node_pairs_pairs_adjacent_references():
    """Two refs within ~250 chars of each other become an edge candidate."""
    text = "Looking at [node:a]. Now compare [node:b]. Long unrelated tail..."
    pairs = extract_node_pairs(text, max_distance=250)
    assert ("a", "b") in pairs or ("b", "a") in pairs


def test_extract_node_pairs_skips_far_apart_refs():
    """References separated by > max_distance characters don't pair."""
    text = "[node:a]" + " " * 500 + "[node:b]"
    pairs = extract_node_pairs(text, max_distance=100)
    assert pairs == []


def test_extract_node_pairs_returns_empty_on_single_or_no_refs():
    assert extract_node_pairs("[node:only-one]") == []
    assert extract_node_pairs("nothing here") == []


# ─── write_dream_outputs — DB writes ────────────────────────────────────────

@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    # Seed two nodes so edge writes have valid sources/targets
    with sqlite3.connect(str(db)) as con:
        for nid in ("seed-a", "seed-b"):
            con.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, created_at, updated_at) "
                "VALUES (?, 'memory', 'lattice', 'aetheria', 'seed content', "
                "0.5, 0.5, 0, ?, ?)",
                (nid, datetime.now().isoformat(), datetime.now().isoformat()),
            )
    return db


def test_write_dream_outputs_writes_reflection_node_with_dream_layer(lattice_db):
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="This is what I noticed: [node:seed-a] connects to [node:seed-b].",
        associations="raw assoc text",
        contradictions="raw contra text",
        loop_health=0.85,
        nodes_read=2,
        is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, layer, type, agent, content FROM nodes WHERE layer = ?",
            (LAYER_DREAM,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["type"] == "reflection"
    assert rows[0]["agent"] == "aetheria"
    assert "seed-a" in rows[0]["content"]


def test_write_dream_outputs_writes_edges_for_paired_refs(lattice_db):
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="[node:seed-a] and [node:seed-b] are linked.",
        associations="x", contradictions="y",
        loop_health=1.0, nodes_read=2, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        edge_count = con.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = 'dream_association'"
        ).fetchone()[0]
    assert edge_count >= 1


def test_write_dream_outputs_writes_dream_log_row(lattice_db):
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="[node:seed-a] and [node:seed-b] linked.",
        associations="x", contradictions="y",
        loop_health=0.7, nodes_read=2, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM dream_log WHERE id = ?", (dream_run_id,),
        ).fetchone()
    assert row is not None
    assert row["trigger"] == "quiet_hours"
    assert row["agent"] == "aetheria"
    assert row["nodes_read"] == 2
    assert row["loop_health"] == 0.7
    assert row["dry_run"] == 0


def test_write_dream_outputs_dry_run_writes_only_dream_log_row(lattice_db):
    """Dry-run must NOT write reflection nodes or edges. Only the audit row."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="[node:seed-a] and [node:seed-b]",
        associations="x", contradictions="y",
        loop_health=1.0, nodes_read=2, is_dry_run=True,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = ?", (LAYER_DREAM,),
        ).fetchone()[0]
        new_edges = con.execute(
            "SELECT COUNT(*) FROM edges WHERE relationship = 'dream_association'"
        ).fetchone()[0]
        log_row = con.execute(
            "SELECT dry_run FROM dream_log WHERE id = ?", (dream_run_id,),
        ).fetchone()
    assert dream_nodes == 0
    assert new_edges == 0
    assert log_row[0] == 1  # dry_run marker set


def test_write_dream_outputs_handles_empty_synthesis(lattice_db):
    """Empty synthesis (silent night) — no reflection node, no edges,
    audit row still written."""
    dream_run_id = str(uuid.uuid4())
    write_dream_outputs(
        lattice_db,
        dream_run_id=dream_run_id,
        synthesis="",
        associations="", contradictions="",
        loop_health=0.0, nodes_read=0, is_dry_run=False,
    )
    with sqlite3.connect(str(lattice_db)) as con:
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = ?", (LAYER_DREAM,),
        ).fetchone()[0]
        log_row = con.execute(
            "SELECT * FROM dream_log WHERE id = ?", (dream_run_id,),
        ).fetchone()
    assert dream_nodes == 0
    assert log_row is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_writeback.py -v
```

Expected: FAIL on import error

- [ ] **Step 3: Create `soveryn/agents/dream/writeback.py`**

```python
"""Dream output parser + DB writer.

Per Aetheria's note: the cognition surface emits natural-language
synthesis, NOT a JSON-schema-constrained structure. The parser is
best-effort: it pulls [node:ID] references out of the prose and
uses adjacency to suggest edges, while the synthesis prose itself
becomes the reflection node content.

DB writes go to three places (silent residue + accessible reflection):
  - nodes (layer='dream', type='reflection') ← reflection content
  - edges (relationship='dream_association') ← extracted from [node:ID] adjacency
  - dream_log ← audit row, always
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from soveryn.platform.lattice.legacy import LAYER_DREAM


# Matches [node:ID] where ID is any non-bracket, non-whitespace run.
# UUIDs (with dashes), short slugs, and numeric IDs all work.
_NODE_REF_PATTERN = re.compile(r"\[node:([^\]\s]+)\]")


def extract_node_references(text: str) -> list[str]:
    """Pull every [node:ID] reference from the text. Deduped, order-preserving."""
    if not isinstance(text, str):
        return []
    seen: list[str] = []
    seen_set: set[str] = set()
    for m in _NODE_REF_PATTERN.finditer(text):
        nid = m.group(1)
        if nid and nid not in seen_set:
            seen.append(nid)
            seen_set.add(nid)
    return seen


def extract_node_pairs(
    text: str, *, max_distance: int = 250,
) -> list[tuple[str, str]]:
    """Pair adjacent [node:ID] references within max_distance characters.

    Adjacency = "mentioned in the same neighborhood of prose." Crude but
    matches the natural-language structure: when a synthesis mentions two
    node IDs close together, they're being connected.
    """
    if not isinstance(text, str):
        return []
    matches = list(_NODE_REF_PATTERN.finditer(text))
    if len(matches) < 2:
        return []
    pairs: list[tuple[str, str]] = []
    for i in range(len(matches) - 1):
        a = matches[i]
        b = matches[i + 1]
        if (b.start() - a.end()) <= max_distance:
            pairs.append((a.group(1), b.group(1)))
    return pairs


def write_dream_outputs(
    lattice_db_path: Path,
    *,
    dream_run_id: str,
    synthesis: str,
    associations: str,
    contradictions: str,
    loop_health: float,
    nodes_read: int,
    is_dry_run: bool,
) -> None:
    """Persist the dream outputs. Dry-run skips reflection + edges; the
    audit row goes in either way."""
    edges_created = 0

    if not is_dry_run and synthesis and synthesis.strip():
        reflection_node_id = _write_reflection_node(
            lattice_db_path,
            dream_run_id=dream_run_id,
            synthesis=synthesis,
            associations=associations,
            contradictions=contradictions,
        )
        edges_created = _write_edges_from_synthesis(
            lattice_db_path,
            synthesis=synthesis,
            reflection_node_id=reflection_node_id,
        )

    _write_dream_log_row(
        lattice_db_path,
        dream_run_id=dream_run_id,
        synthesis=synthesis,
        loop_health=loop_health,
        nodes_read=nodes_read,
        edges_created=edges_created,
        is_dry_run=is_dry_run,
    )


def _write_reflection_node(
    lattice_db_path: Path,
    *,
    dream_run_id: str,
    synthesis: str,
    associations: str,
    contradictions: str,
) -> str:
    """Persist the synthesis as a layer='dream' node. Returns its id."""
    node_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    provenance = {
        "source": "dream_daemon",
        "dream_run_id": dream_run_id,
        "passes_visible": {
            "associations_len": len(associations or ""),
            "contradictions_len": len(contradictions or ""),
            "synthesis_len": len(synthesis or ""),
        },
    }
    with sqlite3.connect(str(lattice_db_path)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at, "
            "provenance) VALUES (?, 'reflection', ?, 'aetheria', ?, "
            "0.6, 0.6, 0, ?, ?, ?)",
            (node_id, LAYER_DREAM, synthesis.strip(), now, now,
             json.dumps(provenance, sort_keys=True)),
        )
    return node_id


def _write_edges_from_synthesis(
    lattice_db_path: Path,
    *,
    synthesis: str,
    reflection_node_id: str,
) -> int:
    """Extract [node:ID] adjacency pairs and write edges with
    relationship='dream_association'. Skips edges where either node id
    doesn't exist in the nodes table (best-effort tolerance)."""
    pairs = extract_node_pairs(synthesis)
    if not pairs:
        return 0
    now = datetime.now().isoformat()
    written = 0
    with sqlite3.connect(str(lattice_db_path)) as con:
        # Verify which referenced node ids actually exist; skip dangling refs
        all_refs = {ref for pair in pairs for ref in pair}
        if not all_refs:
            return 0
        placeholders = ",".join("?" for _ in all_refs)
        existing = {
            r[0] for r in con.execute(
                f"SELECT id FROM nodes WHERE id IN ({placeholders})",
                tuple(all_refs),
            ).fetchall()
        }
        for source_id, target_id in pairs:
            if source_id not in existing or target_id not in existing:
                continue
            try:
                con.execute(
                    "INSERT INTO edges (id, source_id, target_id, relationship, "
                    "strength, bidirectional, reinforcement_count, created_at, "
                    "provenance) VALUES (?, ?, ?, 'dream_association', 0.5, 1, "
                    "1, ?, ?)",
                    (str(uuid.uuid4()), source_id, target_id, now,
                     json.dumps({"source": "dream_daemon",
                                  "reflection_node_id": reflection_node_id},
                                 sort_keys=True)),
                )
                written += 1
            except sqlite3.IntegrityError:
                # Same pair already linked — skip silently
                continue
    return written


def _write_dream_log_row(
    lattice_db_path: Path,
    *,
    dream_run_id: str,
    synthesis: str,
    loop_health: float,
    nodes_read: int,
    edges_created: int,
    is_dry_run: bool,
) -> None:
    summary = synthesis.strip()[:500] if synthesis else "(silent)"
    with sqlite3.connect(str(lattice_db_path)) as con:
        con.execute(
            "INSERT INTO dream_log "
            "(id, trigger, agent, nodes_read, edges_created, nodes_merged, "
            "contradictions_flagged, summary, ran_at, loop_health, dry_run) "
            "VALUES (?, 'quiet_hours', 'aetheria', ?, ?, 0, 0, ?, ?, ?, ?)",
            (dream_run_id, nodes_read, edges_created, summary,
             datetime.now().isoformat(), loop_health,
             1 if is_dry_run else 0),
        )


```

(No trailing placeholder class — earlier draft included an `ExtractedConnections` symbol but it isn't needed.)

Also remove the `ExtractedConnections` import from `tests/test_dream_writeback.py` (Step 1 of this task includes it in the imports — strip it before Step 4):

```python
# Change from:
from soveryn.agents.dream.writeback import (
    ExtractedConnections,
    extract_node_references,
    extract_node_pairs,
    write_dream_outputs,
)
# To:
from soveryn.agents.dream.writeback import (
    extract_node_references,
    extract_node_pairs,
    write_dream_outputs,
)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_writeback.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/dream/writeback.py tests/test_dream_writeback.py
git -c gpg.sign=false commit -m "feat(dream): writeback — best-effort parser + DB writer

Extracts [node:ID] references from synthesis prose; adjacent references
become silent edges (dream_association). Synthesis prose itself becomes
the reflection node at layer='dream'. Dry-run skips writes except audit.

Best-effort tolerance per Aetheria's amendment — no JSON-schema
assumptions, dangling node refs silently skipped, empty synthesis
produces no reflection but still writes audit row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Daemon module (process loop + spin-bug regression)

**Files:**
- Create: `soveryn/agents/dream/daemon.py`
- Create: `soveryn/agents/dream/__main__.py`
- Create: `tests/test_dream_daemon.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_daemon.py`:

```python
"""Tests for the dream daemon loop.

Covers: spin-bug resistance under consecutive skipped ticks (matches the
heartbeat/patrol regression guard), dry-run mode writes only the audit
row, and end-to-end run uses the cognition orchestrator.
"""

import sqlite3
import threading
import time
from datetime import datetime
from unittest.mock import patch

import pytest

from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.daemon import DreamDaemon
from soveryn.agents.dream.cognition import CognitionResult
from soveryn.platform.lattice.legacy import LatticeStore


def _config(**kw) -> DreamConfig:
    base = dict(
        enabled=True, dry_run=True, quiet_hours="00:00-23:59",
        activity_backoff_seconds=1800, nodes_per_run=300,
        max_internal_iterations=3,
        cognition_url="http://x", cognition_timeout_seconds=10,
    )
    base.update(kw)
    return DreamConfig(**base)


@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


@pytest.fixture
def conv_db(tmp_path):
    return tmp_path / "conv.db"  # daemon reads from this for activity check


def test_daemon_does_not_spin_on_consecutive_skipped_ticks(lattice_db, conv_db, tmp_path):
    """Regression: matches the heartbeat 0fb715b + patrol spin-bug guard.
    With enabled=False every tick skips; sleep math must not collapse."""
    config = _config(enabled=False)  # forces DISABLED skip on every tick
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=2,
    )
    t = threading.Thread(target=daemon.run, daemon=True)
    t.start()
    time.sleep(1.0)
    daemon._stop = True
    t.join(timeout=5)
    with sqlite3.connect(str(lattice_db)) as con:
        row_count = con.execute(
            "SELECT COUNT(*) FROM dream_log"
        ).fetchone()[0]
    # Without the fix this loop emits hundreds of rows; with the fix and
    # interval=2s we should see <=5 in ~1s.
    assert row_count <= 5, f"daemon emitted {row_count} log rows in ~1s — spin bug regressed"


def test_daemon_dry_run_writes_only_audit_row(lattice_db, conv_db, tmp_path):
    """Eligible dry-run tick writes a dream_log row with dry_run=1, and
    skips the cognition call + reflection / edge writes."""
    # Seed a node so "nothing_to_dream_about" gate passes
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('n-seed', 'memory', 'lattice', 'aetheria', 'seed', "
            "0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    config = _config(dry_run=True)
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=999999,  # only one tick will run before stop
    )
    with patch("soveryn.agents.dream.daemon.run_three_pass") as mock_three_pass:
        daemon._do_tick(now=datetime.now())
    # Cognition is NOT called in dry-run
    mock_three_pass.assert_not_called()
    with sqlite3.connect(str(lattice_db)) as con:
        log_rows = con.execute(
            "SELECT dry_run FROM dream_log"
        ).fetchall()
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = 'dream'"
        ).fetchone()[0]
    assert len(log_rows) == 1
    assert log_rows[0][0] == 1  # dry_run marker
    assert dream_nodes == 0


def test_daemon_live_run_invokes_three_pass_and_writes_outputs(lattice_db, conv_db, tmp_path):
    """Live (non-dry-run) tick calls run_three_pass and writes outputs."""
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('n-seed', 'memory', 'lattice', 'aetheria', 'seed', "
            "0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    config = _config(dry_run=False)
    daemon = DreamDaemon(
        config, lattice_db=lattice_db, conv_db=conv_db,
        tick_interval_seconds=999999,
    )
    fake_result = CognitionResult(
        iterations_completed=3,
        associations="assoc",
        contradictions="contra",
        synthesis="[node:n-seed] reflection content",
        loop_health=1.0,
        error=None,
    )
    with patch(
        "soveryn.agents.dream.daemon.run_three_pass",
        return_value=fake_result,
    ):
        daemon._do_tick(now=datetime.now())
    with sqlite3.connect(str(lattice_db)) as con:
        dream_nodes = con.execute(
            "SELECT COUNT(*) FROM nodes WHERE layer = 'dream'"
        ).fetchone()[0]
        log_row = con.execute(
            "SELECT dry_run, loop_health FROM dream_log LIMIT 1"
        ).fetchone()
    assert dream_nodes == 1
    assert log_row[0] == 0  # dry_run marker NOT set
    assert log_row[1] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_daemon.py -v
```

Expected: FAIL on import error

- [ ] **Step 3: Create `soveryn/agents/dream/daemon.py`**

```python
"""Dream daemon process loop.

Mirrors heartbeat/patrol shape. Spin-bug-resistant pattern (last_dream_at
vs last_tick_at, same as 0fb715b). SIGTERM/SIGINT triggers graceful
shutdown.

Run as: `python -m soveryn.agents.dream`.
"""

from __future__ import annotations

import json
import logging
import signal
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.agents.dream.cognition import (
    CognitionResult,
    run_three_pass,
)
from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.prompt import DreamBriefing, NodeSummary
from soveryn.agents.dream.trigger import (
    DreamSkipReason,
    TickEligibility,
    evaluate_tick,
)
from soveryn.agents.dream.writeback import write_dream_outputs


logger = logging.getLogger(__name__)


DEFAULT_LATTICE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db")
DEFAULT_CONV_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/conversations_vnext.db")
DEFAULT_TICK_INTERVAL_SECONDS = 600  # 10 minutes — checks gates every 10 min during window


class DreamDaemon:
    """Single-threaded tick loop with spin-bug-resistant sleep math."""

    def __init__(
        self,
        config: DreamConfig,
        *,
        lattice_db: Path = DEFAULT_LATTICE_DB,
        conv_db: Path = DEFAULT_CONV_DB,
        tick_interval_seconds: int = DEFAULT_TICK_INTERVAL_SECONDS,
    ) -> None:
        self.config = config
        self.lattice_db = Path(lattice_db)
        self.conv_db = Path(conv_db)
        self.tick_interval_seconds = tick_interval_seconds
        self._stop = False

    # ─── Lifecycle ──────────────────────────────────────────────────────────

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        logger.info(
            "dream daemon starting. config=%s tick_interval=%ds",
            self.config, self.tick_interval_seconds,
        )
        last_dream_at: datetime | None = self._latest_dream_at()
        last_tick_at: datetime | None = None
        while not self._stop:
            now = datetime.now()
            try:
                self._do_tick(now=now)
            except Exception:
                logger.exception("tick failed")
            # Spin-bug-resistant sleep math:
            # last_tick_at advances every tick (eligible OR skipped).
            last_tick_at = now
            sleep_target = last_tick_at + timedelta(seconds=self.tick_interval_seconds)
            while not self._stop and datetime.now() < sleep_target:
                time.sleep(min(0.5, max(0.05, (sleep_target - datetime.now()).total_seconds())))
        logger.info("dream daemon stopped cleanly")

    def _handle_signal(self, *_: Any) -> None:
        logger.info("dream daemon received shutdown signal")
        self._stop = True

    # ─── Per-tick work ──────────────────────────────────────────────────────

    def _do_tick(self, *, now: datetime) -> None:
        last_dream_at = self._latest_dream_at()
        last_activity_at = self._latest_aetheria_activity_at()
        new_node_count = self._new_node_count_since(last_dream_at)
        eligibility = evaluate_tick(
            self.config, now=now,
            last_dream_at=last_dream_at,
            last_activity_at=last_activity_at,
            new_node_count_since_last_dream=new_node_count,
        )
        if not eligibility.eligible:
            logger.debug(
                "skipped tick: %s",
                eligibility.skip_reason.value if eligibility.skip_reason else "?",
            )
            return

        dream_run_id = str(uuid.uuid4())
        nodes = self._gather_nodes_for_briefing(last_dream_at)
        briefing = DreamBriefing(
            hours_since_last_dream=(
                round((now - last_dream_at).total_seconds() / 3600, 1)
                if last_dream_at else None
            ),
            nodes=nodes,
            board_summary=self._gather_board_summary(),
            recent_daemon_activity=self._gather_recent_daemon_activity(),
            recent_library_writes_count=self._count_recent_library_writes(last_dream_at),
        )

        if self.config.dry_run:
            logger.info(
                "dream tick %s DRY-RUN. nodes=%d briefing_preview=%r",
                dream_run_id, len(nodes),
                _preview(self._render_briefing_for_log(briefing)),
            )
            write_dream_outputs(
                self.lattice_db,
                dream_run_id=dream_run_id,
                synthesis="(dry-run)",
                associations="(dry-run)", contradictions="(dry-run)",
                loop_health=0.0,
                nodes_read=len(nodes),
                is_dry_run=True,
            )
            return

        # Live: run the three-pass cognition loop.
        try:
            result: CognitionResult = run_three_pass(
                briefing=briefing,
                cognition_url=self.config.cognition_url,
                timeout_seconds=self.config.cognition_timeout_seconds,
                max_internal_iterations=self.config.max_internal_iterations,
            )
        except Exception as e:
            logger.exception("cognition orchestrator crashed")
            write_dream_outputs(
                self.lattice_db,
                dream_run_id=dream_run_id,
                synthesis="",
                associations="", contradictions="",
                loop_health=0.0,
                nodes_read=len(nodes),
                is_dry_run=False,
            )
            return

        write_dream_outputs(
            self.lattice_db,
            dream_run_id=dream_run_id,
            synthesis=result.synthesis,
            associations=result.associations,
            contradictions=result.contradictions,
            loop_health=result.loop_health,
            nodes_read=len(nodes),
            is_dry_run=False,
        )
        logger.info(
            "dream tick %s done. iterations=%d loop_health=%.2f synthesis_len=%d",
            dream_run_id, result.iterations_completed,
            result.loop_health, len(result.synthesis or ""),
        )

    # ─── State queries (DB-direct) ──────────────────────────────────────────

    def _latest_dream_at(self) -> datetime | None:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                row = con.execute(
                    "SELECT ran_at FROM dream_log "
                    "WHERE ran_at IS NOT NULL "
                    "ORDER BY ran_at DESC LIMIT 1"
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _latest_aetheria_activity_at(self) -> datetime | None:
        """Most recent Aetheria session updated_at (excluding [heartbeat],
        [signal], [patrol] daemon sessions — those are autonomous, not Jon)."""
        try:
            with sqlite3.connect(str(self.conv_db)) as con:
                row = con.execute(
                    "SELECT MAX(updated_at) FROM conversation_meta "
                    "WHERE agent = 'aetheria' "
                    "AND (title IS NULL OR ("
                    "  title NOT LIKE '[heartbeat]%' "
                    "  AND title NOT LIKE '[signal]%' "
                    "))"
                ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        try:
            return datetime.fromisoformat(row[0])
        except ValueError:
            return None

    def _new_node_count_since(self, since: datetime | None) -> int:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                if since is None:
                    return con.execute(
                        "SELECT COUNT(*) FROM nodes"
                    ).fetchone()[0]
                return con.execute(
                    "SELECT COUNT(*) FROM nodes WHERE created_at > ?",
                    (since.isoformat(),),
                ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def _gather_nodes_for_briefing(self, since: datetime | None) -> tuple[NodeSummary, ...]:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                con.row_factory = sqlite3.Row
                if since is None:
                    rows = con.execute(
                        "SELECT id, agent, type, content FROM nodes "
                        "WHERE layer != ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        ("dream", self.config.nodes_per_run),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT id, agent, type, content FROM nodes "
                        "WHERE created_at > ? AND layer != ? "
                        "ORDER BY created_at DESC LIMIT ?",
                        (since.isoformat(), "dream", self.config.nodes_per_run),
                    ).fetchall()
        except sqlite3.OperationalError:
            return ()
        return tuple(
            NodeSummary(
                id=r["id"],
                agent=r["agent"] or "",
                node_type=r["type"] or "",
                content_head=(r["content"] or "")[:200],
            )
            for r in rows
        )

    def _gather_board_summary(self) -> str:
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                rows = con.execute(
                    "SELECT provenance FROM nodes WHERE type = 'coordination'"
                ).fetchall()
        except sqlite3.OperationalError:
            return "Signal: 0 / Blueprint: 0 / Friction: 0"
        signal_count = 0
        bp_count = 0
        friction_count = 0
        for r in rows:
            try:
                prov = json.loads(r[0] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if prov.get("status") == "Archived":
                continue
            board = prov.get("board")
            if board == "Signal":
                signal_count += 1
            elif board == "Blueprint":
                bp_count += 1
            elif board == "Friction":
                friction_count += 1
        return f"Signal: {signal_count} / Blueprint: {bp_count} open / Friction: {friction_count}"

    def _gather_recent_daemon_activity(self) -> str:
        """Last 24h of heartbeat + patrol audit summaries."""
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                hb = con.execute(
                    "SELECT COUNT(*) FROM heartbeat_log "
                    "WHERE eligible = 1 AND triggered_at > ?",
                    (cutoff,),
                ).fetchone()[0]
                pat = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(dry_run), 0) FROM vett_patrol_log "
                    "WHERE eligible = 1 AND triggered_at > ?",
                    (cutoff,),
                ).fetchone()
        except sqlite3.OperationalError:
            return "no recent daemon activity"
        return f"heartbeat {hb} eligible ticks; patrol {pat[0]} eligible ticks ({pat[1]} dry-run)"

    def _count_recent_library_writes(self, since: datetime | None) -> int:
        if since is None:
            since_iso = (datetime.now() - timedelta(hours=24)).isoformat()
        else:
            since_iso = since.isoformat()
        try:
            with sqlite3.connect(str(self.lattice_db)) as con:
                return con.execute(
                    "SELECT COUNT(*) FROM nodes "
                    "WHERE layer = 'library' AND created_at > ?",
                    (since_iso,),
                ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0

    def _render_briefing_for_log(self, b: DreamBriefing) -> str:
        return (
            f"nodes={len(b.nodes)} board='{b.board_summary}' "
            f"daemon='{b.recent_daemon_activity}' lib_writes={b.recent_library_writes_count}"
        )


def _preview(s: str, limit: int = 200) -> str:
    return s[:limit] + ("…" if len(s) > limit else "")


def _main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = DreamConfig.from_env()
    daemon = DreamDaemon(config)
    daemon.run()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
```

- [ ] **Step 4: Create `soveryn/agents/dream/__main__.py`**

```python
"""Entry point so `python -m soveryn.agents.dream` starts the daemon."""

from soveryn.agents.dream.daemon import _main

if __name__ == "__main__":
    raise SystemExit(_main())
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_daemon.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add soveryn/agents/dream/daemon.py soveryn/agents/dream/__main__.py tests/test_dream_daemon.py
git -c gpg.sign=false commit -m "feat(dream): daemon loop with spin-bug-resistant pattern

Process loop matches heartbeat/patrol shape. last_dream_at advances
only on eligible ticks; last_tick_at advances every tick so sleep math
doesn't collapse on consecutive skips. Dry-run path writes audit row
only; live path invokes the three-pass cognition orchestrator and
persists outputs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Aetheria-only dream tools (recent_dreams + search_dreams)

**Files:**
- Create: `soveryn/agents/dream/tools.py`
- Create: `tests/test_dream_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dream_tools.py`:

```python
"""Tests for the Aetheria-only dream-recall tools."""

import sqlite3
import uuid
from datetime import datetime, timedelta

import pytest

from soveryn.agents.dream.tools import (
    build_recent_dreams_tool,
    build_search_dreams_tool,
    register_dream_tools,
)
from soveryn.platform.lattice.legacy import LAYER_DREAM, LatticeStore
from soveryn.platform.tools.registry import ToolRegistry


@pytest.fixture
def lattice_db(tmp_path):
    db = tmp_path / "lattice.db"
    LatticeStore(db)
    return db


def _insert_dream(db, *, content: str, ran_at_iso: str) -> str:
    node_id = str(uuid.uuid4())
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES (?, 'reflection', ?, 'aetheria', ?, 0.6, 0.6, 0, ?, ?)",
            (node_id, LAYER_DREAM, content, ran_at_iso, ran_at_iso),
        )
    return node_id


# ─── recent_dreams ──────────────────────────────────────────────────────────

def test_recent_dreams_returns_dreams_within_window(lattice_db):
    _insert_dream(
        lattice_db,
        content="last night's synthesis",
        ran_at_iso=(datetime.now() - timedelta(hours=8)).isoformat(),
    )
    _insert_dream(
        lattice_db,
        content="a week ago",
        ran_at_iso=(datetime.now() - timedelta(days=7)).isoformat(),
    )
    tool = build_recent_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({"window_hours": 24})
    assert result["count"] == 1
    assert "last night" in result["dreams"][0]["content_head"]


def test_recent_dreams_defaults_to_24h(lattice_db):
    _insert_dream(
        lattice_db,
        content="recent",
        ran_at_iso=(datetime.now() - timedelta(hours=5)).isoformat(),
    )
    tool = build_recent_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    assert result["count"] == 1


def test_recent_dreams_returns_empty_when_no_dreams(lattice_db):
    tool = build_recent_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({})
    assert result["count"] == 0
    assert result["dreams"] == []


# ─── search_dreams ──────────────────────────────────────────────────────────

def test_search_dreams_returns_layer_dream_only(lattice_db):
    """Should not return non-dream nodes even if their content matches."""
    _insert_dream(lattice_db, content="The funding round next month",
                   ran_at_iso=datetime.now().isoformat())
    # Insert a non-dream node with similar content
    with sqlite3.connect(str(lattice_db)) as con:
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, created_at, updated_at) "
            "VALUES ('not-dream', 'memory', 'lattice', 'aetheria', "
            "'The funding round details', 0.5, 0.5, 0, ?, ?)",
            (datetime.now().isoformat(), datetime.now().isoformat()),
        )
    tool = build_search_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    result = tool.handler({"query": "funding round"})
    # Should match the dream but NOT the non-dream
    ids = {m["reflection_node_id"] for m in result["matches"]}
    assert "not-dream" not in ids
    assert result["count"] >= 1


def test_search_dreams_empty_query_rejected(lattice_db):
    tool = build_search_dreams_tool(
        lattice_db_path=lattice_db, owner_agent="aetheria",
    )
    from soveryn.platform.tools.registry import ToolArgError
    with pytest.raises(ToolArgError):
        tool.handler({"query": ""})


# ─── register_dream_tools ──────────────────────────────────────────────────

def test_register_dream_tools_adds_for_aetheria_only(lattice_db):
    registry = ToolRegistry()
    register_dream_tools(
        registry,
        lattice_db_path=lattice_db,
        owner_agent="aetheria",
    )
    aetheria_tools = {s.name for s in registry.iter_tools_for_agent("aetheria")}
    assert "recent_dreams" in aetheria_tools
    assert "search_dreams" in aetheria_tools
    for other in ("vett", "scotty"):
        other_tools = {s.name for s in registry.iter_tools_for_agent(other)}
        assert "recent_dreams" not in other_tools
        assert "search_dreams" not in other_tools
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_tools.py -v
```

Expected: FAIL on import error

- [ ] **Step 3: Create `soveryn/agents/dream/tools.py`**

```python
"""Aetheria-only dream-recall tools — recent_dreams + search_dreams.

Per spec: dreams are NOT auto-injected into context. She uses these
when she chooses to look. Both are Aetheria-only.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from soveryn.platform.lattice.legacy import LAYER_DREAM
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_recent_dreams_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str,
) -> ToolSpec:
    """List Aetheria's recent reflection nodes from the dream layer."""

    def handler(args: Mapping[str, Any]) -> Any:
        window_hours = args.get("window_hours", 24)
        if not isinstance(window_hours, int) or isinstance(window_hours, bool):
            raise ToolArgError("window_hours must be an integer")
        if window_hours <= 0 or window_hours > 168:
            raise ToolArgError("window_hours must be in [1, 168]")
        cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat()
        with sqlite3.connect(str(lattice_db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, content, created_at FROM nodes "
                "WHERE layer = ? AND type = 'reflection' AND created_at > ? "
                "ORDER BY created_at DESC LIMIT 50",
                (LAYER_DREAM, cutoff),
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "reflection_node_id": r["id"],
                "content_head": (r["content"] or "")[:300],
                "ran_at": r["created_at"],
            })
        return {"count": len(out), "dreams": out}

    return ToolSpec(
        name="recent_dreams",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "window_hours": {
                    "type": "integer",
                    "description": (
                        "How far back to look. Default 24 hours. Max 168 "
                        "(1 week)."
                    ),
                    "minimum": 1,
                    "maximum": 168,
                    "default": 24,
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Read your own recent dreams (reflection nodes from the dream "
            "layer). Use when you want to know what came up while you slept."
        ),
    )


def build_search_dreams_tool(
    *,
    lattice_db_path: Path,
    owner_agent: str,
) -> ToolSpec:
    """Substring search restricted to the dream layer.

    v1 uses SQL LIKE on the content column. The writeback doesn't write
    embeddings for reflection nodes, so embedding-search isn't viable
    yet. Substring matching is good enough for "find that thing I
    reflected on about funding" — and it's transparent / debuggable.
    Embedding-based dream search is a follow-up enhancement.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        query = args.get("query", "")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgError("query must be a non-empty string")
        like_pattern = f"%{query.strip()}%"
        with sqlite3.connect(str(lattice_db_path)) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(
                "SELECT id, content, created_at FROM nodes "
                "WHERE layer = ? AND type = 'reflection' "
                "AND content LIKE ? "
                "ORDER BY created_at DESC LIMIT 20",
                (LAYER_DREAM, like_pattern),
            ).fetchall()
        out = []
        for r in rows:
            out.append({
                "reflection_node_id": r["id"],
                "content_head": (r["content"] or "")[:300],
                "ran_at": r["created_at"],
            })
        return {"count": len(out), "matches": out}

    return ToolSpec(
        name="search_dreams",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Substring to search for in your past dreams. "
                        "Matches anywhere in the reflection content. "
                        "Restricted to your own dream layer."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Search your past dreams (reflection nodes from the dream layer) "
            "by substring. Returns up to 20 matches, most recent first. "
            "Restricted to your own dream layer."
        ),
    )


def register_dream_tools(
    registry: ToolRegistry,
    *,
    lattice_db_path: Path,
    owner_agent: str = "aetheria",
) -> None:
    """Register both dream-recall tools for the given agent (Aetheria by default)."""
    registry.register(build_recent_dreams_tool(
        lattice_db_path=lattice_db_path,
        owner_agent=owner_agent,
    ))
    registry.register(build_search_dreams_tool(
        lattice_db_path=lattice_db_path,
        owner_agent=owner_agent,
    ))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_dream_tools.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/dream/tools.py tests/test_dream_tools.py
git -c gpg.sign=false commit -m "feat(dream): Aetheria-only recent_dreams + search_dreams tools

Per spec: dreams are NOT auto-injected. She uses these tools when she
chooses to look. recent_dreams = window-based list; search_dreams =
embedding-based theme matching. Both restricted to layer='dream'.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Startup wiring — register dream tools for Aetheria

**Files:**
- Modify: `soveryn/app/startup.py`
- Modify: `tests/test_app_startup_tool_registry.py`

- [ ] **Step 1: Update the test to assert dream tools are registered**

Open `tests/test_app_startup_tool_registry.py`. Find the assertion in `test_startup_creates_tool_registry_for_aetheria` that lists Aetheria's tool names. After the existing `assert "recent_self_audit" in names` line, add:

```python
# Dream-recall tools (added 2026-06-05 — Aetheria-only, not auto-injected;
# she queries her own dream layer when she chooses to look).
assert {"recent_dreams", "search_dreams"} <= names
```

Find `test_other_agents_do_not_get_aetheria_lattice_tools`. After the existing `library_tools` set definition, add:

```python
# Dream tools are Aetheria-only — Vett and Scotty don't dream.
dream_tools = {"recent_dreams", "search_dreams"}
```

Inside the `for agent in ("vett", "scotty"):` loop body, add this assertion:

```python
assert names.isdisjoint(dream_tools), \
    f"{agent} sees dream tools (should not): {names & dream_tools}"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_app_startup_tool_registry.py -v
```

Expected: FAIL — dream tools not yet registered

- [ ] **Step 3: Wire dream tools in startup.py**

In `soveryn/app/startup.py`, find the block that registers `signal_send` (search for `register_signal_send_tool`). After that block, add:

```python
        # Aetheria-only dream-recall tools (recent_dreams + search_dreams).
        # NOT auto-injected — she queries her own dream layer when she
        # chooses to look. Restricted to layer='dream' on the nodes table.
        # The dream daemon writes those nodes during quiet hours.
        if env.lattice_db.is_file():
            from soveryn.agents.dream.tools import register_dream_tools
            register_dream_tools(
                tool_registry,
                lattice_db_path=env.lattice_db,
                owner_agent="aetheria",
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest tests/test_app_startup_tool_registry.py -v
```

Expected: PASS

- [ ] **Step 5: Full suite regression check**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest 2>&1 | tail -3
```

Expected: All previous tests + the new ones pass.

- [ ] **Step 6: Commit**

```bash
git add soveryn/app/startup.py tests/test_app_startup_tool_registry.py
git -c gpg.sign=false commit -m "feat(startup): wire dream tools for Aetheria

recent_dreams + search_dreams now registered. Vett + Scotty stay off
the dream layer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: systemd unit + manual smoke test

**Files:**
- Create: `~/.config/systemd/user/soveryn-dream.service` (out-of-repo, managed separately)

- [ ] **Step 1: Create the systemd user unit**

Create `~/.config/systemd/user/soveryn-dream.service` with this exact content:

```ini
# SOVERYN Dream Daemon — user service.
# Aetheria's quiet-hours reflection cycle. Inverse of the heartbeat —
# fires only inside SOVERYN_DREAM_QUIET_HOURS.
#
# Design rules from docs/superpowers/specs/2026-06-05-dream-daemon-design.md:
# - One dream per quiet-hours window
# - 30-min activity backoff so we don't dream while she's mid-thought
# - Three-pass internal cognition (association → contradiction → synthesis)
# - Three output channels: silent edges + silent contradictions +
#   accessible reflection (Aetheria-only recent_dreams/search_dreams tools)
# - Starts DRY-RUN; flip live after 24-48h bake + first inspection

[Unit]
Description=SOVERYN Dream Daemon (Aetheria quiet-hours reflection)
Documentation=file:///home/jon-deoliveira/soveryn_vnext/docs/superpowers/specs/2026-06-05-dream-daemon-design.md
PartOf=soveryn.target
After=soveryn-vnext.service network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/jon-deoliveira/soveryn_vnext
Environment=PATH=/home/jon-deoliveira/miniconda3/envs/soveryn/bin:/usr/bin
Environment=SOVERYN_DREAM_ENABLED=true
Environment=SOVERYN_DREAM_DRY_RUN=true
Environment=SOVERYN_DREAM_QUIET_HOURS=23:00-07:00
Environment=SOVERYN_DREAM_ACTIVITY_BACKOFF_SECONDS=1800
Environment=SOVERYN_DREAM_NODES_PER_RUN=300
Environment=SOVERYN_DREAM_MAX_INTERNAL_ITERATIONS=3
Environment=SOVERYN_DREAM_COGNITION_URL=http://127.0.0.1:8089
Environment=SOVERYN_DREAM_COGNITION_TIMEOUT_SECONDS=120

ExecStartPre=/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.platform.supervisor.readiness http://127.0.0.1:5001/health --name vnext --max-wait 60
ExecStart=/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.agents.dream
Restart=on-failure
RestartSec=30
StandardOutput=append:/tmp/soveryn-dream.log
StandardError=append:/tmp/soveryn-dream.log

[Install]
WantedBy=soveryn.target
```

- [ ] **Step 2: Reload + start the unit + check status**

```bash
systemctl --user daemon-reload
systemctl --user start soveryn-dream.service
sleep 3
systemctl --user status soveryn-dream.service --no-pager | head -15
```

Expected: Active (running). Log file `/tmp/soveryn-dream.log` should have one INFO line: `dream daemon starting. config=DreamConfig(...) tick_interval=...`.

- [ ] **Step 3: Force a dry-run tick interactively (don't wait until 23:00)**

If the current local time is outside the configured quiet hours window (`23:00-07:00`), the daemon will skip every tick. To exercise the eligible-tick path during development, override the quiet-hours window temporarily:

```bash
systemctl --user stop soveryn-dream.service
SOVERYN_DREAM_QUIET_HOURS=00:00-23:59 SOVERYN_DREAM_NODES_PER_RUN=50 /home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -c "
from soveryn.agents.dream.config import DreamConfig
from soveryn.agents.dream.daemon import DreamDaemon
from datetime import datetime
cfg = DreamConfig.from_env()
daemon = DreamDaemon(cfg)
daemon._do_tick(now=datetime.now())
"
```

Expected: log output `dream tick <uuid> DRY-RUN. nodes=N briefing_preview=...` ; one row added to `dream_log` table with `dry_run=1`.

- [ ] **Step 4: Verify the audit row landed**

```bash
sqlite3 /home/jon-deoliveira/soveryn_complete/soveryn_memory/lattice_vnext.db "SELECT substr(ran_at, 12, 8), trigger, agent, nodes_read, dry_run, summary FROM dream_log ORDER BY ran_at DESC LIMIT 3;"
```

Expected: most recent row has `trigger=quiet_hours`, `agent=aetheria`, `dry_run=1`, summary `(dry-run)`.

- [ ] **Step 5: Restart the service in normal mode**

```bash
systemctl --user start soveryn-dream.service
systemctl --user is-active soveryn-dream.service
```

Expected: `active`. Daemon will sleep until the configured quiet-hours window opens.

- [ ] **Step 6: Restart vnext so the dream tools register for Aetheria**

```bash
systemctl --user restart soveryn-vnext.service
sleep 3
curl -s http://127.0.0.1:5001/health
```

Expected: health response. Now Aetheria has `recent_dreams` and `search_dreams` available.

- [ ] **Step 7: Manual smoke — Aetheria can call recent_dreams via /chat**

This step is optional but useful for verification:

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -c "
import json, urllib.request
req = urllib.request.Request(
    'http://127.0.0.1:5001/sessions',
    data=json.dumps({'agent': 'aetheria', 'title': '[probe] dream tools'}).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=10) as r:
    sid = json.loads(r.read())['session_id']
req2 = urllib.request.Request(
    'http://127.0.0.1:5001/chat',
    data=json.dumps({
        'agent': 'aetheria',
        'session_id': sid,
        'message': 'Call the recent_dreams tool with default window. Tell me what you find.'
    }).encode(),
    headers={'Content-Type': 'application/json'},
    method='POST',
)
with urllib.request.urlopen(req2, timeout=120) as r:
    body = json.loads(r.read())
print('content head:', (body.get('content') or '')[:400])
"
```

Expected: Aetheria responds describing what `recent_dreams` returned. If the dream layer is empty (no dream daemon runs yet), she should say so honestly.

---

## Task 11: Final regression sweep

- [ ] **Step 1: Run the full suite**

```bash
/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest 2>&1 | tail -5
```

Expected: All tests pass. The total count should be approximately `1223 (before this plan) + ~50 new tests = ~1270`.

- [ ] **Step 2: Confirm no untracked files left over**

```bash
git status --porcelain
```

Expected: Only `data/ares/` and `data/telemetry/` left as untracked (those are runtime daemon scratch, not source). Everything from the plan should be committed.

- [ ] **Step 3: Show the full commit chain for the plan**

```bash
git log --oneline -12
```

Expected: 9-11 fresh commits from this plan, each focused and atomic.

---

## Out of plan (deferred until first bake observations)

These are explicitly NOT in this plan; they wait for data:

- **Flipping `SOVERYN_DREAM_DRY_RUN=false`** — after a 24-48h dry-run bake against the cognition surface. Manual change in the systemd unit + restart. Watch the first 3-5 live runs.
- **Tuning the three internal prompt strings** — the v1 prose in `prompt.py` is a starting point. After first live runs, observe whether the cognition surface responds with the synthesis-asking shape we expected; iterate the prompts as needed.
- **Adding a `dream_now` CLI flag** for forced runs (skip trigger gates, for debugging). Trivial addition to `__main__.py`; add it when a manual replay becomes useful.
- **Standing up the cognition surface on Quadro #2:8089.** This plan assumes the surface is operational at the configured URL. The infrastructure work (llama-server invocation + GPU pinning + readiness probe) is operational, not in-plan code work.
- **Migrating to Spark when it arrives.** Single env var change: `SOVERYN_DREAM_COGNITION_URL=http://<spark>:<port>`. systemctl restart, validate.

---

## Implementation order recap

The eleven tasks above should be completed sequentially. Each is atomic and committed independently so a partial implementation still leaves a coherent codebase:

1. Schema additions (LAYER_DREAM + dream_log.dry_run)
2. Config module
3. Trigger module
4. Prompt module
5. Cognition HTTP client + 3-pass orchestrator
6. Writeback parser + DB writer
7. Daemon loop + spin-bug regression
8. Aetheria-only dream tools
9. Startup wiring
10. systemd unit + smoke test
11. Final regression sweep
