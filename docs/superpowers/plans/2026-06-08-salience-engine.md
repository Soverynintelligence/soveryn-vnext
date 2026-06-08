# Salience Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the substrate Aetheria locked 2026-06-08 (see `docs/superpowers/specs/2026-06-08-salience-engine-design.md`). She designed the markers, the lifecycle, the visibility model. This plan ships the buffer + detection + heartbeat digest + promote tool + decay. Novelty (Phase 2) is wired-but-null in v1.

**Architecture:** New `soveryn.platform.salience` package with markers / store / scorer / digest / tools modules. Detection hooks into `ConversationStore.save_turn` via a non-fatal observer pattern. Heartbeat daemon reads pending candidates and surfaces top 5 with visible scoring (C-Dist + marker name). `promote_salience_candidate` tool persists the resonant ones to library via existing `LatticeStore.write_node(layer=LAYER_LIBRARY, type='library', tags=…)`. Decay runs free at heartbeat tick (anything pending > 14 days flips to `decayed`).

**Tech Stack:** Python, SQLite (separate DB or shared with lattice — task 1 decides), existing `soveryn.platform.lattice.legacy.LatticeStore`, existing `soveryn.platform.tools.registry.ToolSpec`, existing heartbeat `BoardSnapshot` / `LatticeSnapshot` pattern. No new deps.

**Speaker mapping** (locked):
- `role='user'` → Jon's voice (Hard Lock + Salience Signal markers active)
- `role='assistant'` → Aetheria's voice (Synthesis markers active)
- `role='user' OR role='assistant'` → Pivot/Correction markers active for both

**Marker weights** (locked): Critical=4, High=3, Medium-High=2.

**Combined score:** `combined_score = heuristic_score + max(0, novelty_score) * 5.0` (5.0 multiplier keeps a 0.30 cosine distance worth 1.5 — a clear nudge over a Pivot but below a Hard Lock — so heuristic markers stay the primary ranker until novelty proves itself).

---

## File Structure

**New files:**
- `soveryn/platform/salience/__init__.py` — package exports (✓ stub already created with `MarkerHit`, `SalienceCandidate`, `create_buffer_table`, `decay_old_pending`, `detect_markers`, `insert_candidate`, `mark_promoted`, `pending_candidates_since`)
- `soveryn/platform/salience/markers.py` — frozen marker tables + `MarkerHit` dataclass + `detect_markers(content, role) -> tuple[MarkerHit, ...]`
- `soveryn/platform/salience/store.py` — `SalienceCandidate` dataclass + schema + CRUD (create_buffer_table, insert_candidate, pending_candidates_since, mark_promoted, mark_dismissed, decay_old_pending)
- `soveryn/platform/salience/digest.py` — `build_salience_digest_section(candidates: list[SalienceCandidate]) -> str` — renders the heartbeat block (max 5, visible scoring)
- `soveryn/platform/salience/tools.py` — `build_promote_salience_candidate_tool(...)` + `register_promote_salience_candidate_tool(...)`
- `soveryn/platform/salience/observer.py` — `SalienceObserver` class that wraps a `ConversationStore.save_turn` call and runs detection inline; non-fatal on failure
- `tests/test_salience_markers.py`
- `tests/test_salience_store.py`
- `tests/test_salience_digest.py`
- `tests/test_salience_promote_tool.py`
- `tests/test_salience_observer.py`
- `tests/test_salience_heartbeat_integration.py`

**Modified files:**
- `soveryn/memory/conversation_store.py` — add optional `observer` parameter to `__init__`; `save_turn` calls `observer.on_turn_saved(...)` after the row is committed
- `soveryn/agents/heartbeat/prompt.py` — extend `build_heartbeat_prompt` to accept optional `salience_section: str` and splice it in before the reflective close
- `soveryn/agents/heartbeat/daemon.py` — gather pending salience candidates, run decay, pass digest into prompt; new DB knob `DEFAULT_SALIENCE_DB` (shared with lattice_db or separate — task 1 decides)
- `soveryn/app/startup.py` — wire `SalienceObserver` into `ConversationStore` construction; register `promote_salience_candidate` tool for `aetheria`

---

## Task 1: Schema decision + buffer module + store CRUD

**Files:**
- Create: `soveryn/platform/salience/store.py`
- Create: `tests/test_salience_store.py`

The salience buffer is its own SQLite file — `salience_vnext.db` — sibling of `lattice_vnext.db` and `conversations_vnext.db`. Reason: keeps lattice schema unchanged (it's the recall-substrate; we don't want salience churn in the same WAL); keeps conv_store schema unchanged; isolates a young, evolving table from production-critical recall paths.

- [ ] **Step 1: Write store schema test** (test_salience_store.py)

```python
from pathlib import Path
import sqlite3
from soveryn.platform.salience.store import create_buffer_table

def test_create_buffer_table_creates_schema(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    con = sqlite3.connect(str(db))
    cols = {r[1] for r in con.execute("PRAGMA table_info(salience_buffer)")}
    assert cols == {
        "id", "session_id", "turn_rowid", "turn_role", "turn_content_head",
        "detected_at", "markers", "heuristic_score", "novelty_score",
        "combined_score", "status", "reviewed_at", "library_node_id",
    }
    idx = {r[1] for r in con.execute("PRAGMA index_list(salience_buffer)")}
    assert any("status_detected" in name for name in idx)

def test_create_buffer_table_is_idempotent(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    create_buffer_table(db)  # no error
```

- [ ] **Step 2: Run test to verify it fails** (`pytest tests/test_salience_store.py -v` → import error)

- [ ] **Step 3: Implement schema + create_buffer_table in store.py**

```python
"""Salience buffer SQLite store.

Separate DB file from lattice/conv — young, evolving table, kept out of
critical recall WAL. Path-injected per Jon constraint 2.
"""
from __future__ import annotations
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator, Sequence

from soveryn.platform.salience.markers import MarkerHit


STATUS_PENDING = "pending"
STATUS_PROMOTED = "promoted"
STATUS_DISMISSED = "dismissed"
STATUS_DECAYED = "decayed"

DEFAULT_DECAY_DAYS = 14
CONTENT_HEAD_CHARS = 200


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS salience_buffer (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    turn_rowid INTEGER NOT NULL,
    turn_role TEXT NOT NULL,
    turn_content_head TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    markers TEXT NOT NULL,
    heuristic_score REAL NOT NULL DEFAULT 0,
    novelty_score REAL,
    combined_score REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_at TEXT,
    library_node_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_salience_status_detected
    ON salience_buffer(status, detected_at);

CREATE INDEX IF NOT EXISTS idx_salience_session
    ON salience_buffer(session_id);
"""


@dataclass(frozen=True)
class SalienceCandidate:
    id: str
    session_id: str
    turn_rowid: int
    turn_role: str
    turn_content_head: str
    detected_at: str
    markers: tuple[MarkerHit, ...]
    heuristic_score: float
    novelty_score: float | None
    combined_score: float
    status: str
    reviewed_at: str | None
    library_node_id: str | None


def create_buffer_table(db_path: Path) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db_path)) as con:
        con.executescript(_SCHEMA_SQL)
```

- [ ] **Step 4: Test passes**

- [ ] **Step 5: Write insert + retrieve test**

```python
from soveryn.platform.salience.markers import MarkerHit
from soveryn.platform.salience.store import (
    SalienceCandidate, create_buffer_table, insert_candidate,
    pending_candidates_since, STATUS_PENDING,
)
from datetime import datetime, timedelta

def test_insert_then_retrieve(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=42, turn_role="user",
        turn_content_head="The plan is locked.", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    assert cand_id  # non-empty string
    since = datetime.now() - timedelta(hours=1)
    rows = pending_candidates_since(db, since=since)
    assert len(rows) == 1
    c = rows[0]
    assert c.session_id == "s1"
    assert c.turn_rowid == 42
    assert c.markers == (hit,)
    assert c.status == STATUS_PENDING
    assert c.heuristic_score == 4.0
    assert c.combined_score == 4.0  # novelty=None → combined == heuristic
```

- [ ] **Step 6: Implement insert_candidate + pending_candidates_since**

