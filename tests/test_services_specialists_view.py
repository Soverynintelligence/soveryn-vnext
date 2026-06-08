"""Tests for soveryn/app/services/specialists_view.py."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest

from soveryn.app.services.specialists_view import (
    DacEdge, _parse_title, kill_specialist,
    list_active_specialists, recent_dac_edges,
)


@pytest.fixture
def conv_db(tmp_path):
    db = tmp_path / "conv.db"
    with sqlite3.connect(str(db)) as con:
        con.execute("""
            CREATE TABLE conversation_meta (
                session_id TEXT PRIMARY KEY,
                agent TEXT NOT NULL,
                title TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
    return db


def _seed_session(db, *, sid, agent, title, created_at="2026-06-07T20:00:00"):
    with sqlite3.connect(str(db)) as con:
        con.execute(
            "INSERT INTO conversation_meta (session_id, agent, title, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (sid, agent, title, created_at, created_at),
        )


# ─── _parse_title ────────────────────────────────────────────────────────────


def test_parse_title_extracts_name_and_coord_id():
    assert _parse_title("[specialist:kernel_analyst:node-42]") == (
        "kernel_analyst", "node-42",
    )


def test_parse_title_handles_coord_with_colons():
    """coord_node_id might contain colons; split=":1" preserves them."""
    assert _parse_title("[specialist:fr:node:foo:bar]") == (
        "fr", "node:foo:bar",
    )


def test_parse_title_returns_unknown_on_non_specialist():
    assert _parse_title("[direct:node-1]") == ("unknown", "unknown")
    assert _parse_title("") == ("unknown", "unknown")
    assert _parse_title("[specialist:malformed") == ("unknown", "unknown")


# ─── list_active_specialists ────────────────────────────────────────────────


def test_list_active_specialists_filters_to_active_only(conv_db):
    """Only [specialist:...] titles count; archived, killed, and other
    titles are excluded."""
    _seed_session(conv_db, sid="active1", agent="vett",
                  title="[specialist:kernel:node-1]")
    _seed_session(conv_db, sid="active2", agent="scotty",
                  title="[specialist:gpu_audit:node-2]")
    _seed_session(conv_db, sid="archived", agent="vett",
                  title="[specialist-archived:done:node-3]")
    _seed_session(conv_db, sid="killed", agent="vett",
                  title="[specialist-killed:zapped:node-4]")
    _seed_session(conv_db, sid="regular", agent="aetheria",
                  title="[direct:node-5]")

    active = list_active_specialists(conv_db)
    sids = {s.specialist_id for s in active}
    assert sids == {"active1", "active2"}


def test_list_active_specialists_newest_first(conv_db):
    _seed_session(conv_db, sid="old", agent="vett",
                  title="[specialist:old_one:n1]",
                  created_at="2026-06-07T10:00:00")
    _seed_session(conv_db, sid="new", agent="vett",
                  title="[specialist:new_one:n2]",
                  created_at="2026-06-07T20:00:00")
    active = list_active_specialists(conv_db)
    assert [s.specialist_id for s in active] == ["new", "old"]


def test_list_active_specialists_extracts_name_coord_age(conv_db):
    _seed_session(
        conv_db, sid="s1", agent="vett",
        title="[specialist:detector_v1:abc-123]",
        created_at="2026-06-07T18:00:00",
    )
    now = datetime(2026, 6, 7, 20, 0, 0)
    active = list_active_specialists(conv_db, now=now)
    assert len(active) == 1
    s = active[0]
    assert s.name == "detector_v1"
    assert s.coord_node_id == "abc-123"
    assert s.host_agent == "vett"
    assert s.age_minutes == 120


def test_list_active_specialists_empty(conv_db):
    assert list_active_specialists(conv_db) == []


# ─── kill_specialist ────────────────────────────────────────────────────────


def test_kill_specialist_retitles_active_to_killed_prefix(conv_db):
    _seed_session(conv_db, sid="zap", agent="vett",
                  title="[specialist:rogue:node-9]")
    result = kill_specialist(conv_db, specialist_id="zap")
    assert result["specialist_id"] == "zap"
    assert result["killed_title"] == "[specialist-killed:rogue:node-9]"

    with sqlite3.connect(str(conv_db)) as con:
        new_title = con.execute(
            "SELECT title FROM conversation_meta WHERE session_id='zap'"
        ).fetchone()[0]
    assert new_title == "[specialist-killed:rogue:node-9]"


def test_kill_specialist_unknown_returns_error(conv_db):
    assert kill_specialist(conv_db, specialist_id="ghost") == {
        "error": "unknown_specialist", "specialist_id": "ghost",
    }


def test_kill_specialist_rejects_non_active_session(conv_db):
    """A session that's not an active specialist (e.g. already archived,
    or a regular direct session) can't be killed."""
    _seed_session(conv_db, sid="done", agent="vett",
                  title="[specialist-archived:wrapped:node-1]")
    result = kill_specialist(conv_db, specialist_id="done")
    assert result["error"] == "not_active_specialist"
    assert result["current_title"] == "[specialist-archived:wrapped:node-1]"


def test_kill_specialist_frees_concurrency_slot(conv_db):
    """After kill, count_active_specialists should drop."""
    from soveryn.agents.specialists.concurrency import count_active_specialists
    for i in range(3):
        _seed_session(conv_db, sid=f"s{i}", agent="vett",
                      title=f"[specialist:n{i}:c{i}]")
    assert count_active_specialists(conv_db) == 3
    kill_specialist(conv_db, specialist_id="s1")
    assert count_active_specialists(conv_db) == 2


# ─── recent_dac_edges ───────────────────────────────────────────────────────


@pytest.fixture
def lattice_db(tmp_path):
    """Lattice with edges + nodes tables, schema mirrored from production."""
    db = tmp_path / "lattice.db"
    with sqlite3.connect(str(db)) as con:
        con.executescript("""
            CREATE TABLE nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                layer TEXT NOT NULL,
                agent TEXT NOT NULL,
                content TEXT NOT NULL,
                intensity REAL NOT NULL,
                salience REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                tags TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                embedding TEXT,
                intent TEXT,
                provenance TEXT
            );
            CREATE TABLE edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relationship TEXT NOT NULL,
                strength REAL NOT NULL DEFAULT 0.5,
                bidirectional INTEGER NOT NULL DEFAULT 1,
                archived INTEGER NOT NULL DEFAULT 0,
                reinforcement_count INTEGER NOT NULL DEFAULT 1,
                reinforced_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)
    return db


def _seed_dac(
    db, *,
    msg_id, edge_id, coord_id,
    sender, target, mode, head,
    session_id="sess-1",
    created_at="2026-06-07T20:00:00",
):
    """Seed a direct_message node + its edge to a coord node."""
    import json
    relationship = "direct_command" if mode == "execute" else "direct_query"
    content = (
        f"[direct_{mode}] {sender} -> {target}\n"
        f"session: {session_id}\n"
        f"coord: {coord_id}\n"
        f"head: {head}"
    )
    provenance = json.dumps({
        "kind": "direct_message",
        "sender": sender, "target": target,
        "session_id": session_id, "mode": mode,
        "coord_node_id": coord_id,
    })
    with sqlite3.connect(str(db)) as con:
        # The coord target node has to exist for the FK
        # (we don't enable FK in tests so this is for shape; insert anyway)
        con.execute(
            "INSERT OR IGNORE INTO nodes (id, type, layer, agent, content, "
            "intensity, salience, access_count, tags, created_at, updated_at) "
            "VALUES (?, 'coordination', 'lattice', 'aetheria', ?, "
            "0.3, 0.5, 0, '[]', ?, ?)",
            (coord_id, "coord placeholder", created_at, created_at),
        )
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
            "salience, access_count, tags, created_at, updated_at, provenance) "
            "VALUES (?, 'direct_message', 'private', ?, ?, 0.3, 0.5, 0, '[]', "
            "?, ?, ?)",
            (msg_id, sender, content, created_at, created_at, provenance),
        )
        con.execute(
            "INSERT INTO edges (id, source_id, target_id, relationship, "
            "strength, bidirectional, archived, reinforcement_count, "
            "reinforced_at, created_at) VALUES (?, ?, ?, ?, 0.5, 0, 0, 1, ?, ?)",
            (edge_id, msg_id, coord_id, relationship, created_at, created_at),
        )


def test_recent_dac_edges_surfaces_sender_target_head(lattice_db):
    _seed_dac(
        lattice_db, msg_id="m1", edge_id="e1", coord_id="c1",
        sender="aetheria", target="scotty", mode="execute",
        head="Begin schema discovery on the lattice DB.",
    )
    now = datetime(2026, 6, 7, 21, 0, 0)
    edges = recent_dac_edges(lattice_db, now=now)
    assert len(edges) == 1
    e = edges[0]
    assert e.relationship == "direct_command"
    assert e.sender == "aetheria"
    assert e.target == "scotty"
    assert e.coord_node_id == "c1"
    assert "schema discovery" in e.message_head
    assert e.age_minutes == 60


def test_recent_dac_edges_query_mode_renders_direct_query(lattice_db):
    _seed_dac(
        lattice_db, msg_id="m1", edge_id="e1", coord_id="c1",
        sender="aetheria", target="vett", mode="query",
        head="What's the current friction on this thread?",
    )
    edges = recent_dac_edges(lattice_db)
    assert edges[0].relationship == "direct_query"


def test_recent_dac_edges_newest_first(lattice_db):
    _seed_dac(lattice_db, msg_id="m1", edge_id="e1", coord_id="c1",
              sender="aetheria", target="vett", mode="execute",
              head="old call", created_at="2026-06-07T18:00:00")
    _seed_dac(lattice_db, msg_id="m2", edge_id="e2", coord_id="c1",
              sender="aetheria", target="scotty", mode="execute",
              head="newer call", created_at="2026-06-07T20:00:00")
    edges = recent_dac_edges(lattice_db)
    assert edges[0].message_head == "newer call"
    assert edges[1].message_head == "old call"


def test_recent_dac_edges_respects_limit(lattice_db):
    for i in range(20):
        ts = f"2026-06-07T{i:02d}:00:00"
        _seed_dac(
            lattice_db, msg_id=f"m{i}", edge_id=f"e{i}", coord_id="c1",
            sender="aetheria", target="vett", mode="execute",
            head=f"call {i}", created_at=ts,
        )
    edges = recent_dac_edges(lattice_db, limit=5)
    assert len(edges) == 5
    assert edges[0].message_head == "call 19"  # newest


def test_recent_dac_edges_clamps_limit(lattice_db):
    for i in range(3):
        _seed_dac(lattice_db, msg_id=f"m{i}", edge_id=f"e{i}", coord_id="c1",
                  sender="aetheria", target="vett", mode="execute",
                  head=f"c{i}", created_at=f"2026-06-07T{i:02d}:00:00")
    assert len(recent_dac_edges(lattice_db, limit=-5)) == 1
    assert len(recent_dac_edges(lattice_db, limit=9999)) == 3


def test_recent_dac_edges_excludes_non_dac_relationships(lattice_db):
    """The query filters strictly to direct_command + direct_query."""
    import json
    with sqlite3.connect(str(lattice_db)) as con:
        # Seed two non-DAC nodes + edges with a different relationship
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
            "salience, access_count, tags, created_at, updated_at) "
            "VALUES (?, 'fact', 'private', 'aetheria', ?, 0.3, 0.5, 0, '[]', "
            "?, ?)",
            ("src", "x", "2026-06-07T20:00:00", "2026-06-07T20:00:00"),
        )
        con.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, "
            "salience, access_count, tags, created_at, updated_at) "
            "VALUES (?, 'fact', 'private', 'aetheria', ?, 0.3, 0.5, 0, '[]', "
            "?, ?)",
            ("tgt", "y", "2026-06-07T20:00:00", "2026-06-07T20:00:00"),
        )
        con.execute(
            "INSERT INTO edges (id, source_id, target_id, relationship, "
            "strength, bidirectional, archived, reinforcement_count, "
            "reinforced_at, created_at) VALUES (?, ?, ?, ?, 0.5, 0, 0, 1, ?, ?)",
            ("eF", "src", "tgt", "dream_association",
             "2026-06-07T20:00:00", "2026-06-07T20:00:00"),
        )
    assert recent_dac_edges(lattice_db) == []


def test_recent_dac_edges_empty_lattice(lattice_db):
    assert recent_dac_edges(lattice_db) == []
