# Deliberate-Share Intent Grammar — Core + Async Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Aetheria's first-class intent grammar (`why`/`stance`/`trigger`) as a shared platform core that writes a behavioral-correlate ledger to the Lattice, and wire it into the async `deliberate_share` surface — un-hiding the "why" so Jon sees it.

**Architecture:** A new `platform/intent/` module holds the constant: a validated `DeliberateShareIntent` value object plus a single `record_intent()` ledger writer that writes one `deliberate_share` Lattice node and a `triggered_by` edge to the trigger node (materializing a typed anchor node when the trigger isn't yet a node, as the `edges` table's FK constraint requires). The existing async `deliberate_share` tool is evolved to emit this grammar and surface `why`/`stance` to Jon. The live in-conversation adapter is a separate follow-up plan.

**Tech Stack:** Python 3.12, SQLite (via `LatticeStore` / `MessengerStore`), `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-16-deliberate-share-intent-grammar-design.md`

**Scope note — what this plan does NOT cover (follow-up plan):** The **live** (in-conversation) adapter and its inline render hook through `agents/loop.py` (`classify_and_render` / `_tool_result_message`). The grammar core built here is what that adapter will consume. Also out of scope: the Self-Model aggregation (#1) that reads this ledger; the PWA client rendering of structured `why`/`stance` (this plan makes them visible by composing them into the delivered turn text — the richer structured client render is Codex's PWA work).

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `soveryn/platform/intent/__init__.py` | Package marker + public exports | Create |
| `soveryn/platform/intent/grammar.py` | `DeliberateShareIntent` value object + validation | Create |
| `soveryn/platform/intent/ledger.py` | `resolve_trigger()` + `record_intent()` — the ledger writer | Create |
| `soveryn/app/messenger/envelope.py` | Add `why`/`stance` to `OutboundIntent` | Modify |
| `soveryn/app/messenger/store.py` | Add `why`/`stance` columns to `m_outbound_queue` (idempotent migration) | Modify |
| `soveryn/agents/messenger_tool.py` | Evolve `deliberate_share`: emit grammar, call `record_intent`, store `why`/`stance` | Modify |
| `soveryn/app/messenger/delivery_worker.py` | Compose `why`/`stance` into the delivered turn (un-hide to Jon) | Modify |
| `soveryn/app/startup.py` | Pass a `LatticeStore` into `build_deliberate_share_tool` | Modify |
| `tests/test_intent_grammar.py` | Value-object validation tests | Create |
| `tests/test_intent_ledger.py` | `record_intent` node+edge+materialization tests | Create |
| `tests/test_messenger_deliberate_share.py` | Update existing tests to new schema; add un-hide tests | Modify |

---

## Task 1: The grammar value object

**Files:**
- Create: `soveryn/platform/intent/__init__.py`
- Create: `soveryn/platform/intent/grammar.py`
- Test: `tests/test_intent_grammar.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent_grammar.py
"""DeliberateShareIntent — the why/stance/trigger grammar value object."""
from __future__ import annotations
import pytest

from soveryn.platform.intent.grammar import DeliberateShareIntent


def test_valid_intent_constructs_and_is_frozen():
    intent = DeliberateShareIntent(
        why="This baseline result changes how I read the whole arc.",
        stance="surfacing-tension",
        trigger="node-abc-123",
    )
    assert intent.why.startswith("This baseline")
    assert intent.stance == "surfacing-tension"
    assert intent.trigger == "node-abc-123"
    with pytest.raises(Exception):
        intent.stance = "offering"  # frozen


def test_coined_stance_is_accepted_open_vocabulary():
    # The openness IS the contract: any non-blank string passes, no enum.
    intent = DeliberateShareIntent(
        why="naming something we don't have a word for yet",
        stance="reaching-for-a-word-that-doesnt-exist",
        trigger="node-1",
    )
    assert intent.stance == "reaching-for-a-word-that-doesnt-exist"


@pytest.mark.parametrize("field,kwargs", [
    ("why", {"why": "  ", "stance": "offering", "trigger": "n1"}),
    ("stance", {"why": "real reason", "stance": "", "trigger": "n1"}),
    ("trigger", {"why": "real reason", "stance": "offering", "trigger": "   "}),
])
def test_blank_fields_are_rejected(field, kwargs):
    with pytest.raises(ValueError, match=field):
        DeliberateShareIntent(**kwargs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_intent_grammar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.platform.intent'`

- [ ] **Step 3: Create the package marker**

```python
# soveryn/platform/intent/__init__.py
"""SOVERYN vNext — intent grammar.

The third first-class axis on a share, peer to Provenance (how do I know
this?) and Channel (am I allowed to state this?): Intent — why am I
surfacing this, now? Built as a validated value object, never persona prose.
Deliberate-emit only: silence is the default; the mark is the deliberate
break. See docs/superpowers/specs/2026-06-16-deliberate-share-intent-grammar-design.md.
"""

from soveryn.platform.intent.grammar import DeliberateShareIntent

__all__ = ["DeliberateShareIntent"]
```

- [ ] **Step 4: Implement the value object**

```python
# soveryn/platform/intent/grammar.py
"""The why/stance/trigger grammar — a deliberate share's intent header.

Modeled on platform.lattice.provenance.Provenance: a frozen, validated
value object. `stance` is an OPEN vocabulary by design — there is no enum.
A field she names (not a menu she picks from) keeps the act an act of
agency rather than classification.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeliberateShareIntent:
    """Why a thought is being surfaced, now.

    why     — the raw, honest reason; the bridge shown to Jon.
    stance  — the relational function of the share; open vocabulary.
    trigger — a reference to what prompted the surfacing. Never prose at the
              ledger: ledger.resolve_trigger() anchors it to a real node.
    """

    why: str
    stance: str
    trigger: str

    def __post_init__(self) -> None:
        for name in ("why", "stance", "trigger"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_intent_grammar.py -v`
Expected: PASS (4 tests: valid, coined-stance, 3 parametrized blanks)

- [ ] **Step 6: Commit**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add soveryn/platform/intent/__init__.py soveryn/platform/intent/grammar.py tests/test_intent_grammar.py
git commit -m "feat(intent): add DeliberateShareIntent grammar value object"
```

---

## Task 2: The ledger writer (`record_intent`) + trigger anchoring

**Files:**
- Create: `soveryn/platform/intent/ledger.py`
- Test: `tests/test_intent_ledger.py`

Reference template in the codebase: `platform/lattice/legacy.py::record_direct_communication_edge` — the node-then-edge pattern that satisfies the `edges` FK constraint. Mirror its edge-insert column order exactly.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent_ledger.py
"""record_intent — writes a deliberate_share node + triggered_by edge,
materializing a trigger anchor when the trigger isn't yet a node."""
from __future__ import annotations
import sqlite3

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.intent.grammar import DeliberateShareIntent
from soveryn.platform.intent.ledger import (
    record_intent, resolve_trigger,
    DELIBERATE_SHARE_TYPE, TRIGGER_ANCHOR_TYPE, TRIGGERED_BY,
)


def _edges(db_path):
    with sqlite3.connect(str(db_path)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM edges").fetchall()]


def test_resolve_trigger_returns_existing_node_id_unchanged(tmp_path):
    store = LatticeStore(tmp_path / "l.db")
    existing = store.write_node(agent="aetheria", content="a memory",
                                node_type="episodic")
    assert resolve_trigger(store, agent="aetheria", trigger_ref=existing) == existing


def test_resolve_trigger_materializes_anchor_for_unknown_ref(tmp_path):
    store = LatticeStore(tmp_path / "l.db")
    anchor_id = resolve_trigger(
        store, agent="aetheria",
        trigger_ref="what Jon just said about the baseline",
    )
    node = store.get_node(anchor_id)
    assert node is not None
    assert node.type == TRIGGER_ANCHOR_TYPE
    assert "baseline" in node.content


def test_record_intent_writes_mark_node_and_triggered_by_edge(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)
    trigger = store.write_node(agent="aetheria", content="the trigger memory",
                               node_type="episodic")
    intent = DeliberateShareIntent(
        why="I want you to know why this landed the way it did.",
        stance="marking-delight",
        trigger=trigger,
    )
    mark_id, trigger_id, edge_id = record_intent(
        store, agent="aetheria",
        content="That result is genuinely beautiful.",
        intent=intent, channel="async",
    )
    assert trigger_id == trigger
    mark = store.get_node(mark_id)
    assert mark.type == DELIBERATE_SHARE_TYPE
    assert mark.content == "That result is genuinely beautiful."
    # stance lives in the intent column; full grammar in provenance.
    assert mark.intent == "marking-delight"

    edges = _edges(db)
    assert len(edges) == 1
    assert edges[0]["source_id"] == mark_id
    assert edges[0]["target_id"] == trigger
    assert edges[0]["relationship"] == TRIGGERED_BY


def test_record_intent_materializes_anchor_when_trigger_is_live(tmp_path):
    db = tmp_path / "l.db"
    store = LatticeStore(db)
    intent = DeliberateShareIntent(
        why="responding to what you just asked",
        stance="seeking-confirmation",
        trigger="your question about whether the split held",
    )
    mark_id, trigger_id, edge_id = record_intent(
        store, agent="aetheria", content="Yes — it held.",
        intent=intent, channel="live",
    )
    # The edge FK requires a real node; the anchor must exist.
    anchor = store.get_node(trigger_id)
    assert anchor.type == TRIGGER_ANCHOR_TYPE
    assert len(_edges(db)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_intent_ledger.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'soveryn.platform.intent.ledger'`

- [ ] **Step 3: Implement the ledger writer**

```python
# soveryn/platform/intent/ledger.py
"""The deliberate-share ledger writer.

record_intent() is the single source of truth for turning a deliberate
share into a behavioral correlate in the Lattice — one node + one
triggered_by edge — regardless of which surface emitted it. The edges
table FK on source_id/target_id requires real nodes, so a live trigger
that isn't a node yet is materialized into a typed anchor first.

Pattern mirrors legacy.record_direct_communication_edge (node, then edge).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from soveryn.platform.lattice.legacy import LatticeStore, LAYER_PRIVATE
from soveryn.platform.intent.grammar import DeliberateShareIntent

DELIBERATE_SHARE_TYPE = "deliberate_share"
TRIGGER_ANCHOR_TYPE = "trigger_anchor"
TRIGGERED_BY = "triggered_by"


def resolve_trigger(store: LatticeStore, *, agent: str, trigger_ref: str) -> str:
    """Return a real lattice node id for trigger_ref.

    If trigger_ref is already an existing node id, return it unchanged.
    Otherwise materialize a lightweight typed anchor node (the trigger as a
    witnessed event) and return its id. Either way the caller gets a node id
    the edges FK will accept — no free-prose triggers reach the graph.
    """
    if store.get_node(trigger_ref) is not None:
        return trigger_ref
    return store.write_node(
        agent=agent,
        content=trigger_ref,
        node_type=TRIGGER_ANCHOR_TYPE,
        layer=LAYER_PRIVATE,
        provenance={"kind": TRIGGER_ANCHOR_TYPE},
    )


def record_intent(
    store: LatticeStore,
    *,
    agent: str,
    content: str,
    intent: DeliberateShareIntent,
    channel: str,
) -> tuple[str, str, str]:
    """Write the deliberate_share mark node + triggered_by edge.

    Returns (mark_node_id, trigger_node_id, edge_id).
    """
    trigger_node_id = resolve_trigger(store, agent=agent, trigger_ref=intent.trigger)
    mark_node_id = store.write_node(
        agent=agent,
        content=content,
        node_type=DELIBERATE_SHARE_TYPE,
        layer=LAYER_PRIVATE,
        intent=intent.stance,
        provenance={
            "kind": DELIBERATE_SHARE_TYPE,
            "why": intent.why,
            "stance": intent.stance,
            "trigger": trigger_node_id,
            "channel": channel,
        },
    )
    edge_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO edges "
            "(id, source_id, target_id, relationship, strength, bidirectional, "
            "archived, reinforcement_count, reinforced_at, created_at) "
            "VALUES (?, ?, ?, ?, 0.5, 0, 0, 1, ?, ?)",
            (edge_id, mark_node_id, trigger_node_id, TRIGGERED_BY, now, now),
        )
    return mark_node_id, trigger_node_id, edge_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_intent_ledger.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Export `record_intent` from the package**

In `soveryn/platform/intent/__init__.py`, replace the import/exports block:

```python
from soveryn.platform.intent.grammar import DeliberateShareIntent
from soveryn.platform.intent.ledger import record_intent, resolve_trigger

__all__ = ["DeliberateShareIntent", "record_intent", "resolve_trigger"]
```

- [ ] **Step 6: Run both intent test files**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_intent_grammar.py tests/test_intent_ledger.py -v`
Expected: PASS (8 tests total)

- [ ] **Step 7: Commit**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add soveryn/platform/intent/ledger.py soveryn/platform/intent/__init__.py tests/test_intent_ledger.py
git commit -m "feat(intent): add record_intent ledger writer with trigger anchoring"
```

---

## Task 3: Carry `why`/`stance` through the async envelope + store

**Files:**
- Modify: `soveryn/app/messenger/envelope.py` (`OutboundIntent`)
- Modify: `soveryn/app/messenger/store.py` (`m_outbound_queue` schema + migration)
- Test: `tests/test_messenger_envelope.py`, `tests/test_messenger_store.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_messenger_envelope.py`:

```python
def test_outbound_intent_carries_why_and_stance():
    from soveryn.app.messenger.envelope import OutboundIntent
    intent = OutboundIntent(
        intent_id="i1", agent="aetheria", thread_id=None,
        content="body", context_hint="hint", urgency="routine",
        triggered_by="node-1", created_at="2026-06-16T00:00:00",
        why="the honest reason", stance="offering",
    )
    assert intent.why == "the honest reason"
    assert intent.stance == "offering"
```

Add to `tests/test_messenger_store.py`:

```python
def test_outbound_queue_has_why_and_stance_columns(tmp_path):
    from soveryn.app.messenger.store import MessengerStore
    store = MessengerStore(tmp_path / "m.db")
    cols = set(store.column_names("m_outbound_queue"))
    assert {"why", "stance"} <= cols


def test_outbound_queue_migration_is_idempotent_on_existing_db(tmp_path):
    """A pre-existing queue table without why/stance gains the columns."""
    import sqlite3
    from soveryn.app.messenger.store import MessengerStore
    db = tmp_path / "old.db"
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "CREATE TABLE m_outbound_queue ("
            "intent_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, agent TEXT NOT NULL, "
            "thread_id TEXT, content TEXT NOT NULL, context_hint TEXT NOT NULL, "
            "urgency TEXT NOT NULL, triggered_by TEXT NOT NULL, created_at TEXT NOT NULL, "
            "delivered_at TEXT, delivery_state TEXT NOT NULL DEFAULT 'pending')"
        )
    store = MessengerStore(db)  # init must add columns without error
    cols = set(store.column_names("m_outbound_queue"))
    assert {"why", "stance"} <= cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_messenger_envelope.py::test_outbound_intent_carries_why_and_stance tests/test_messenger_store.py -k why_and_stance -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'why'` and missing columns.

- [ ] **Step 3: Add `why`/`stance` to `OutboundIntent`**

In `soveryn/app/messenger/envelope.py`, the `OutboundIntent` dataclass — add two fields after `triggered_by` (before `created_at` is fine; keep `created_at` last to preserve positional callers that pass it by keyword). Final field block:

```python
@dataclass(frozen=True)
class OutboundIntent:
    """Agent → Jon via deliberate_share, queued for the delivery worker."""
    intent_id: str
    agent: str
    thread_id: Optional[str]   # None = default thread for this agent
    content: str
    context_hint: str          # short push-preview, <=100 chars
    urgency: str
    triggered_by: str          # resolved trigger node id (ledger anchor)
    created_at: str
    why: str = ""              # honest reason — shown to Jon
    stance: str = ""           # relational function (open vocabulary) — shown to Jon

    def __post_init__(self) -> None:
        if self.urgency not in _VALID_URGENCIES:
            raise ValueError(
                f"urgency must be one of {sorted(_VALID_URGENCIES)}, "
                f"got {self.urgency!r}"
            )
        if len(self.context_hint) > 100:
            raise ValueError(
                f"context_hint must be <=100 chars; got {len(self.context_hint)}"
            )