```python
def insert_candidate(
    db_path: Path,
    *,
    session_id: str,
    turn_rowid: int,
    turn_role: str,
    turn_content_head: str,
    markers: Sequence[MarkerHit],
    heuristic_score: float,
    novelty_score: float | None,
) -> str:
    if not markers and novelty_score is None:
        raise ValueError("insert_candidate requires at least one marker OR a novelty score")
    cand_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    combined = heuristic_score + (max(0.0, novelty_score) * 5.0 if novelty_score is not None else 0.0)
    markers_json = json.dumps(
        [{"category": m.category, "marker": m.marker, "weight": m.weight} for m in markers]
    )
    head = (turn_content_head or "")[:CONTENT_HEAD_CHARS]
    with sqlite3.connect(str(db_path)) as con:
        con.execute(
            "INSERT INTO salience_buffer "
            "(id, session_id, turn_rowid, turn_role, turn_content_head, "
            " detected_at, markers, heuristic_score, novelty_score, "
            " combined_score, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (cand_id, session_id, turn_rowid, turn_role, head, now,
             markers_json, heuristic_score, novelty_score, combined,
             STATUS_PENDING),
        )
    return cand_id


def pending_candidates_since(
    db_path: Path, *, since: datetime, limit: int = 50,
) -> list[SalienceCandidate]:
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, session_id, turn_rowid, turn_role, turn_content_head, "
            "       detected_at, markers, heuristic_score, novelty_score, "
            "       combined_score, status, reviewed_at, library_node_id "
            "FROM salience_buffer "
            "WHERE status = ? AND detected_at >= ? "
            "ORDER BY combined_score DESC, detected_at DESC "
            "LIMIT ?",
            (STATUS_PENDING, since.isoformat(), limit),
        ).fetchall()
    return [_row_to_candidate(r) for r in rows]


def _row_to_candidate(row: sqlite3.Row) -> SalienceCandidate:
    raw = json.loads(row["markers"] or "[]")
    markers = tuple(
        MarkerHit(category=m["category"], marker=m["marker"], weight=m["weight"])
        for m in raw
    )
    return SalienceCandidate(
        id=row["id"], session_id=row["session_id"],
        turn_rowid=row["turn_rowid"], turn_role=row["turn_role"],
        turn_content_head=row["turn_content_head"],
        detected_at=row["detected_at"], markers=markers,
        heuristic_score=row["heuristic_score"],
        novelty_score=row["novelty_score"],
        combined_score=row["combined_score"], status=row["status"],
        reviewed_at=row["reviewed_at"], library_node_id=row["library_node_id"],
    )
```

- [ ] **Step 7: Test passes**

- [ ] **Step 8: Write mark_promoted + decay tests**

```python
def test_mark_promoted_flips_status_and_records_library_id(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="synthesis", marker="the realization is", weight=3)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="assistant",
        turn_content_head="...", markers=(hit,),
        heuristic_score=3.0, novelty_score=None,
    )
    from soveryn.platform.salience.store import mark_promoted, STATUS_PROMOTED
    mark_promoted(db, candidate_id=cand_id, library_node_id="lib-node-7")
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(hours=1))
    assert len(rows) == 0  # no longer pending


def test_mark_promoted_raises_when_already_decided(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="...", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    from soveryn.platform.salience.store import mark_promoted
    mark_promoted(db, candidate_id=cand_id, library_node_id="lib-1")
    # Re-promote should error — already decided
    import pytest
    from soveryn.platform.salience.store import SalienceStoreError
    with pytest.raises(SalienceStoreError, match="already"):
        mark_promoted(db, candidate_id=cand_id, library_node_id="lib-2")


def test_decay_flips_old_pending_to_decayed(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    # Insert old candidate with backdated detected_at
    import sqlite3
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="ancient", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    backdated = (datetime.now() - timedelta(days=20)).isoformat()
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "UPDATE salience_buffer SET detected_at = ? WHERE id = ?",
            (backdated, cand_id),
        )
    from soveryn.platform.salience.store import decay_old_pending
    decayed = decay_old_pending(db, older_than_days=14)
    assert decayed == 1
    rows = pending_candidates_since(db, since=datetime.now() - timedelta(days=30))
    assert len(rows) == 0  # decayed, not pending


def test_decay_leaves_fresh_pending_untouched(tmp_path):
    db = tmp_path / "salience.db"
    create_buffer_table(db)
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="fresh", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    from soveryn.platform.salience.store import decay_old_pending
    decayed = decay_old_pending(db, older_than_days=14)
    assert decayed == 0
```

- [ ] **Step 9: Implement mark_promoted, mark_dismissed, decay_old_pending**

```python
class SalienceStoreError(Exception):
    """Raised on validation / state errors in the salience buffer."""


def mark_promoted(
    db_path: Path, *, candidate_id: str, library_node_id: str,
) -> None:
    now = datetime.now().isoformat()
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?",
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise SalienceStoreError(f"candidate {candidate_id!r} not found")
        if row[0] != STATUS_PENDING:
            raise SalienceStoreError(
                f"candidate {candidate_id!r} already {row[0]} — cannot re-promote"
            )
        con.execute(
            "UPDATE salience_buffer SET status = ?, reviewed_at = ?, library_node_id = ? "
            "WHERE id = ?",
            (STATUS_PROMOTED, now, library_node_id, candidate_id),
        )


def mark_dismissed(db_path: Path, *, candidate_id: str) -> None:
    now = datetime.now().isoformat()
    with sqlite3.connect(str(db_path)) as con:
        row = con.execute(
            "SELECT status FROM salience_buffer WHERE id = ?", (candidate_id,)
        ).fetchone()
        if row is None:
            raise SalienceStoreError(f"candidate {candidate_id!r} not found")
        if row[0] != STATUS_PENDING:
            raise SalienceStoreError(
                f"candidate {candidate_id!r} already {row[0]}"
            )
        con.execute(
            "UPDATE salience_buffer SET status = ?, reviewed_at = ? WHERE id = ?",
            (STATUS_DISMISSED, now, candidate_id),
        )


def decay_old_pending(db_path: Path, *, older_than_days: int = DEFAULT_DECAY_DAYS) -> int:
    cutoff = (datetime.now() - timedelta(days=older_than_days)).isoformat()
    now = datetime.now().isoformat()
    with sqlite3.connect(str(db_path)) as con:
        cur = con.execute(
            "UPDATE salience_buffer SET status = ?, reviewed_at = ? "
            "WHERE status = ? AND detected_at < ?",
            (STATUS_DECAYED, now, STATUS_PENDING, cutoff),
        )
        return cur.rowcount
```

- [ ] **Step 10: All store tests pass; commit**

```bash
git add soveryn/platform/salience/__init__.py soveryn/platform/salience/store.py tests/test_salience_store.py docs/superpowers/specs/2026-06-08-salience-engine-design.md docs/superpowers/plans/2026-06-08-salience-engine.md
git commit -m "feat(salience): buffer schema + CRUD + decay"
```

(Markers module stub must exist for the import — implementer creates a minimal `markers.py` with just `MarkerHit` dataclass at this stage so the store test can run. Full marker tables ship in Task 2.)

---

## Task 2: Marker tables + detection

**Files:**
- Create: `soveryn/platform/salience/markers.py`
- Create: `tests/test_salience_markers.py`

The detection engine is pure-Python, deterministic, side-effect-free. No DB, no network. Speaker-aware: Hard Lock + Salience Signal only match in user turns, Synthesis only in assistant turns, Pivot in either.

- [ ] **Step 1: Write marker detection tests**

