"""Tests for RepresentationDaemon._do_tick — no HTTP, no real model.

All tests use injected fake stores, chat_fn, embed_fn, and a fixed 'now'.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from soveryn.agents.representation.config import RepresentationConfig
from soveryn.agents.representation.daemon import RepresentationDaemon
from soveryn.memory.conversation_store import ConversationStore
from soveryn.platform.lattice.legacy import LatticeStore


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fake_embed(text: str) -> tuple[float, ...]:
    return (0.1, 0.2, 0.3)


def _valid_conclusion_line() -> str:
    """One well-formed conclusion line from the parser's expected format."""
    return "deductive | confident | Jon values autonomy and self-determination. | [node:turn:abc:0]"


def _node_count(db_path: Path) -> int:
    with sqlite3.connect(str(db_path)) as con:
        return con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]


def _make_config(**kwargs) -> RepresentationConfig:
    defaults = dict(
        enabled=True,
        min_turns=1,
        dry_run=True,
        turns_per_briefing=20,
        subject="jon",
        cognition_url="http://127.0.0.1:9999",  # never called — chat_fn injected
        owner_agent="aetheria",
    )
    defaults.update(kwargs)
    return RepresentationConfig(**defaults)


def _seed_turns(conv_store: ConversationStore, agent: str, n: int) -> str:
    """Create a session with n turns, return session_id."""
    session_id = conv_store.new_session(agent)
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        conv_store.save_turn(session_id, agent=agent, role=role, content=f"turn {i}")
    return session_id


# ── Test A: eligible tick runs cognition + returns summary ────────────────────

def test_tick_eligible_dry_run_no_lattice_write(tmp_path):
    """When new_turn_count >= min_turns, cognition runs, but dry_run=True means
    NOTHING is written to the lattice (0 conclusion nodes)."""
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conv.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    # Seed 3 turns (> min_turns=1)
    _seed_turns(conv_store, "aetheria", 3)

    call_count = {"n": 0}

    def fake_chat_fn(prompt: str, url: str) -> str:
        call_count["n"] += 1
        return _valid_conclusion_line()

    cfg = _make_config(min_turns=1, dry_run=True)
    daemon = RepresentationDaemon(
        conv_store=conv_store,
        lattice_store=lattice_store,
        chat_fn=fake_chat_fn,
        embed_fn=_fake_embed,
        config=cfg,
    )

    now = datetime(2026, 6, 17, 12, 0, 0)
    summary = daemon._do_tick(now=now)

    # Cognition was called
    assert call_count["n"] == 1, "chat_fn should have been called once"

    # dry_run → nothing written
    assert _node_count(lattice_db) == 0, "dry_run must write no nodes"

    # Summary structure
    assert summary is not None
    assert summary["eligible"] is True
    assert summary["conclusion_count"] >= 1


# ── Test B: ineligible tick skips cognition entirely ─────────────────────────

def test_tick_ineligible_no_cognition_call(tmp_path):
    """When new_turn_count < min_turns, _do_tick skips and returns a
    non-eligible summary without calling chat_fn."""
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conv.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    # Zero turns seeded — below min_turns=4
    call_count = {"n": 0}

    def fake_chat_fn(prompt: str, url: str) -> str:
        call_count["n"] += 1
        return _valid_conclusion_line()

    cfg = _make_config(min_turns=4, dry_run=True)
    daemon = RepresentationDaemon(
        conv_store=conv_store,
        lattice_store=lattice_store,
        chat_fn=fake_chat_fn,
        embed_fn=_fake_embed,
        config=cfg,
    )

    now = datetime(2026, 6, 17, 12, 0, 0)
    summary = daemon._do_tick(now=now)

    assert call_count["n"] == 0, "chat_fn must not be called when ineligible"
    assert summary is not None
    assert summary["eligible"] is False


# ── Test C: _last_run_at advances after eligible tick ────────────────────────

def test_tick_advances_last_run_at(tmp_path):
    """After an eligible tick _last_run_at is set to `now`."""
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conv.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)
    _seed_turns(conv_store, "aetheria", 5)

    def fake_chat_fn(prompt, url):
        return _valid_conclusion_line()

    cfg = _make_config(min_turns=1, dry_run=True)
    daemon = RepresentationDaemon(
        conv_store=conv_store,
        lattice_store=lattice_store,
        chat_fn=fake_chat_fn,
        embed_fn=_fake_embed,
        config=cfg,
    )

    assert daemon._last_run_at is None
    now = datetime(2026, 6, 17, 14, 0, 0)
    daemon._do_tick(now=now)
    assert daemon._last_run_at == now


# ── Test D: second tick with no new turns since last run is skipped ───────────

def test_second_tick_no_new_turns_skipped(tmp_path):
    """After a successful first tick, a second tick with the same turn count
    (nothing new) is skipped because new_turn_count < min_turns=1 after
    the cutoff advances."""
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conv.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)
    _seed_turns(conv_store, "aetheria", 3)

    call_count = {"n": 0}

    def fake_chat_fn(prompt, url):
        call_count["n"] += 1
        return _valid_conclusion_line()

    cfg = _make_config(min_turns=1, dry_run=True)
    daemon = RepresentationDaemon(
        conv_store=conv_store,
        lattice_store=lattice_store,
        chat_fn=fake_chat_fn,
        embed_fn=_fake_embed,
        config=cfg,
    )

    # Use a t1 that is definitely after the seed timestamps so the turns are
    # "new" on tick 1 but "old" on tick 2 (nothing added between ticks).
    t1 = datetime.now() + timedelta(seconds=5)
    summary1 = daemon._do_tick(now=t1)
    assert summary1["eligible"] is True
    assert call_count["n"] == 1

    # No new turns added — second tick at t1 + 1h should find 0 new turns
    # because all turns are timestamped before t1 (which is now _last_run_at).
    t2 = t1 + timedelta(hours=1)
    summary2 = daemon._do_tick(now=t2)
    assert summary2["eligible"] is False
    assert call_count["n"] == 1  # no additional cognition call
