"""Tests for Phase E: webhook-driven inter-agent triggering.

Spec: docs/superpowers/specs/2026-06-01-coord-webhooks.md

Covers:
- Event emission shape from each store mutation
- coord_event_log audit trail
- Routing rule table
- Dispatcher webhook session lifecycle + prompt construction
- Worker chain-depth cap
- Worker error isolation
"""

import sqlite3
import threading
import time
from unittest.mock import MagicMock

import pytest

from soveryn.platform.coordination import (
    CoordBoard,
    CoordinationStore,
    CoordStatus,
)
from soveryn.platform.coordination.dispatcher import (
    AgentDispatcher,
    build_webhook_prompt,
)
from soveryn.platform.coordination.events import (
    MAX_CHAIN_DEPTH,
    ChainContext,
    CoordEvent,
    CoordEventKind,
    InMemoryEventBus,
    chain_context,
    get_active_chain,
)
from soveryn.platform.coordination.routing import route
from soveryn.platform.coordination.worker import CoordEventWorker
from soveryn.platform.lattice.legacy import LatticeStore


@pytest.fixture
def lattice_path(tmp_path):
    db_path = tmp_path / "test_lattice.db"
    LatticeStore(db_path)
    return db_path


@pytest.fixture
def bus():
    return InMemoryEventBus()


@pytest.fixture
def store(lattice_path, bus):
    return CoordinationStore(lattice_path, event_bus=bus)


# ─── Event emission ─────────────────────────────────────────────────────────

def test_create_node_emits_node_created_event(store, bus):
    store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    events = bus.drain()
    assert len(events) == 1
    assert events[0].kind == CoordEventKind.NODE_CREATED
    assert events[0].actor_agent == "vett"
    assert events[0].payload["board"] == "Signal"


def test_update_status_emits_status_changed_event(store, bus):
    n = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    bus.drain()
    store.update_status(n.id, CoordStatus.REFINING, acting_agent="aetheria")
    events = bus.drain()
    assert any(e.kind == CoordEventKind.STATUS_CHANGED for e in events)
    s = next(e for e in events if e.kind == CoordEventKind.STATUS_CHANGED)
    assert s.payload["old_status"] == "Open"
    assert s.payload["new_status"] == "Refining"


def test_promote_emits_promoted_event(store, bus):
    sig = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    bus.drain()
    store.promote_node(sig.id, target_board=CoordBoard.BLUEPRINT,
                        new_content="plan", acting_agent="aetheria")
    events = bus.drain()
    promoted = [e for e in events if e.kind == CoordEventKind.PROMOTED]
    assert len(promoted) == 1
    assert promoted[0].payload["target_board"] == "Blueprint"
    assert promoted[0].payload["source_node_id"] == sig.id


def test_archive_emits_archived_event(store, bus):
    n = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    bus.drain()
    store.archive_node(n.id, lesson_learned_content="learned",
                        acting_agent="aetheria")
    events = bus.drain()
    archived = [e for e in events if e.kind == CoordEventKind.ARCHIVED]
    assert len(archived) == 1


def test_add_block_emits_block_added_event(store, bus):
    f = store.create_node(board=CoordBoard.FRICTION, owner="aetheria",
                          content="contradiction")
    bp = store.create_node(board=CoordBoard.BLUEPRINT, owner="scotty",
                            content="plan")
    bus.drain()
    store.add_block(f.id, bp.id, acting_agent="aetheria")
    events = bus.drain()
    blocks = [e for e in events if e.kind == CoordEventKind.BLOCK_ADDED]
    assert len(blocks) == 1
    assert blocks[0].payload["blocks_blueprint_id"] == bp.id


def test_null_bus_is_default_when_unset(lattice_path):
    """A store with no event_bus argument should still work — events go to
    NullEventBus (no-op). Confirms the optional plumbing doesn't break the
    standalone use case."""
    s = CoordinationStore(lattice_path)  # no bus
    n = s.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    assert n.id  # didn't raise


# ─── Audit log ──────────────────────────────────────────────────────────────