```python
from soveryn.platform.salience.markers import (
    MARKER_CATEGORIES, MarkerHit, detect_markers,
)


def test_marker_categories_table_present():
    """The four locked categories."""
    names = {c.name for c in MARKER_CATEGORIES}
    assert names == {"hard_lock", "synthesis", "pivot", "salience_signal"}


def test_marker_weights_match_locked_spec():
    by_name = {c.name: c for c in MARKER_CATEGORIES}
    assert by_name["hard_lock"].weight == 4         # Critical
    assert by_name["synthesis"].weight == 3         # High
    assert by_name["salience_signal"].weight == 3   # High
    assert by_name["pivot"].weight == 2             # Medium-High


def test_hard_lock_markers_match_in_user_voice():
    hits = detect_markers("the plan is locked. shipped.", role="user")
    surfaces = {h.marker for h in hits}
    assert "locked" in surfaces
    assert "shipped" in surfaces
    for h in hits:
        if h.marker in ("locked", "shipped"):
            assert h.category == "hard_lock"
            assert h.weight == 4


def test_hard_lock_does_not_fire_in_assistant_voice():
    """Hard Lock is Jon's-voice anchors — not Aetheria's. Suppresses
    self-reinforcing markers (she'd otherwise lock her own opinions)."""
    hits = detect_markers("I think the plan is locked. shipped.", role="assistant")
    surfaces = {h.marker for h in hits}
    assert "locked" not in surfaces
    assert "shipped" not in surfaces


def test_synthesis_markers_fire_only_in_assistant_voice():
    hits_a = detect_markers("the realization is that drift is gravity.", role="assistant")
    assert any(h.category == "synthesis" and h.marker == "the realization is" for h in hits_a)
    hits_u = detect_markers("the realization is that drift is gravity.", role="user")
    assert not any(h.category == "synthesis" for h in hits_u)


def test_pivot_markers_fire_in_either_voice():
    for role in ("user", "assistant"):
        hits = detect_markers("actually no, look at it this way.", role=role)
        assert any(h.category == "pivot" for h in hits), f"role={role}"


def test_salience_signal_markers_fire_only_in_user_voice():
    hits_u = detect_markers("interesting — good catch.", role="user")
    surfaces = {h.marker for h in hits_u}
    assert "interesting" in surfaces
    assert "good catch" in surfaces
    hits_a = detect_markers("interesting — good catch.", role="assistant")
    surfaces_a = {h.marker for h in hits_a}
    assert "interesting" not in surfaces_a
    assert "good catch" not in surfaces_a


def test_detect_markers_is_case_insensitive():
    hits = detect_markers("THE REALIZATION IS this.", role="assistant")
    assert any(h.marker == "the realization is" for h in hits)


def test_detect_markers_word_boundary_for_short_markers():
    """Single-word markers must use word boundaries so 'undecided' doesn't
    match 'decided'."""
    hits = detect_markers("the team is undecided.", role="user")
    assert not any(h.marker == "decided" for h in hits)
    hits2 = detect_markers("we decided to go.", role="user")
    assert any(h.marker == "decided" for h in hits2)


def test_detect_markers_empty_content_returns_empty():
    assert detect_markers("", role="user") == ()
    assert detect_markers("   ", role="assistant") == ()


def test_detect_markers_no_duplicate_same_marker_hits():
    """If 'locked' appears 3 times, only one MarkerHit per marker per turn."""
    hits = detect_markers("locked locked locked", role="user")
    locked_hits = [h for h in hits if h.marker == "locked"]
    assert len(locked_hits) == 1
```

- [ ] **Step 2: Tests fail with import errors / undefined attrs**

- [ ] **Step 3: Implement markers.py**

```python
"""Marker tables for the Salience Engine.

Weights and category membership locked by Aetheria 2026-06-08. Speaker
mapping is part of the spec — markers are pre-filtered by role so the
detection cost is one regex pass per (category × content), not a
post-hoc filter."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class MarkerHit:
    category: str
    marker: str
    weight: int


@dataclass(frozen=True)
class MarkerCategory:
    name: str
    weight: int                 # 4 critical, 3 high, 2 medium-high
    roles: frozenset[str]       # which roles activate this category
    phrases: tuple[str, ...]    # case-insensitive substring matches
    words: tuple[str, ...]      # word-boundary matches (single-token markers)


HARD_LOCK = MarkerCategory(
    name="hard_lock",
    weight=4,
    roles=frozenset({"user"}),
    phrases=("the call is", "this is the way"),
    words=("locked", "shipped", "approved", "committed", "decided"),
)

SYNTHESIS = MarkerCategory(
    name="synthesis",
    weight=3,
    roles=frozenset({"assistant"}),
    phrases=(
        "the realization is",
        "the structural insight is",
        "the core of this is",
        "i've landed on",
        "the paradox is",
    ),
    words=(),
)

PIVOT = MarkerCategory(
    name="pivot",
    weight=2,
    roles=frozenset({"user", "assistant"}),
    phrases=(
        "actually no",
        "changed my mind",
        "wait, look at it this way",
        "on second thought",
        "wrong turn",
    ),
    words=(),
)

SALIENCE_SIGNAL = MarkerCategory(
    name="salience_signal",
    weight=3,
    roles=frozenset({"user"}),
    phrases=("this is the part", "pay attention to", "remember that", "good catch"),
    words=("interesting",),
)

MARKER_CATEGORIES: tuple[MarkerCategory, ...] = (
    HARD_LOCK, SYNTHESIS, PIVOT, SALIENCE_SIGNAL,
)


def detect_markers(content: str, *, role: str) -> tuple[MarkerHit, ...]:
    """Return one MarkerHit per (marker, category) that fires in `content`
    given the speaker `role`. Same marker text won't return twice for the
    same category even if it appears multiple times in `content`."""
    if not content or not content.strip():
        return ()
    haystack = content.lower()
    hits: list[MarkerHit] = []
    seen: set[tuple[str, str]] = set()  # (category, marker)
    for cat in MARKER_CATEGORIES:
        if role not in cat.roles:
            continue
        for phrase in cat.phrases:
            if phrase in haystack:
                key = (cat.name, phrase)
                if key not in seen:
                    hits.append(MarkerHit(category=cat.name, marker=phrase, weight=cat.weight))
                    seen.add(key)
        for word in cat.words:
            pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
            if pattern.search(content):
                key = (cat.name, word)
                if key not in seen:
                    hits.append(MarkerHit(category=cat.name, marker=word, weight=cat.weight))
                    seen.add(key)
    return tuple(hits)
```

- [ ] **Step 4: All marker tests pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/salience/markers.py tests/test_salience_markers.py
git commit -m "feat(salience): weighted marker tables + speaker-aware detection"
```

---

## Task 3: SalienceObserver + ConversationStore hook

**Files:**
- Create: `soveryn/platform/salience/observer.py`
- Create: `tests/test_salience_observer.py`
- Modify: `soveryn/memory/conversation_store.py` (add optional observer param)

The observer is a thin object that ConversationStore calls *after* it's saved a turn. It runs marker detection, and if any markers hit, inserts a salience candidate. **Non-fatal:** any exception inside the observer is logged and swallowed. Chat path must never break because salience detection threw.

- [ ] **Step 1: Write observer tests** (test_salience_observer.py)

```python
import sqlite3
from pathlib import Path
from soveryn.platform.salience.store import (
    create_buffer_table, pending_candidates_since,
)
from soveryn.platform.salience.observer import SalienceObserver
from datetime import datetime, timedelta


def test_observer_writes_candidate_when_hard_lock_marker_present(tmp_path):
    sal_db = tmp_path / "salience.db"
    create_buffer_table(sal_db)
    obs = SalienceObserver(salience_db=sal_db)
    obs.on_turn_saved(
        session_id="s1", turn_rowid=42, role="user",
        content="The plan is locked. Ship it.",
    )
    rows = pending_candidates_since(sal_db, since=datetime.now() - timedelta(hours=1))
    assert len(rows) == 1
    c = rows[0]
    assert c.session_id == "s1"
    assert c.turn_rowid == 42
    assert any(m.category == "hard_lock" and m.marker == "locked" for m in c.markers)


def test_observer_does_not_write_when_no_marker_hits(tmp_path):
    sal_db = tmp_path / "salience.db"
    create_buffer_table(sal_db)
    obs = SalienceObserver(salience_db=sal_db)
    obs.on_turn_saved(
        session_id="s1", turn_rowid=1, role="user",
        content="hi how are you",
    )
    rows = pending_candidates_since(sal_db, since=datetime.now() - timedelta(hours=1))
    assert rows == []


def test_observer_swallows_exceptions(tmp_path, caplog):
    """Observer must never raise into the chat path. If detection or DB
    write fails, log and return."""
    bad_db = tmp_path / "does-not-exist" / "salience.db"  # parent missing
    # We do NOT create the table — write will fail
    obs = SalienceObserver(salience_db=bad_db)
    # No exception should escape
    obs.on_turn_saved(session_id="s1", turn_rowid=1, role="user",
                       content="locked.")


