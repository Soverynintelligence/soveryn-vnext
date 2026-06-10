"""Tests for Task 7 of the Salience Engine plan: app-startup wiring.

Covers:
  - EnvConfig gains a salience_db field with default + env override.
  - create_app() wraps a SalienceObserver around the default
    ConversationStore so the first user turn flags candidates.
  - The conv_store injection path (used by other tests) bypasses the
    default observer wrapping — backwards compat preserved.
  - promote_salience_candidate is registered for Aetheria only.

Path discipline: every test uses tmp_path. No production DB is touched.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path

import pytest

from soveryn.app.startup import create_app
from soveryn.config.loader import (
    DEFAULT_SALIENCE_DB,
    load_env_config,
)
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore
from soveryn.platform.salience.store import (
    create_buffer_table,
    pending_candidates_since,
)


# ─── Fixtures (mirror tests/test_app_startup_tool_registry.py shape) ─────────


@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    (souls_dir / "aetheria.md").write_text("# Aetheria\n", encoding="utf-8")
    (souls_dir / "vett.md").write_text("# Vett\n", encoding="utf-8")
    (souls_dir / "scotty.md").write_text("# Scotty\n", encoding="utf-8")
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned\n", encoding="utf-8")
    return pinned


@pytest.fixture
def recall_lattice_path(tmp_path) -> Path:
    # Materialize a real lattice DB so create_app's recall-gated tool
    # registrations (library + salience promote) all fire.
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "startup salience wiring memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


def _configure_env(
    monkeypatch,
    *,
    fake_souls_dir: Path,
    fake_pinned: Path,
    recall_lattice_path: Path,
    salience_db: Path | None = None,
) -> None:
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))
    if salience_db is not None:
        monkeypatch.setenv("SOVERYN_SALIENCE_DB", str(salience_db))


# ─── EnvConfig.salience_db ──────────────────────────────────────────────────


def test_load_env_config_includes_salience_db():
    cfg = load_env_config({})
    assert cfg.salience_db == DEFAULT_SALIENCE_DB
    # Post-path-consolidation (2026-06-10): the default derives from
    # DEFAULT_DATA_ROOT / "memory" / "salience_vnext.db" instead of the
    # legacy soveryn_complete museum path.
    assert str(cfg.salience_db).endswith("/memory/salience_vnext.db")


def test_load_env_config_respects_salience_env_var():
    cfg = load_env_config({"SOVERYN_SALIENCE_DB": "/tmp/test.db"})
    assert cfg.salience_db == Path("/tmp/test.db")


# ─── Observer wiring (default conv_store path) ──────────────────────────────


def test_create_app_wires_observer_into_conv_store(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """When create_app builds its own ConversationStore, it must wrap a
    SalienceObserver around it so the first turn flags candidates."""
    salience_db = tmp_path / "salience.db"
    conv_db = tmp_path / "conv.db"
    monkeypatch.setenv("SOVERYN_CONVERSATIONS_DB", str(conv_db))
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
        salience_db=salience_db,
    )

    app = create_app()  # NOTE: no conv_store injection — exercise the default path.
    conv_store = app.extensions["soveryn"]["conv_store"]
    assert conv_store.observer is not None, \
        "default ConversationStore should be wrapped with a SalienceObserver"

    sid = conv_store.new_session("aetheria", title="wiring probe")
    conv_store.save_turn(sid, "aetheria", "user", "The plan is locked. Ship it.")

    pending = pending_candidates_since(
        salience_db, since=datetime(1970, 1, 1), limit=10,
    )
    assert len(pending) == 1
    assert pending[0].session_id == sid
    markers = {m.marker for m in pending[0].markers}
    assert "locked" in markers


def test_create_app_skips_observer_when_conv_store_injected(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """When a caller injects a pre-built conv_store via kwarg, the salience
    observer is NOT auto-attached — caller owns that decision. This guards
    the existing test-injection path used by ~all app tests."""
    salience_db = tmp_path / "salience.db"
    create_buffer_table(salience_db)  # so a stray write would visibly land
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
        salience_db=salience_db,
    )

    injected = ConversationStore(tmp_path / "conv.db")
    assert injected.observer is None  # sanity pre-check

    app = create_app(conv_store=injected)
    conv_store = app.extensions["soveryn"]["conv_store"]
    assert conv_store is injected
    assert conv_store.observer is None, \
        "injected conv_store must NOT have an observer auto-attached"

    sid = conv_store.new_session("aetheria", title="injection probe")
    conv_store.save_turn(sid, "aetheria", "user", "The plan is locked.")

    pending = pending_candidates_since(
        salience_db, since=datetime(1970, 1, 1), limit=10,
    )
    assert pending == [], \
        "no salience candidate should be written when caller injects conv_store"


# ─── Tool-registry coverage ─────────────────────────────────────────────────


def _tool_names_for(app, agent: str) -> set[str]:
    registry = app.extensions["soveryn"]["tool_registry"]
    return {spec.name for spec in registry.iter_tools_for_agent(agent)}


def test_promote_salience_tool_registered_for_aetheria(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    names = _tool_names_for(app, "aetheria")
    assert "promote_salience_candidate" in names


def test_promote_salience_tool_NOT_registered_for_vett_or_scotty(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """Capability leak guard: the promote tool is Aetheria-only because
    the engine's review verdict lives with her. Vett/Scotty must not see it."""
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    for agent in ("vett", "scotty"):
        assert "promote_salience_candidate" not in _tool_names_for(app, agent), \
            f"{agent} should NOT see promote_salience_candidate"