def test_event_log_row_written_on_emission(store, lattice_path):
    n = store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="lead")
    con = sqlite3.connect(str(lattice_path))
    rows = con.execute(
        "SELECT kind, node_id, actor_agent, chain_depth, parent_event_id "
        "FROM coord_event_log WHERE node_id = ?", (n.id,),
    ).fetchall()
    con.close()
    assert len(rows) == 1
    assert rows[0][0] == "node_created"
    assert rows[0][1] == n.id
    assert rows[0][2] == "vett"
    assert rows[0][3] == 0  # depth 0 for user-triggered
    assert rows[0][4] is None  # no parent


def test_event_log_records_chain_depth_under_chain_context(store, lattice_path):
    """When a mutation runs inside a chain_context (simulating dispatcher
    invocation), the event should carry chain_depth=parent+1 and the parent id."""
    ctx = ChainContext(parent_event_id="parent-uuid-1234", chain_depth=2)
    with chain_context(ctx):
        n = store.create_node(board=CoordBoard.SIGNAL, owner="vett",
                              content="chained")
    con = sqlite3.connect(str(lattice_path))
    row = con.execute(
        "SELECT chain_depth, parent_event_id FROM coord_event_log WHERE node_id = ?",
        (n.id,),
    ).fetchone()
    con.close()
    assert row[0] == 3  # parent_depth + 1
    assert row[1] == "parent-uuid-1234"


# ─── Routing rules ──────────────────────────────────────────────────────────

def _event(kind: CoordEventKind, actor: str, payload: dict) -> CoordEvent:
    return CoordEvent.new(kind=kind, node_id="n-1", actor_agent=actor,
                           payload=payload)


def test_route_signal_created_goes_to_aetheria_triage():
    e = _event(CoordEventKind.NODE_CREATED, "vett", {"board": "Signal"})
    assert route(e) == ("aetheria",)


def test_route_blueprint_created_goes_to_aetheria_review():
    """Blueprint created without an owner field — only review fires."""
    e = _event(CoordEventKind.NODE_CREATED, "scotty", {"board": "Blueprint"})
    assert route(e) == ("aetheria",)


def test_route_self_triggering_filtered_out():
    """If Aetheria creates a Blueprint herself, the Blueprint-review rule
    would route to her — but the actor-equals-destination filter must
    drop that."""
    e = _event(CoordEventKind.NODE_CREATED, "aetheria", {"board": "Blueprint"})
    assert route(e) == ()


def test_route_blueprint_created_with_vett_owner_routes_to_vett_too():
    """Owner-aware routing (2026-06-04): NODE_CREATED on Blueprint routes
    to aetheria (review) AND the owner, so Vett gets woken when Aetheria
    creates Blueprint work for him."""
    e = _event(CoordEventKind.NODE_CREATED, "aetheria",
                {"board": "Blueprint", "owner": "vett"})
    # aetheria self-filters out (she's the actor); vett remains.
    assert route(e) == ("vett",)


def test_route_blueprint_created_by_vett_with_scotty_owner_routes_both_minus_actor():
    """Vett creates a Blueprint with Scotty as owner: aetheria (review) +
    scotty (start). Vett is the actor and self-filters out anyway."""
    e = _event(CoordEventKind.NODE_CREATED, "vett",
                {"board": "Blueprint", "owner": "scotty"})
    assert route(e) == ("aetheria", "scotty")


def test_route_blueprint_created_with_owner_same_as_aetheria_dedupes():
    """If owner == aetheria, she shouldn't appear twice in the destination
    tuple (review + owner). The dedup makes this deterministic."""
    e = _event(CoordEventKind.NODE_CREATED, "scotty",
                {"board": "Blueprint", "owner": "aetheria"})
    assert route(e) == ("aetheria",)


def test_route_promoted_to_blueprint_routes_to_target_owner():
    """The old universal-to-scotty rule is gone. Routes to whoever the
    promoter assigned as target_owner."""
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Blueprint", "source_board": "Signal",
                 "target_owner": "scotty"})
    assert route(e) == ("scotty",)