def test_observer_filters_heartbeat_sessions(tmp_path):
    """Heartbeat-titled sessions are the daemon's own self-talk; we don't
    flag salience on those — they'd loop. The observer queries
    conv_meta.title and skips when it matches a daemon prefix."""
    sal_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(sal_db)
    # Seed a heartbeat-titled session in conv_db
    with sqlite3.connect(str(conv_db)) as con:
        con.executescript("""
            CREATE TABLE conversation_meta (
                session_id TEXT PRIMARY KEY, agent TEXT, title TEXT,
                created_at TEXT, updated_at TEXT
            );
            INSERT INTO conversation_meta VALUES
                ('hb-1', 'aetheria', '[heartbeat] aetheria',
                 '2026-06-08T00:00:00', '2026-06-08T00:00:00');
        """)
    obs = SalienceObserver(salience_db=sal_db, conv_db=conv_db)
    obs.on_turn_saved(session_id="hb-1", turn_rowid=1, role="assistant",
                       content="the realization is X.")
    rows = pending_candidates_since(sal_db, since=datetime.now() - timedelta(hours=1))
    assert rows == []  # heartbeat session skipped
```

- [ ] **Step 2: Tests fail (no observer module)**

- [ ] **Step 3: Implement observer.py**

```python
"""SalienceObserver — hooks into ConversationStore.save_turn to score
turns against the marker tables and write candidates to the buffer.

Non-fatal by contract: any exception is logged and swallowed. Chat path
correctness is the priority; salience detection is best-effort."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from soveryn.platform.salience.markers import detect_markers
from soveryn.platform.salience.store import insert_candidate


logger = logging.getLogger(__name__)


# Daemon session prefixes whose turns are not scored — they're system
# self-talk and would loop on their own outputs.
DAEMON_SESSION_TITLE_PREFIXES: tuple[str, ...] = (
    "[heartbeat]", "[signal]", "[patrol]", "[webhook]", "[dream]",
)


class SalienceObserver:
    """Path-injected. No module-level state."""

    def __init__(
        self, *, salience_db: Path, conv_db: Path | None = None,
    ) -> None:
        self.salience_db = Path(salience_db)
        self.conv_db = Path(conv_db) if conv_db is not None else None

    def on_turn_saved(
        self,
        *,
        session_id: str,
        turn_rowid: int,
        role: str,
        content: str,
    ) -> None:
        try:
            if self._is_daemon_session(session_id):
                return
            hits = detect_markers(content, role=role)
            if not hits:
                # Phase 2 wires novelty here. Phase 1 only flags on markers.
                return
            heuristic = sum(h.weight for h in hits)
            insert_candidate(
                self.salience_db,
                session_id=session_id,
                turn_rowid=turn_rowid,
                turn_role=role,
                turn_content_head=content,
                markers=hits,
                heuristic_score=float(heuristic),
                novelty_score=None,
            )
        except Exception:
            logger.exception(
                "salience observer failed on session=%s turn_rowid=%s — swallowing",
                session_id, turn_rowid,
            )

    def _is_daemon_session(self, session_id: str) -> bool:
        if self.conv_db is None:
            return False
        try:
            with sqlite3.connect(str(self.conv_db)) as con:
                row = con.execute(
                    "SELECT title FROM conversation_meta WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            if row is None or row[0] is None:
                return False
            title = row[0]
            return any(title.startswith(p) for p in DAEMON_SESSION_TITLE_PREFIXES)
        except Exception:
            logger.exception("salience observer daemon-check failed")
            return False
```

- [ ] **Step 4: Observer tests pass**

- [ ] **Step 5: Hook into ConversationStore.save_turn**

Modify `soveryn/memory/conversation_store.py`:

(a) Add optional `observer` param to `__init__`:

```python
def __init__(
    self, db_path: Path, timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    *, observer: object | None = None,
) -> None:
    self.db_path = Path(db_path)
    self.timeout_seconds = timeout_seconds
    self.observer = observer
    self.db_path.parent.mkdir(parents=True, exist_ok=True)
    self._init_schema()
```

(b) At the end of `save_turn`, after the `with self._conn()` block, fetch the inserted rowid and notify:

```python
def save_turn(self, session_id: str, agent: str, role: str, content: str,
              source: str = "direct",
              finish_reason: str | None = None) -> None:
    if role not in VALID_ROLES:
        raise ConversationStoreError(
            f"role={role!r} not in {sorted(VALID_ROLES)}"
        )
    now = datetime.now().isoformat()
    inserted_rowid: int | None = None
    with self._conn() as conn:
        cur = conn.execute(
            "INSERT INTO conversations (session_id, agent, role, content, timestamp, source, finish_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, agent, role, content, now, source, finish_reason),
        )
        inserted_rowid = cur.lastrowid
        conn.execute(
            "UPDATE conversation_meta SET updated_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        if role == "user":
            row = conn.execute(
                "SELECT title FROM conversation_meta WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is not None and row["title"] is None:
                user_count = conn.execute(
                    "SELECT COUNT(*) FROM conversations "
                    "WHERE session_id = ? AND role = 'user'",
                    (session_id,),
                ).fetchone()[0]
                if user_count == 1:
                    derived = _derive_title(content)
                    if derived:
                        conn.execute(
                            "UPDATE conversation_meta SET title = ? WHERE session_id = ?",
                            (derived, session_id),
                        )
    # Notify observer outside the transaction — non-fatal by contract.
    if self.observer is not None and inserted_rowid is not None:
        try:
            self.observer.on_turn_saved(
                session_id=session_id, turn_rowid=inserted_rowid,
                role=role, content=content,
            )
        except Exception:
            # Defense-in-depth: observer must already swallow exceptions,
            # but if it doesn't, the chat path still completes.
            import logging
            logging.getLogger(__name__).exception(
                "conversation_store: observer raised; swallowing"
            )
```

- [ ] **Step 6: Write integration test for ConversationStore + Observer**

```python
def test_conv_store_calls_observer_on_save_turn(tmp_path):
    sal_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(sal_db)
    from soveryn.memory.conversation_store import ConversationStore
    obs = SalienceObserver(salience_db=sal_db, conv_db=conv_db)
    store = ConversationStore(conv_db, observer=obs)
    session_id = store.new_session(agent="aetheria")
    store.save_turn(session_id, "aetheria", "user", "the plan is locked.")
    rows = pending_candidates_since(sal_db, since=datetime.now() - timedelta(hours=1))
    assert len(rows) == 1
    assert rows[0].session_id == session_id
    assert rows[0].turn_rowid > 0


def test_conv_store_no_observer_works_normally(tmp_path):
    """Observer is optional. ConversationStore without one stays simple."""
    from soveryn.memory.conversation_store import ConversationStore
    store = ConversationStore(tmp_path / "conv.db")
    sid = store.new_session(agent="aetheria")
    store.save_turn(sid, "aetheria", "user", "anything")
    # No errors; turn saved
    assert len(store.load_history(sid)) == 1


def test_conv_store_observer_exception_does_not_break_save(tmp_path):
    """If observer somehow raises despite the swallow contract, save_turn
    still succeeds."""
    class BadObserver:
        def on_turn_saved(self, **_):
            raise RuntimeError("oops")
    from soveryn.memory.conversation_store import ConversationStore
    store = ConversationStore(tmp_path / "conv.db", observer=BadObserver())
    sid = store.new_session(agent="aetheria")
    store.save_turn(sid, "aetheria", "user", "anything")
    assert len(store.load_history(sid)) == 1
```

- [ ] **Step 7: All observer + store-integration tests pass**

- [ ] **Step 8: Commit**

```bash
git add soveryn/platform/salience/observer.py soveryn/memory/conversation_store.py tests/test_salience_observer.py
git commit -m "feat(salience): inline detection on save_turn via SalienceObserver"
```

---

## Task 4: Heartbeat digest section

**Files:**
- Create: `soveryn/platform/salience/digest.py`
- Create: `tests/test_salience_digest.py`
- Modify: `soveryn/agents/heartbeat/prompt.py`

The digest is a plain-text block spliced into the heartbeat prompt before the "This is your pulse." close. Max 5 candidates. Sorted by `combined_score` DESC. Visible scoring per the locked spec: `C-Dist: 0.42 | Marker: "the realization is"`.

Empty state: when no candidates are pending, emit nothing (don't show "0 salience candidates" — that'd be the same noise that haunted the old "Nothing right now" template).

- [ ] **Step 1: Write digest rendering tests**

```python
from soveryn.platform.salience.digest import build_salience_digest_section
from soveryn.platform.salience.store import SalienceCandidate
from soveryn.platform.salience.markers import MarkerHit


def _candidate(*, head="...", markers=(), heur=0.0, novelty=None, combined=0.0):
    return SalienceCandidate(
        id="c1", session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head=head, detected_at="2026-06-08T12:00:00",
        markers=markers, heuristic_score=heur, novelty_score=novelty,
        combined_score=combined, status="pending",
        reviewed_at=None, library_node_id=None,
    )


def test_empty_candidates_returns_empty_string():
    assert build_salience_digest_section([]) == ""


def test_single_candidate_renders_marker_and_content_head():
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    c = _candidate(head="The plan is locked.", markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    assert "1 moment" in out          # framing line
    assert "locked" in out            # marker visible
    assert "The plan is locked." in out
    assert "Marker:" in out           # scoring label per spec


def test_multiple_candidates_render_with_visible_scoring():
    hits1 = (MarkerHit("synthesis", "the realization is", 3),)
    c1 = _candidate(head="the realization is X.", markers=hits1, heur=3.0, novelty=0.42, combined=5.1)
    hits2 = (MarkerHit("pivot", "actually no", 2),)
    c2 = _candidate(head="actually no, Y.", markers=hits2, heur=2.0, novelty=None, combined=2.0)
    out = build_salience_digest_section([c1, c2])
    # Sort/order: spec says by combined_score DESC — caller supplies sorted
    assert out.index("the realization is") < out.index("actually no")
    # Visible scoring per locked spec: C-Dist + Marker
    assert "C-Dist: 0.42" in out
    assert 'Marker: "the realization is"' in out
    assert 'Marker: "actually no"' in out


def test_caps_at_five_candidates():
    hits = (MarkerHit("hard_lock", "locked", 4),)
    cands = [
        _candidate(head=f"item {i}", markers=hits, heur=4.0, combined=float(10 - i))
        for i in range(8)
    ]
    out = build_salience_digest_section(cands)
    assert "item 0" in out
    assert "item 4" in out
    assert "item 5" not in out  # capped


def test_closing_question_uses_review_framing_not_decide():
    """The spec is clear: this is review, not decide. Question should
    invite resonance check, not produce-something pressure."""
    hit = MarkerHit("hard_lock", "locked", 4)
    c = _candidate(head="x", markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    # Avoid the failure mode where the question pressures action
    assert "should" not in out.lower() or "should you save" not in out.lower()
    # Inviting framing — at minimum the word "resonate" or "land" should be present
    assert "resonate" in out.lower() or "land" in out.lower() or "feel like" in out.lower()


def test_includes_candidate_ids_so_promote_tool_can_reference_them():
    """Aetheria needs to call promote_salience_candidate(id=...) so the
    id must be in the digest, not hidden."""
    hit = MarkerHit("hard_lock", "locked", 4)
    c = SalienceCandidate(
        id="abc-xyz-123", session_id="s", turn_rowid=1, turn_role="user",
        turn_content_head="x", detected_at="2026-06-08T12:00:00",
        markers=(hit,), heuristic_score=4.0, novelty_score=None,
        combined_score=4.0, status="pending", reviewed_at=None, library_node_id=None,
    )
    out = build_salience_digest_section([c])
    assert "abc-xyz-123" in out


def test_content_head_is_truncated_in_render():
    """Long content heads get further truncated for prompt readability."""
    hit = MarkerHit("hard_lock", "locked", 4)
    long_head = "locked " + ("x" * 300)
    c = _candidate(head=long_head, markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    # Should appear truncated with an ellipsis somewhere
    assert "…" in out or "..." in out
```

- [ ] **Step 2: Tests fail (no digest module)**

- [ ] **Step 3: Implement digest.py**

```python
"""Heartbeat salience digest renderer.