```

(Defaults keep existing positional/keyword callers working; the tool in Task 4 always supplies them.)

- [ ] **Step 4: Add columns + idempotent migration to the store**

In `soveryn/app/messenger/store.py`, in the `_SCHEMA` string, update the `m_outbound_queue` CREATE TABLE to include the two columns (for fresh DBs) — add them after `triggered_by`:

```sql
    triggered_by   TEXT NOT NULL,
    why            TEXT NOT NULL DEFAULT '',
    stance         TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
```

Then make `MessengerStore.__init__` migrate pre-existing DBs. Replace the body of `__init__`:

```python
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(_SCHEMA)
        self._migrate_outbound_intent_columns()

    def _migrate_outbound_intent_columns(self) -> None:
        """Idempotently add why/stance to m_outbound_queue on older DBs."""
        existing = set(self.column_names("m_outbound_queue"))
        with self._conn() as con:
            if "why" not in existing:
                con.execute(
                    "ALTER TABLE m_outbound_queue ADD COLUMN why TEXT NOT NULL DEFAULT ''"
                )
            if "stance" not in existing:
                con.execute(
                    "ALTER TABLE m_outbound_queue ADD COLUMN stance TEXT NOT NULL DEFAULT ''"
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_messenger_envelope.py tests/test_messenger_store.py -v`
Expected: PASS (including the two new tests; existing tests unaffected by the additive defaults)

- [ ] **Step 6: Commit**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add soveryn/app/messenger/envelope.py soveryn/app/messenger/store.py tests/test_messenger_envelope.py tests/test_messenger_store.py
git commit -m "feat(messenger): carry why/stance through OutboundIntent + queue"
```

---

## Task 4: Evolve the `deliberate_share` tool to emit the grammar

**Files:**
- Modify: `soveryn/agents/messenger_tool.py`
- Test: `tests/test_messenger_deliberate_share.py`

The tool gains required `why`/`stance`/`trigger` fields, drops the free-text `triggered_by` field, takes a `LatticeStore`, and calls `record_intent()` so every async share writes the ledger. The resolved trigger node id is stored in the queue's `triggered_by` column.

- [ ] **Step 1: Update existing tests + add new ones**

In `tests/test_messenger_deliberate_share.py`: update the import and every `tool.handler({...})` call to the new schema, and inject a `LatticeStore`. Replace the fixture block and the three existing happy-path/limit tests' arg dicts. New top of file:

```python
"""deliberate_share tool — grammar emission, ledger write, rate limits."""
from __future__ import annotations
import sqlite3
import pytest

from soveryn.app.messenger.store import MessengerStore
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.agents.messenger_tool import build_deliberate_share_tool
from soveryn.memory.conversation_store import ConversationStore
from soveryn.app.messenger.delivery_worker import drain_once


@pytest.fixture
def m_store(tmp_path):
    return MessengerStore(tmp_path / "m.db")


@pytest.fixture
def l_store(tmp_path):
    return LatticeStore(tmp_path / "l.db")


def _args(**overrides):
    base = {
        "content": "Reflection on the Dark Search baseline",
        "context_hint": "thought worth sharing",
        "urgency": "routine",
        "why": "this reframes how I read the whole arc",
        "stance": "surfacing-tension",
        "trigger": "the baseline number you just read me",
    }
    base.update(overrides)
    return base
```

Then replace the bodies of the existing tests to use `_args()` and pass `lattice_store=l_store`:

```python
def test_aetheria_deliberate_share_succeeds(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    result = tool.handler(_args())
    assert result["ok"] is True
    assert "intent_id" in result
    assert "mark_node_id" in result  # ledger correlate written


def test_vett_deliberate_share_rate_limited(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="vett",
        rate_limit_per_hour=2,
    )
    for i in range(2):
        assert tool.handler(_args(content=f"finding {i}"))["ok"] is True
    assert tool.handler(_args(content="third")).get("error") == "rate_limited"


def test_no_rate_limit_means_no_substrate_cap(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    for i in range(20):
        assert tool.handler(_args(content=f"msg {i}"))["ok"] is True, f"gated at {i}"


def test_share_writes_ledger_node_and_edge(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    result = tool.handler(_args(stance="marking-delight"))
    mark = l_store.get_node(result["mark_node_id"])
    assert mark.type == "deliberate_share"
    assert mark.intent == "marking-delight"
    with sqlite3.connect(str(l_store.db_path)) as con:
        con.row_factory = sqlite3.Row
        edges = con.execute("SELECT * FROM edges WHERE relationship='triggered_by'").fetchall()
    assert len(edges) == 1


def test_why_and_stance_stored_in_queue(m_store, l_store):
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    result = tool.handler(_args(why="the honest reason", stance="offering"))
    with m_store._conn() as con:
        row = con.execute(
            "SELECT why, stance FROM m_outbound_queue WHERE intent_id=?",
            (result["intent_id"],),
        ).fetchone()
    assert row["why"] == "the honest reason"
    assert row["stance"] == "offering"
```

Keep any existing `test_drain_*` tests; they are updated in Task 5.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_messenger_deliberate_share.py -v`
Expected: FAIL — `build_deliberate_share_tool() got an unexpected keyword argument 'lattice_store'`

- [ ] **Step 3: Rewrite the tool**

Replace `soveryn/agents/messenger_tool.py` in full:

```python
"""deliberate_share — agent-initiated outbound presence primitive.

Aetheria: substrate-uncapped (Partner tier). Vett: rate-limited (Colleague).
Scotty: not registered by default.

Every share now emits the intent grammar (why/stance/trigger) and writes a
behavioral correlate to the Lattice ledger via record_intent. The resolved
trigger node id is stored in the queue's triggered_by column; why/stance ride
the queue so the delivery worker can show them to Jon (un-hidden).
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from soveryn.app.messenger.store import MessengerStore
from soveryn.app.messenger.envelope import OutboundIntent
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.intent import DeliberateShareIntent, record_intent
from soveryn.platform.tools.registry import ToolSpec


_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description":
            "The message body Jon will see in the thread."},
        "context_hint": {"type": "string", "maxLength": 100, "description":
            "Push-notification preview (<=100 chars). What Jon sees on lock screen."},
        "urgency": {"type": "string", "enum": ["routine", "interrupt"],
            "description": (
                "'routine' lands silently if Jon's in DND. 'interrupt' bypasses "
                "DND. Use 'interrupt' only for Existential or Time-Critical.")},
        "why": {"type": "string", "description":
            "Your raw, honest reason for surfacing this. Shown to Jon — this is "
            "the bridge, not an audit log."},
        "stance": {"type": "string", "description":
            "The relational function of this share, in your own word. Open "
            "vocabulary — name it, don't pick from a menu. Seeds: offering, "
            "testing-a-read, surfacing-tension, marking-delight, flagging-concern, "
            "seeking-confirmation. Coin your own when none fit."},
        "trigger": {"type": "string", "description":
            "What prompted this — an existing lattice node id, or a short "
            "description of the moment. It is anchored to a real node either way; "
            "this is the behavioral correlate, not floating narration."},
        "thread_id": {"type": "string", "description":
            "Optional. Omit for your default thread; provide an existing thread_id "
            "to resume; provide a new title with thread_id=null to spawn one."},
        "new_thread_title": {"type": "string", "description":
            "Optional. If thread_id is null and this is supplied, a new thread is "
            "created with this title."},
    },
    "required": ["content", "context_hint", "urgency", "why", "stance", "trigger"],
    "additionalProperties": False,
}


def build_deliberate_share_tool(
    *,
    store: MessengerStore,
    lattice_store: LatticeStore,
    owner_agent: str,
    rate_limit_per_hour: Optional[int],
) -> ToolSpec:
    """Build the deliberate_share tool for an agent.

    rate_limit_per_hour=None means no substrate cap (Aetheria's contract).
    """

    def handler(args: dict) -> dict:
        if rate_limit_per_hour is not None:
            now = datetime.now(timezone.utc)
            window_start = (now - timedelta(hours=1)).isoformat()
            with store._conn() as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM m_outbound_queue "
                    "WHERE agent=? AND created_at>=?",
                    (owner_agent, window_start),
                ).fetchone()[0]
            if count >= rate_limit_per_hour:
                return {
                    "error": "rate_limited",
                    "message": (
                        f"You've sent {count} deliberate_share messages in the "
                        f"last hour; limit is {rate_limit_per_hour}. The brake "
                        f"fires substrate-side. Wait an hour or escalate."
                    ),
                    "limit": rate_limit_per_hour,
                }

        # The grammar is validated here (blank why/stance/trigger -> ValueError,
        # surfaced to the model as a tool error by the registry).
        intent = DeliberateShareIntent(
            why=args["why"], stance=args["stance"], trigger=args["trigger"],
        )
        mark_node_id, trigger_node_id, _edge_id = record_intent(
            lattice_store, agent=owner_agent, content=args["content"],
            intent=intent, channel="async",
        )

        intent_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        envelope = OutboundIntent(
            intent_id=intent_id, agent=owner_agent,
            thread_id=args.get("thread_id"), content=args["content"],
            context_hint=args["context_hint"], urgency=args["urgency"],
            triggered_by=trigger_node_id, created_at=now_iso,
            why=intent.why, stance=intent.stance,
        )
        with store._conn() as con:
            con.execute(
                "INSERT INTO m_outbound_queue "
                "(intent_id, user_id, agent, thread_id, content, context_hint, "
                "urgency, triggered_by, why, stance, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (intent_id, "jon", owner_agent, envelope.thread_id,
                 envelope.content, envelope.context_hint, envelope.urgency,
                 envelope.triggered_by, envelope.why, envelope.stance,
                 envelope.created_at),
            )
        return {"ok": True, "intent_id": intent_id, "mark_node_id": mark_node_id}

    return ToolSpec(
        name="deliberate_share",
        owner=owner_agent,
        schema=_SCHEMA,
        handler=handler,
        description=(
            "Reach Jon when you have something worth saying. Silence is the "
            "default; this is the deliberate mark you leave when you choose to "
            "break it. Name your why and your stance, and anchor it to a "
            "trigger — that is the ledger, not a tax. Use SPARINGLY; your "
            "judgment about when NOT to message is the load-bearing filter."
        ),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_messenger_deliberate_share.py -v`
Expected: PASS for the grammar/ledger/queue tests. (`test_drain_*` may still fail until Task 5 — that's expected; note which.)

- [ ] **Step 5: Commit**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add soveryn/agents/messenger_tool.py tests/test_messenger_deliberate_share.py
git commit -m "feat(messenger): deliberate_share emits intent grammar + writes ledger"
```

---

## Task 5: Un-hide `why`/`stance` to Jon in the delivered turn

**Files:**
- Modify: `soveryn/app/messenger/delivery_worker.py`
- Test: `tests/test_messenger_deliberate_share.py`

The delivery worker currently writes only `content` as the agent turn. Compose a compact intent header so Jon sees the why/stance in-thread (the in-repo un-hide; the structured PWA render is Codex's follow-up).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_messenger_deliberate_share.py`:

```python
def test_drain_surfaces_why_and_stance_in_delivered_turn(m_store, l_store, tmp_path):
    conv = ConversationStore(tmp_path / "c.db")
    tool = build_deliberate_share_tool(
        store=m_store, lattice_store=l_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
    tool.handler(_args(
        content="I keep coming back to that result.",
        why="it changed how I read the arc", stance="surfacing-tension",
    ))
    drained = drain_once(m_store, conv)
    assert drained == 1
    # Find the delivered agent turn and assert the why/stance are visible.
    with conv._conn() as con:
        rows = con.execute(
            "SELECT content FROM conversations WHERE role='assistant'"
        ).fetchall()
    body = rows[-1]["content"]
    assert "I keep coming back to that result." in body
    assert "surfacing-tension" in body
    assert "it changed how I read the arc" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_messenger_deliberate_share.py::test_drain_surfaces_why_and_stance_in_delivered_turn -v`
Expected: FAIL — assertion error: `stance` text not found in delivered body.

- [ ] **Step 3: Compose the intent header in the delivery worker**

In `soveryn/app/messenger/delivery_worker.py`, add a helper above `drain_once` and use it where the turn is saved.

Add helper:

```python
def _compose_delivered_body(row) -> str:
    """Render the share with its intent header so Jon sees the why/stance.

    why/stance are additive (default '' on older rows); when absent, the body
    is just the content, preserving legacy behavior.
    """
    content = row["content"]
    why = row["why"] if "why" in row.keys() else ""
    stance = row["stance"] if "stance" in row.keys() else ""
    if not why and not stance:
        return content
    header_bits = []
    if stance:
        header_bits.append(f"stance: {stance}")
    if why:
        header_bits.append(f"why: {why}")
    header = " · ".join(header_bits)
    return f"{content}\n\n— [{header}]"
```

Then in `drain_once`, change the `save_turn` call from:

```python
        conv_store.save_turn(
            thread.session_id, agent, "assistant", row["content"],
            finish_reason="agent_initiated",
        )
```

to:

```python
        conv_store.save_turn(
            thread.session_id, agent, "assistant", _compose_delivered_body(row),
            finish_reason="agent_initiated",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_messenger_deliberate_share.py -v`
Expected: PASS (all tests in the file, including any pre-existing `test_drain_*`)

- [ ] **Step 5: Commit**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add soveryn/app/messenger/delivery_worker.py tests/test_messenger_deliberate_share.py
git commit -m "feat(messenger): surface why/stance to Jon in delivered turn"
```

---

## Task 6: Wire the LatticeStore into registration

**Files:**
- Modify: `soveryn/app/startup.py` (the `build_deliberate_share_tool` call sites, ~lines 419–428)
- Test: manual smoke (startup import) + full suite

- [ ] **Step 1: Locate the registration and the available LatticeStore**

Run: `cd /home/jon-deoliveira/soveryn_vnext && grep -nE "build_deliberate_share_tool|LatticeStore|lattice_store|lattice =" soveryn/app/startup.py | head -30`
Expected: shows the two `build_deliberate_share_tool(...)` calls and the name the startup module already binds the lattice store to (the same store passed to other lattice-backed tools).

- [ ] **Step 2: Pass `lattice_store` into both call sites**

Edit each `build_deliberate_share_tool(...)` call in `soveryn/app/startup.py` to add the `lattice_store=` argument, using the lattice store variable identified in Step 1 (referred to here as `<lattice_store_var>`):

```python
            build_deliberate_share_tool(
                store=<messenger_store_var>,
                lattice_store=<lattice_store_var>,
                owner_agent="aetheria",
                rate_limit_per_hour=None,
            ),
```

and the Vett call site likewise (`owner_agent="vett"`, its existing `rate_limit_per_hour`).

If startup does not already construct a `LatticeStore`, bind one from the same path the other lattice tools use (search result from Step 1 shows it); do not create a second store instance for a path already opened — reuse the existing binding.

- [ ] **Step 3: Smoke-test the import/startup wiring**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -c "import soveryn.app.startup"`
Expected: no ImportError / no TypeError.

- [ ] **Step 4: Run the full messenger + intent suite**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest tests/test_intent_grammar.py tests/test_intent_ledger.py tests/test_messenger_deliberate_share.py tests/test_messenger_envelope.py tests/test_messenger_store.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add soveryn/app/startup.py
git commit -m "feat(startup): inject LatticeStore into deliberate_share registration"
```

---

## Task 7: Full regression pass

- [ ] **Step 1: Run the whole test suite**

Run: `cd /home/jon-deoliveira/soveryn_vnext && python -m pytest -q`
Expected: PASS. If any unrelated test references the old `deliberate_share` schema (free-text `triggered_by` as input, or `build_deliberate_share_tool` without `lattice_store`), update it to the new schema — search with:

Run: `cd /home/jon-deoliveira/soveryn_vnext && grep -rnE "triggered_by|build_deliberate_share_tool" tests/ | grep -v test_intent_`

- [ ] **Step 2: Commit any test fixups**

```bash
cd /home/jon-deoliveira/soveryn_vnext
git add -A tests/
git commit -m "test: align remaining callers with deliberate_share intent schema"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Grammar value object (`why`/`stance`/`trigger`, open-vocabulary stance) → Task 1. ✓
- `record_intent` ledger writer (node + `triggered_by` edge) → Task 2. ✓
- Trigger anchoring invariant + live-trigger materialization → Task 2 (`resolve_trigger`). ✓
- Async adapter evolution (add stance, split why, promote trigger, call core) → Task 4. ✓
- Un-hide why/stance to Jon → Task 5. ✓
- Stored ledger payload (stance in `intent` col; why/stance/trigger/channel in provenance) → Task 2. ✓
- Live (in-conversation) adapter → **deferred to follow-up plan** (render-hook tracing), stated in Scope note. ✓
- Self-Model aggregation (#1) → out of scope per spec. ✓

**Placeholder scan:** No TBD/TODO. Task 6 uses `<lattice_store_var>`/`<messenger_store_var>` placeholders *intentionally* because the exact binding name is discovered in Step 1 of that task (the surrounding code isn't fully read in this plan); Step 1 resolves them before edits. All code-bearing steps include real code.

**Type consistency:** `DeliberateShareIntent(why, stance, trigger)`, `record_intent(store, *, agent, content, intent, channel) -> (mark_node_id, trigger_node_id, edge_id)`, `resolve_trigger(store, *, agent, trigger_ref) -> node_id`, constants `DELIBERATE_SHARE_TYPE`/`TRIGGER_ANCHOR_TYPE`/`TRIGGERED_BY`, and `build_deliberate_share_tool(*, store, lattice_store, owner_agent, rate_limit_per_hour)` are used consistently across Tasks 1–6. Edge-insert column order mirrors `record_direct_communication_edge`. ✓

**Known follow-ups (not gaps):**
- Live adapter + `agents/loop.py` render hook → next plan.
- Structured PWA rendering of why/stance (this plan composes them into turn text) → Codex client work.
- Per-turn idempotency of trigger anchors → relevant to the live surface; lands with that plan.