def test_route_promoted_to_blueprint_routes_to_vett_when_owner_is_vett():
    """Aetheria promoting Signal -> Blueprint with target_owner=vett
    wakes Vett, not Scotty. The whole point of the owner-aware refactor."""
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Blueprint", "source_board": "Signal",
                 "target_owner": "vett"})
    assert route(e) == ("vett",)


def test_route_promoted_to_blueprint_without_target_owner_routes_nowhere():
    """Pre-refactor / hand-constructed events with no target_owner used to
    route universally to scotty. New behavior: nowhere (no fallback).
    Production paths always supply target_owner via promote_node's
    effective_owner default."""
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Blueprint", "source_board": "Signal"})
    assert route(e) == ()


def test_route_promoted_self_filters_when_target_owner_is_actor():
    """Aetheria promotes a Signal to a Blueprint she owns herself —
    self-filter drops her. Same shape as the create-self case."""
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Blueprint", "source_board": "Signal",
                 "target_owner": "aetheria"})
    assert route(e) == ()


def test_route_normalizes_stylized_target_owner_v_dot_e_dot_t_dot_t():
    """The 2026-06-04 silent-dispatch bug: Aetheria wrote target_owner as
    'V.E.T.T.' (her stylization), router accepted it verbatim, dispatcher
    couldn't find an agent loop named 'V.E.T.T.', failed silently.
    Normalization at the routing layer makes the dispatch work."""
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Blueprint", "source_board": "Signal",
                 "target_owner": "V.E.T.T."})
    assert route(e) == ("vett",)


def test_route_normalizes_uppercase_owner_on_node_created():
    """Same normalization on NODE_CREATED Blueprint owner field."""
    e = _event(CoordEventKind.NODE_CREATED, "aetheria",
                {"board": "Blueprint", "owner": "VETT"})
    # aetheria self-filters; vett (normalized) remains.
    assert route(e) == ("vett",)


def test_route_normalizes_owner_with_whitespace_and_mixed_case():
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Blueprint", "source_board": "Signal",
                 "target_owner": "  Scotty  "})
    assert route(e) == ("scotty",)


def test_normalize_agent_name_handles_edge_cases():
    """Direct test of the normalizer for completeness."""
    from soveryn.platform.coordination.routing import normalize_agent_name
    assert normalize_agent_name("V.E.T.T.") == "vett"
    assert normalize_agent_name("Vett") == "vett"
    assert normalize_agent_name("VETT") == "vett"
    assert normalize_agent_name("  vett  ") == "vett"
    assert normalize_agent_name("V. E. T. T.") == "vett"
    assert normalize_agent_name("aetheria") == "aetheria"
    assert normalize_agent_name("") is None
    assert normalize_agent_name("   ") is None
    assert normalize_agent_name(None) is None
    assert normalize_agent_name(42) is None


def test_route_promoted_to_friction_does_not_auto_trigger():
    """Friction promotions are arbitration territory; Aetheria handles them
    through chat, not webhook (per the locked rules)."""
    e = _event(CoordEventKind.PROMOTED, "aetheria",
                {"target_board": "Friction", "source_board": "Signal"})
    assert route(e) == ()


def test_route_status_open_to_refining_on_blueprint_goes_to_scotty():
    e = _event(CoordEventKind.STATUS_CHANGED, "aetheria", {
        "board": "Blueprint", "old_status": "Open", "new_status": "Refining",
    })
    assert route(e) == ("scotty",)


def test_route_status_refining_to_ready_on_blueprint_goes_to_aetheria():
    e = _event(CoordEventKind.STATUS_CHANGED, "scotty", {
        "board": "Blueprint", "old_status": "Refining", "new_status": "Ready",
    })
    assert route(e) == ("aetheria",)


def test_route_block_added_goes_to_aetheria_arbitration():
    e = _event(CoordEventKind.BLOCK_ADDED, "vett",
                {"blocks_blueprint_id": "bp-1"})
    assert route(e) == ("aetheria",)