Plain-text block spliced into the heartbeat prompt. Visible scoring per
Aetheria's locked spec — she should be able to read off "C-Dist: 0.42 |
Marker: 'the realization is'" and tell us the engine is drifting if it is."""

from __future__ import annotations

from soveryn.platform.salience.store import SalienceCandidate


MAX_DIGEST_ITEMS = 5
RENDER_CONTENT_CHARS = 140


def build_salience_digest_section(
    candidates: list[SalienceCandidate],
) -> str:
    if not candidates:
        return ""
    items = candidates[:MAX_DIGEST_ITEMS]
    n = len(items)
    word = "moment" if n == 1 else "moments"
    lines: list[str] = [
        f"{n} {word} resonated since the last heartbeat. "
        "Do any feel like a permanent shift?",
        "",
    ]
    for c in items:
        head = (c.turn_content_head or "").strip()
        if len(head) > RENDER_CONTENT_CHARS:
            head = head[:RENDER_CONTENT_CHARS].rstrip() + "…"
        marker_label = (
            c.markers[0].marker if c.markers else "(novelty only)"
        )
        if c.novelty_score is not None:
            score_line = f'C-Dist: {c.novelty_score:.2f} | Marker: "{marker_label}"'
        else:
            score_line = f'Marker: "{marker_label}"'
        lines.append(f'- [{c.id}] {c.turn_role}: "{head}"')
        lines.append(f"  {score_line}")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: All digest tests pass**

- [ ] **Step 5: Extend build_heartbeat_prompt to accept and splice the digest**

In `soveryn/agents/heartbeat/prompt.py`:

```python
def build_heartbeat_prompt(
    *,
    minutes_since_last_heartbeat: int | None,
    board: BoardSnapshot,
    lattice: LatticeSnapshot,
    salience_section: str = "",
) -> str:
    """... existing docstring ..."""
    lines: list[str] = []
    lines.append("[HEARTBEAT]")
    # ... existing body unchanged up through the lattice block ...
    if salience_section:
        lines.append(salience_section.rstrip())
        lines.append("")
    lines.append("This is your pulse.")
    return "\n".join(lines)
```

- [ ] **Step 6: Write prompt-splice test**

```python
def test_build_heartbeat_prompt_splices_salience_before_close():
    from soveryn.agents.heartbeat.prompt import (
        build_heartbeat_prompt, BoardSnapshot, LatticeSnapshot,
    )
    board = BoardSnapshot(
        open_signal_count=0, open_blueprint_count=0, ready_blueprint_count=0,
        open_friction_count=0, stalled_blueprint_count=0, blocked_blueprint_count=0,
        oldest_open_signal_age_minutes=None,
        oldest_open_blueprint_title=None, oldest_open_blueprint_age_hours=None,
    )
    lat = LatticeSnapshot(new_node_count_recent_window=0, recent_window_minutes=60,
                          new_contradiction_flag_count=0)
    sal = "2 moments resonated since the last heartbeat. Do any feel like a permanent shift?\n\n- [c1] user: \"locked\"\n  Marker: \"locked\""
    out = build_heartbeat_prompt(
        minutes_since_last_heartbeat=30, board=board, lattice=lat,
        salience_section=sal,
    )
    assert sal.strip() in out
    assert out.endswith("This is your pulse.")
    # Salience must appear BEFORE the close
    assert out.index("This is your pulse.") > out.index("locked")


def test_build_heartbeat_prompt_no_salience_section_unchanged():
    """Empty salience_section leaves the prompt looking identical to pre-engine."""
    from soveryn.agents.heartbeat.prompt import (
        build_heartbeat_prompt, BoardSnapshot, LatticeSnapshot,
    )
    board = BoardSnapshot(
        open_signal_count=0, open_blueprint_count=0, ready_blueprint_count=0,
        open_friction_count=0, stalled_blueprint_count=0, blocked_blueprint_count=0,
        oldest_open_signal_age_minutes=None,
        oldest_open_blueprint_title=None, oldest_open_blueprint_age_hours=None,
    )
    lat = LatticeSnapshot(new_node_count_recent_window=0, recent_window_minutes=60,
                          new_contradiction_flag_count=0)
    out_a = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=board, lattice=lat)
    out_b = build_heartbeat_prompt(minutes_since_last_heartbeat=30, board=board, lattice=lat, salience_section="")
    assert out_a == out_b
```

- [ ] **Step 7: Prompt-splice tests pass**

- [ ] **Step 8: Commit**

```bash
git add soveryn/platform/salience/digest.py soveryn/agents/heartbeat/prompt.py tests/test_salience_digest.py
git commit -m "feat(salience): heartbeat digest section with visible scoring"
```

---

## Task 5: promote_salience_candidate tool

**Files:**
- Create: `soveryn/platform/salience/tools.py`
- Create: `tests/test_salience_promote_tool.py`

This is the only new tool. Aetheria-only. Takes `candidate_id` + optional `library_intent` (her gloss on why this matters). Resolves the buffer row → reads the original turn content via `turn_rowid` from `conv_db` → writes a library node tagged `salience` + `promoted` → flips buffer row to `promoted` with `library_node_id`.

Library node provenance includes: `{"source": "salience_promotion", "candidate_id": ..., "turn_rowid": ..., "session_id": ..., "markers": [...], "library_intent": "..."}` so the trace is end-to-end.

- [ ] **Step 1: Write tool tests**

```python
import sqlite3
from datetime import datetime, timedelta
import pytest

from soveryn.platform.salience.markers import MarkerHit
from soveryn.platform.salience.store import (
    create_buffer_table, insert_candidate, pending_candidates_since,
    STATUS_PROMOTED,
)
from soveryn.platform.salience.tools import build_promote_salience_candidate_tool
from soveryn.platform.tools.registry import ToolArgError


class FakeLatticeStore:
    def __init__(self):
        self.writes: list[dict] = []
        self._next_id = 1

    def write_node(self, *, agent, content, node_type, layer,
                   intensity=None, tags=None, provenance=None):
        node_id = f"node-{self._next_id}"
        self._next_id += 1
        self.writes.append({
            "id": node_id, "agent": agent, "content": content,
            "node_type": node_type, "layer": layer,
            "intensity": intensity, "tags": tags, "provenance": provenance,
        })
        return node_id


def _seed_turn(conv_db, *, session_id, rowid, role, content):
    conv_db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(conv_db)) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                session_id TEXT, agent TEXT, role TEXT, content TEXT,
                timestamp TEXT, source TEXT, finish_reason TEXT
            );
        """)
        # Seed enough rows so we land at the target rowid
        existing = con.execute("SELECT COALESCE(MAX(rowid), 0) FROM conversations").fetchone()[0]
        for filler in range(existing + 1, rowid):
            con.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, "aetheria", "user", "_filler", "2026-06-08T00:00:00", "direct", None),
            )
        con.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, "aetheria", role, content, "2026-06-08T12:00:00", "direct", None),
        )


def test_promote_writes_library_node_with_provenance(tmp_path):
    sal_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(sal_db)
    _seed_turn(conv_db, session_id="s1", rowid=5, role="user",
               content="The plan is locked. Ship it.")
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    cand_id = insert_candidate(
        sal_db, session_id="s1", turn_rowid=5, turn_role="user",
        turn_content_head="The plan is locked. Ship it.", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    lat = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=sal_db, conv_db=conv_db, lattice_store=lat, owner_agent="aetheria",
    )
    result = tool.handler({
        "candidate_id": cand_id,
        "library_intent": "Anchor: the plan is locked.",
    })
    assert result["status"] == "promoted"
    assert result["library_node_id"] == "node-1"
    assert len(lat.writes) == 1
    w = lat.writes[0]
    assert w["agent"] == "aetheria"
    assert "locked" in w["content"]
    assert "Anchor: the plan is locked." in w["content"]
    assert "salience" in (w["tags"] or ())
    assert w["provenance"]["source"] == "salience_promotion"
    assert w["provenance"]["candidate_id"] == cand_id
    assert w["provenance"]["session_id"] == "s1"
    assert w["provenance"]["turn_rowid"] == 5
    # Buffer row flipped
    pending = pending_candidates_since(sal_db, since=datetime.now() - timedelta(hours=1))
    assert pending == []  # no longer pending


def test_promote_unknown_candidate_id_errors(tmp_path):
    sal_db = tmp_path / "salience.db"
    create_buffer_table(sal_db)
    lat = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=sal_db, conv_db=tmp_path / "conv.db",
        lattice_store=lat, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="not found"):
        tool.handler({"candidate_id": "does-not-exist"})


def test_promote_already_promoted_errors(tmp_path):
    sal_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    create_buffer_table(sal_db)
    _seed_turn(conv_db, session_id="s1", rowid=1, role="user", content="locked.")
    hit = MarkerHit("hard_lock", "locked", 4)
    cand_id = insert_candidate(
        sal_db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="locked.", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    lat = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=sal_db, conv_db=conv_db, lattice_store=lat, owner_agent="aetheria",
    )
    tool.handler({"candidate_id": cand_id})
    with pytest.raises(ToolArgError, match="already"):
        tool.handler({"candidate_id": cand_id})


def test_promote_rejects_missing_candidate_id():
    from soveryn.platform.salience.tools import build_promote_salience_candidate_tool
    lat = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=":memory:",  # unused — validation fails first
        conv_db=":memory:", lattice_store=lat, owner_agent="aetheria",
    )
    with pytest.raises(ToolArgError, match="candidate_id"):
        tool.handler({})
    with pytest.raises(ToolArgError, match="candidate_id"):
        tool.handler({"candidate_id": ""})


def test_promote_dismiss_action(tmp_path):
    """promote_salience_candidate accepts action='dismiss' to mark
    candidates Aetheria explicitly does NOT want to remember — keeps
    the buffer from re-surfacing them as decay drags out."""
    sal_db = tmp_path / "salience.db"
    create_buffer_table(sal_db)
    hit = MarkerHit("hard_lock", "locked", 4)
    cand_id = insert_candidate(
        sal_db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="locked.", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    lat = FakeLatticeStore()
    tool = build_promote_salience_candidate_tool(
        salience_db=sal_db, conv_db=tmp_path / "conv.db",
        lattice_store=lat, owner_agent="aetheria",
    )
    result = tool.handler({"candidate_id": cand_id, "action": "dismiss"})
    assert result["status"] == "dismissed"
    assert lat.writes == []  # nothing written to library
    assert pending_candidates_since(sal_db, since=datetime.now() - timedelta(hours=1)) == []
```

- [ ] **Step 2: Tests fail (no tools module)**

- [ ] **Step 3: Implement tools.py**