def test_route_archived_does_not_auto_trigger():
    e = _event(CoordEventKind.ARCHIVED, "aetheria",
                {"board": "Blueprint", "lesson_id": "l-1"})
    assert route(e) == ()


def test_route_status_change_on_non_blueprint_board_does_not_trigger():
    e = _event(CoordEventKind.STATUS_CHANGED, "aetheria", {
        "board": "Signal", "old_status": "Open", "new_status": "Refining",
    })
    assert route(e) == ()


# ─── Chain context thread-local ─────────────────────────────────────────────

def test_chain_context_isolates_per_thread():
    """The active chain is thread-local — one thread setting context should
    not leak into another's view."""
    saw_from_thread = []

    def worker():
        saw_from_thread.append(get_active_chain())

    ctx = ChainContext(parent_event_id="p-1", chain_depth=1)
    with chain_context(ctx):
        assert get_active_chain() == ctx
        t = threading.Thread(target=worker)
        t.start()
        t.join()
    assert get_active_chain() is None  # restored on exit
    assert saw_from_thread == [None]  # other thread saw nothing


# ─── Dispatcher prompt construction ─────────────────────────────────────────

def test_build_webhook_prompt_includes_kind_and_actor():
    e = _event(CoordEventKind.NODE_CREATED, "vett", {
        "board": "Signal", "content_head": "EU grant lead",
    })
    p = build_webhook_prompt(e)
    assert "node_created" in p
    assert "Actor: vett" in p
    assert "Board: Signal" in p
    assert "EU grant lead" in p
    assert "Chain depth" in p


def test_build_webhook_prompt_includes_status_transition_when_present():
    e = _event(CoordEventKind.STATUS_CHANGED, "scotty", {
        "board": "Blueprint", "old_status": "Refining", "new_status": "Ready",
    })
    p = build_webhook_prompt(e)
    assert "Refining -> Ready" in p


# ─── Dispatcher behavior with mocked AgentLoop ─────────────────────────────

class _FakeConvStore:
    def __init__(self):
        self.sessions = {}
        self._n = 0

    def new_session(self, agent, title=None):
        self._n += 1
        sid = f"sid-{self._n}"
        self.sessions[sid] = {"agent": agent, "title": title}
        return sid

    def get_session(self, sid):
        if sid in self.sessions:
            return MagicMock(session_id=sid, agent=self.sessions[sid]["agent"])
        return None


def test_dispatcher_reuses_webhook_session_across_events():
    conv = _FakeConvStore()
    loop = MagicMock()
    loop.process_message.return_value = MagicMock(content="ok")
    disp = AgentDispatcher({"aetheria": loop}, conv)

    e1 = _event(CoordEventKind.NODE_CREATED, "vett", {"board": "Signal"})
    e2 = _event(CoordEventKind.NODE_CREATED, "vett", {"board": "Signal"})
    disp.dispatch(e1, "aetheria")
    disp.dispatch(e2, "aetheria")
    # Only one session was created
    assert len(conv.sessions) == 1
    # process_message was called twice on the same session
    sids_seen = [call.args[0] for call in loop.process_message.call_args_list]
    assert sids_seen[0] == sids_seen[1]


def test_dispatcher_returns_none_for_unknown_agent():
    conv = _FakeConvStore()
    disp = AgentDispatcher({}, conv)
    e = _event(CoordEventKind.NODE_CREATED, "vett", {"board": "Signal"})
    assert disp.dispatch(e, "scotty") is None


def test_dispatcher_sets_chain_context_during_invocation():
    """During process_message, the chain context should be active so any
    coord-tool emissions inherit the chain metadata."""
    conv = _FakeConvStore()
    captured: list[ChainContext | None] = []

    def fake_process(sid, msg):
        captured.append(get_active_chain())
        return MagicMock(content="ok")

    loop = MagicMock()
    loop.process_message.side_effect = fake_process
    disp = AgentDispatcher({"aetheria": loop}, conv)
    e = _event(CoordEventKind.NODE_CREATED, "vett", {"board": "Signal"})
    disp.dispatch(e, "aetheria")
    assert captured[0] is not None
    assert captured[0].parent_event_id == e.id
    assert captured[0].chain_depth == e.chain_depth
    # After dispatch, chain is restored to None
    assert get_active_chain() is None