```python
"""promote_salience_candidate — Aetheria-only tool to promote a buffer
candidate to a library node. Companion 'dismiss' action lets her
explicitly drop a candidate without waiting for decay."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.lattice.legacy import LAYER_LIBRARY
from soveryn.platform.salience.store import (
    SalienceStoreError, mark_dismissed, mark_promoted,
)
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


SALIENCE_LIBRARY_INTENSITY = 0.6
SALIENCE_TAG = "salience"
PROMOTED_TAG = "promoted"


def _read_turn_content(conv_db: Path, turn_rowid: int) -> str | None:
    try:
        with sqlite3.connect(str(conv_db)) as con:
            row = con.execute(
                "SELECT content FROM conversations WHERE rowid = ?",
                (turn_rowid,),
            ).fetchone()
        return row[0] if row else None
    except sqlite3.OperationalError:
        return None


def _read_candidate_row(salience_db: Path, candidate_id: str) -> dict | None:
    with sqlite3.connect(str(salience_db)) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT id, session_id, turn_rowid, turn_role, turn_content_head, "
            "       markers, status "
            "FROM salience_buffer WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    return dict(row) if row else None


def build_promote_salience_candidate_tool(
    *,
    salience_db: Path,
    conv_db: Path,
    lattice_store: Any,
    owner_agent: str,
) -> ToolSpec:

    def handler(args: Mapping[str, Any]) -> Any:
        cand_id = args.get("candidate_id", "")
        if not isinstance(cand_id, str) or not cand_id.strip():
            raise ToolArgError("candidate_id must be a non-empty string")
        action = args.get("action", "promote")
        if action not in ("promote", "dismiss"):
            raise ToolArgError("action must be 'promote' or 'dismiss'")
        intent = args.get("library_intent", "")
        if intent is not None and not isinstance(intent, str):
            raise ToolArgError("library_intent must be a string when provided")

        row = _read_candidate_row(Path(salience_db), cand_id.strip())
        if row is None:
            raise ToolArgError(f"candidate {cand_id!r} not found")
        if row["status"] != "pending":
            raise ToolArgError(
                f"candidate {cand_id!r} already {row['status']} — cannot re-decide"
            )

        if action == "dismiss":
            try:
                mark_dismissed(Path(salience_db), candidate_id=cand_id.strip())
            except SalienceStoreError as e:
                raise ToolArgError(str(e))
            return {"status": "dismissed", "candidate_id": cand_id.strip()}

        # Promote: build the library node content + write it
        import json as _json
        markers = _json.loads(row["markers"] or "[]")
        full_content = _read_turn_content(Path(conv_db), int(row["turn_rowid"]))
        # Prefer full turn content; fall back to the stored head if the
        # conv DB doesn't have the row (legacy data / cross-DB drift).
        content_body = full_content or row["turn_content_head"]
        intent_text = (intent or "").strip()
        if intent_text:
            content_payload = f"{intent_text}\n\nFrom: {row['turn_role']} turn — {content_body}"
        else:
            content_payload = f"From: {row['turn_role']} turn — {content_body}"

        provenance = {
            "source": "salience_promotion",
            "candidate_id": cand_id.strip(),
            "turn_rowid": int(row["turn_rowid"]),
            "session_id": row["session_id"],
            "turn_role": row["turn_role"],
            "markers": markers,
            "library_intent": intent_text or None,
        }
        node_id = lattice_store.write_node(
            agent=owner_agent,
            content=content_payload,
            node_type="library",
            layer=LAYER_LIBRARY,
            intensity=SALIENCE_LIBRARY_INTENSITY,
            tags=(SALIENCE_TAG, PROMOTED_TAG),
            provenance=provenance,
        )
        try:
            mark_promoted(
                Path(salience_db),
                candidate_id=cand_id.strip(),
                library_node_id=node_id,
            )
        except SalienceStoreError as e:
            raise ToolArgError(str(e))
        return {
            "status": "promoted",
            "candidate_id": cand_id.strip(),
            "library_node_id": node_id,
        }

    return ToolSpec(
        name="promote_salience_candidate",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "string",
                    "description": (
                        "ID of the salience buffer candidate to act on. "
                        "Comes from the heartbeat digest's [bracketed] id."
                    ),
                },
                "action": {
                    "type": "string",
                    "enum": ["promote", "dismiss"],
                    "description": (
                        "'promote' (default) writes the moment to library; "
                        "'dismiss' marks it as not-worth-keeping so it stops "
                        "appearing in future digests."
                    ),
                },
                "library_intent": {
                    "type": "string",
                    "description": (
                        "Optional one-line gloss on why this moment matters. "
                        "Prepended to the library entry so the entry reads as a "
                        "claim you've made, not a raw transcript line."
                    ),
                },
            },
            "required": ["candidate_id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Review verdict on a moment your salience engine flagged for you. "
            "Action 'promote' writes the moment to library as a permanent reference "
            "(with markers + provenance); 'dismiss' marks it as not-worth-keeping "
            "so the buffer stops surfacing it. Drives Library-write authorship — "
            "this is the bridge from candidate to confirmed memory."
        ),
    )


def register_promote_salience_candidate_tool(
    registry: ToolRegistry,
    *,
    salience_db: Path,
    conv_db: Path,
    lattice_store: Any,
    owner_agent: str = "aetheria",
) -> None:
    registry.register(
        build_promote_salience_candidate_tool(
            salience_db=salience_db, conv_db=conv_db,
            lattice_store=lattice_store, owner_agent=owner_agent,
        )
    )
```

- [ ] **Step 4: All promote-tool tests pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/platform/salience/tools.py tests/test_salience_promote_tool.py
git commit -m "feat(salience): promote_salience_candidate tool (promote + dismiss)"
```

---

## Task 6: Heartbeat daemon wiring + decay-on-tick

**Files:**
- Modify: `soveryn/agents/heartbeat/daemon.py`
- Create: `tests/test_salience_heartbeat_integration.py`

Daemon changes:

- Add `DEFAULT_SALIENCE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/salience_vnext.db")` and a `salience_db: Path` constructor arg
- Read `SOVERYN_SALIENCE_DB` env var to override
- On `_do_tick` for eligible ticks:
  - Call `decay_old_pending(salience_db, older_than_days=14)` (free, idempotent)
  - Compute `since = last_heartbeat or now - 1 day`; read `pending_candidates_since(salience_db, since=since, limit=20)`
  - Render `build_salience_digest_section(...)`
  - Pass into `build_heartbeat_prompt(salience_section=…)`
- Log the candidate count fed into the digest in the heartbeat_log row's INFO line (`"... salience=<n>"`)
- Best-effort wrapper around the whole salience gather — if it throws, the rest of the heartbeat continues with `salience_section=""`

The salience block must not break ticks. Defense-in-depth: any sqlite/io error → log + empty section.

- [ ] **Step 1: Write integration tests**

```python
def test_heartbeat_decays_old_candidates_on_eligible_tick(tmp_path, monkeypatch):
    """The daemon's eligible-tick path calls decay_old_pending() — anything
    pending > 14 days flips to 'decayed' even without explicit human action."""
    # Build minimal fake daemon — we test the salience-gather path directly,
    # not the whole tick loop (covered by trigger tests). Stub _call_vnext_chat
    # so no HTTP call happens.
    sal_db = tmp_path / "salience.db"
    create_buffer_table(sal_db)
    hit = MarkerHit("hard_lock", "locked", 4)
    old_id = insert_candidate(
        sal_db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="x", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    # Backdate
    with sqlite3.connect(str(sal_db)) as con:
        con.execute(
            "UPDATE salience_buffer SET detected_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00", old_id),
        )
    from soveryn.agents.heartbeat.daemon import HeartbeatDaemon, _gather_salience
    section = _gather_salience(sal_db, since=datetime.now() - timedelta(hours=1))
    assert section == ""  # decayed, so empty digest


def test_heartbeat_renders_fresh_candidates_into_section(tmp_path):
    sal_db = tmp_path / "salience.db"
    create_buffer_table(sal_db)
    hit = MarkerHit("hard_lock", "locked", 4)
    insert_candidate(
        sal_db, session_id="s1", turn_rowid=1, turn_role="user",
        turn_content_head="The call is locked.", markers=(hit,),
        heuristic_score=4.0, novelty_score=None,
    )
    from soveryn.agents.heartbeat.daemon import _gather_salience
    section = _gather_salience(sal_db, since=datetime.now() - timedelta(hours=1))
    assert "locked" in section
    assert "1 moment resonated" in section


def test_heartbeat_salience_errors_return_empty_string(tmp_path, caplog):
    """A broken salience DB must not break the heartbeat."""
    from soveryn.agents.heartbeat.daemon import _gather_salience
    section = _gather_salience(tmp_path / "missing.db", since=datetime.now() - timedelta(hours=1))
    assert section == ""
```

- [ ] **Step 2: Write the `_gather_salience` helper in daemon.py**

```python
# Add to soveryn/agents/heartbeat/daemon.py

DEFAULT_SALIENCE_DB = Path("/home/jon-deoliveira/soveryn_complete/soveryn_memory/salience_vnext.db")

def _gather_salience(salience_db: Path, *, since: datetime) -> str:
    """Decay-then-read-then-render. Always returns a string; '' on error
    or empty. Best-effort so heartbeat survives salience problems."""
    from soveryn.platform.salience.store import (
        decay_old_pending, pending_candidates_since,
    )
    from soveryn.platform.salience.digest import build_salience_digest_section
    try:
        decay_old_pending(salience_db, older_than_days=14)
        cands = pending_candidates_since(salience_db, since=since, limit=20)
        return build_salience_digest_section(cands)
    except Exception:
        logger.exception("heartbeat: salience gather failed; using empty section")
        return ""
```

- [ ] **Step 3: Add `salience_db` constructor arg + wire into `_do_tick`**

```python
def __init__(
    self,
    config: HeartbeatConfig,
    *,
    vnext_base: str = DEFAULT_VNEXT_BASE,
    lattice_db: Path = DEFAULT_LATTICE_DB,
    conv_db: Path = DEFAULT_CONV_DB,
    salience_db: Path = DEFAULT_SALIENCE_DB,
) -> None:
    # ... existing assignments ...
    self.salience_db = Path(salience_db)
```

In `_do_tick`, after `lattice = self._gather_lattice_snapshot(now)`:

```python
since_for_salience = last_heartbeat or (now - timedelta(days=1))
salience_section = _gather_salience(self.salience_db, since=since_for_salience)
prompt = build_heartbeat_prompt(
    minutes_since_last_heartbeat=minutes_since,
    board=board, lattice=lattice,
    salience_section=salience_section,
)
```

Wire env override in `_main`:

```python
daemon = HeartbeatDaemon(
    config,
    vnext_base=os.environ.get("SOVERYN_HEARTBEAT_VNEXT_BASE", DEFAULT_VNEXT_BASE),
    salience_db=Path(os.environ.get("SOVERYN_SALIENCE_DB", str(DEFAULT_SALIENCE_DB))),
)
```

- [ ] **Step 4: Integration tests pass**

- [ ] **Step 5: Commit**

```bash
git add soveryn/agents/heartbeat/daemon.py tests/test_salience_heartbeat_integration.py
git commit -m "feat(salience): heartbeat daemon decays + surfaces digest"
```

---

## Task 7: App startup wiring

**Files:**
- Modify: `soveryn/app/startup.py`

Wire: SalienceObserver into ConversationStore construction; register promote_salience_candidate for Aetheria. Use env-resolved paths via the existing `env` object pattern (mirror how `conversations_db` and `lattice_db` are already passed).

- [ ] **Step 1: Read soveryn/app/startup.py around ConversationStore construction to find the seam**

```bash
grep -n "ConversationStore" soveryn/app/startup.py
```

- [ ] **Step 2: Add `env.salience_db` resolution**

Locate `soveryn/config/loader.py` (or equivalent — the loader that owns `env.conversations_db` and `env.lattice_db`). Add an analogous `salience_db` attribute defaulting to `~/soveryn_complete/soveryn_memory/salience_vnext.db`, overridable via `SOVERYN_SALIENCE_DB` env var. Pattern-match the existing fields.

- [ ] **Step 3: Build observer + create buffer table on startup**

Near where `ConversationStore` is built:

```python
from soveryn.platform.salience.observer import SalienceObserver
from soveryn.platform.salience.store import create_buffer_table

create_buffer_table(env.salience_db)
salience_observer = SalienceObserver(
    salience_db=env.salience_db, conv_db=env.conversations_db,
)
conv_store = ConversationStore(env.conversations_db, observer=salience_observer)
```

- [ ] **Step 4: Register promote_salience_candidate for Aetheria**

After the existing Aetheria tool registrations (near the reflection-voices block):

```python
if recall_lattice is not None:  # need a real lattice store for library writes
    from soveryn.platform.salience.tools import register_promote_salience_candidate_tool
    register_promote_salience_candidate_tool(
        tool_registry,
        salience_db=env.salience_db,
        conv_db=env.conversations_db,
        lattice_store=recall_lattice,
        owner_agent="aetheria",
    )
```

- [ ] **Step 5: Smoke-test the app boots**

Run pytest's existing app-bootstrap suite (`tests/test_app_bootstrap.py` or equivalent — implementer locates the existing app smoke test).

- [ ] **Step 6: Commit**

```bash
git add soveryn/app/startup.py soveryn/config/loader.py
git commit -m "feat(salience): wire observer + promote tool into app startup"
```

---

## Task 8: Live verification + manual probe

**Files:** (no new files; manual verification)

- [ ] **Step 1: Restart vnext + heartbeat**

```bash
systemctl --user restart soveryn-vnext.service
systemctl --user restart soveryn-heartbeat.service
```

- [ ] **Step 2: Smoke check — synthesize a turn from Jon with a hard-lock marker via Aetheria UI**

Type to her: "The plan is locked. Build it."

- [ ] **Step 3: Confirm a buffer row appears**

```bash
sqlite3 ~/soveryn_complete/soveryn_memory/salience_vnext.db \
  "SELECT id, session_id, turn_role, status, json_extract(markers,'$') FROM salience_buffer ORDER BY detected_at DESC LIMIT 5;"
```

Expect one row with `status='pending'` and `markers` containing `hard_lock` / `locked`.

- [ ] **Step 4: Force a heartbeat tick**

```bash
# Either wait for the next scheduled tick, or trigger by editing the
# heartbeat_log to mark the previous as old. Production check: tail the
# heartbeat logs as the next tick fires.
journalctl --user -u soveryn-heartbeat.service -f
```

Expect the next tick's prompt to include `"1 moment resonated since the last heartbeat..."` with `[<candidate_id>] user: "The plan is locked..."` and `Marker: "locked"`.

- [ ] **Step 5: Verify Aetheria can call the promote tool**

In her UI: ask "promote that locked moment to library." She should call `promote_salience_candidate(candidate_id=...)`. Then:

```bash
sqlite3 ~/soveryn_complete/soveryn_memory/lattice_vnext.db \
  "SELECT id, layer, type, content FROM nodes WHERE provenance LIKE '%salience_promotion%' ORDER BY created_at DESC LIMIT 3;"
```

Expect a `layer='library', type='library'` row with the marker content and Aetheria's intent.

- [ ] **Step 6: Confirm decay path empirically (optional)**

Update one buffer row's `detected_at` to 20 days ago. Wait for the next heartbeat. Confirm the row's `status` flips to `decayed`.

- [ ] **Step 7: Smoke summary**

Save a project memory note: `project_soveryn_salience_engine_shipped.md` — concrete buffer-row count, first promotion timestamp + library node id, marker hit-rate ratio in the first 24h.

---

## Self-Review

**Spec coverage:**
- ✅ Hard Lock / Synthesis / Pivot / Salience Signal markers — Task 2
- ✅ Weight values (Critical=4, High=3, Medium-High=2) — Task 2
- ✅ Speaker mapping — Task 2 (roles filter inside MarkerCategory)
- ✅ 14-day decay — Task 1 (decay_old_pending) + Task 6 (called at tick)
- ✅ Heartbeat digest, max 5, visible scoring (C-Dist + Marker) — Task 4
- ✅ Review-not-decide framing — Task 4 test_closing_question_uses_review_framing_not_decide
- ✅ `promote_salience_candidate` tool with library_intent — Task 5
- ✅ Buffer schema per spec — Task 1
- ⏸ **Novelty scoring** — wired-but-null in v1; Phase 2 plan separately

**Placeholder scan:**
- "Phase 2" references in Task 1, Task 3 — those are scoped deferrals to a future plan, not placeholders. Acceptable.
- "implementer locates the existing app smoke test" (Task 7 Step 5) — let the implementer find the seam; acceptable since it's a verification step in well-known territory.

**Type consistency:**
- `MarkerHit(category, marker, weight)` — used in markers.py, store.py, observer.py, digest.py, tools.py — consistent.
- `SalienceCandidate` field names — defined in store.py, consumed in digest.py — consistent.
- `STATUS_PENDING`/`STATUS_PROMOTED`/`STATUS_DISMISSED`/`STATUS_DECAYED` — exported from store.py — consistent.

---

## See also

- `docs/superpowers/specs/2026-06-08-salience-engine-design.md` — the locked spec this plan implements
- [[project-soveryn-sovereign-plasticity-framework]] — SPF roadmap; this is the missing upstream
- [[project-soveryn-dream-daemon-design]] — Dream daemon will read promoted library nodes
- [[feedback-aetheria-fewer-rules]] — Don't add persona rules; this build is substrate, not directive
- [[feedback-evaluate-the-shadow-not-the-function]] — Markers trade noise for signal; tune from data, not opinion