# ─── Worker behavior ────────────────────────────────────────────────────────

def test_worker_drops_events_over_chain_depth_cap(lattice_path, bus):
    """Events with chain_depth >= MAX_CHAIN_DEPTH should be dropped without
    dispatch."""
    conv = _FakeConvStore()
    loop = MagicMock()
    loop.process_message.return_value = MagicMock(content="ok")
    disp = AgentDispatcher({"aetheria": loop, "scotty": loop, "vett": loop}, conv)
    w = CoordEventWorker(bus, disp, lattice_db_path=lattice_path,
                          poll_interval_seconds=0.05)
    # Manually insert an event log row so _mark_triggered has something to update
    runaway = CoordEvent.new(
        kind=CoordEventKind.NODE_CREATED,
        node_id="n-runaway",
        actor_agent="vett",
        payload={"board": "Signal"},
        chain_depth=MAX_CHAIN_DEPTH,  # at cap
    )
    con = sqlite3.connect(str(lattice_path))
    con.execute(
        "INSERT INTO coord_event_log "
        "(id, kind, node_id, actor_agent, chain_depth, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (runaway.id, runaway.kind.value, runaway.node_id, runaway.actor_agent,
         runaway.chain_depth, runaway.timestamp),
    )
    con.commit()
    con.close()
    bus.emit(runaway)
    w.start()
    # Give the worker a moment to process
    time.sleep(0.5)
    w.stop()
    # Dispatcher was NEVER invoked because event was dropped
    loop.process_message.assert_not_called()
    # Event log row was updated to reflect the drop
    con = sqlite3.connect(str(lattice_path))
    row = con.execute(
        "SELECT triggered_agents FROM coord_event_log WHERE id = ?",
        (runaway.id,),
    ).fetchone()
    con.close()
    assert row[0] == "DROPPED: chain_depth cap"


def test_worker_isolates_dispatch_errors(lattice_path, bus):
    """One failing dispatch should be logged but not crash the worker or
    drop future events."""
    conv = _FakeConvStore()
    bad_loop = MagicMock()
    bad_loop.process_message.side_effect = RuntimeError("boom")
    good_loop = MagicMock()
    good_loop.process_message.return_value = MagicMock(content="ok")
    disp = AgentDispatcher(
        {"aetheria": bad_loop, "scotty": good_loop, "vett": MagicMock()}, conv,
    )
    w = CoordEventWorker(bus, disp, lattice_db_path=lattice_path,
                          poll_interval_seconds=0.05)

    # Insert audit rows + emit two events
    # NODE_CREATED on Signal routes to aetheria (bad_loop).
    # PROMOTED to Blueprint with target_owner=scotty routes to scotty
    # (good_loop) — target_owner is required under the 2026-06-04 owner-
    # aware routing refactor.
    for kind, target_board in [(CoordEventKind.NODE_CREATED, "Signal"),
                                (CoordEventKind.PROMOTED, None)]:
        e = CoordEvent.new(
            kind=kind, node_id=f"n-{kind.value}", actor_agent="vett",
            payload={"board": target_board} if target_board else
                    {"target_board": "Blueprint", "source_board": "Signal",
                     "target_owner": "scotty"},
        )
        con = sqlite3.connect(str(lattice_path))
        con.execute(
            "INSERT INTO coord_event_log "
            "(id, kind, node_id, actor_agent, chain_depth, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (e.id, e.kind.value, e.node_id, e.actor_agent, e.chain_depth,
             e.timestamp),
        )
        con.commit()
        con.close()
        bus.emit(e)
    w.start()
    time.sleep(0.6)
    w.stop()
    # bad_loop was called and crashed; good_loop was called too — worker
    # didn't poison-pill on the bad dispatch
    assert bad_loop.process_message.called
    assert good_loop.process_message.called
