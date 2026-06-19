"""Tests for Task 6 of the Cross-Surface Continuity plan: app-startup wiring.

Covers:
  - EnvConfig gains the four cross_surface_* fields with defaults + env overrides.
  - create_app() builds a ContinuityConfig for Aetheria's AgentLoop only.
  - Vett and Scotty's AgentLoops get continuity_config=None.

Path discipline: every test uses tmp_path. No production DB is touched.
"""

from __future__ import annotations
from pathlib import Path

import pytest

from soveryn.app.startup import create_app
from soveryn.config.loader import load_env_config
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore


# ─── EnvConfig.cross_surface_* ───────────────────────────────────────────────


def test_load_env_config_includes_cross_surface_defaults():
    cfg = load_env_config({})
    assert cfg.cross_surface_enabled is True
    assert cfg.cross_surface_window_hours == 6
    assert cfg.cross_surface_token_budget == 1500
    assert cfg.cross_surface_per_session_cap == 400


def test_load_env_config_respects_cross_surface_enabled_env():
    cfg = load_env_config({"SOVERYN_CROSS_SURFACE_ENABLED": "false"})
    assert cfg.cross_surface_enabled is False


def test_load_env_config_respects_cross_surface_window_hours_env():
    cfg = load_env_config({"SOVERYN_CROSS_SURFACE_WINDOW_HOURS": "4"})
    assert cfg.cross_surface_window_hours == 4


def test_load_env_config_respects_cross_surface_token_budget_env():
    cfg = load_env_config({"SOVERYN_CROSS_SURFACE_TOKEN_BUDGET": "2000"})
    assert cfg.cross_surface_token_budget == 2000


def test_load_env_config_respects_cross_surface_per_session_cap_env():
    cfg = load_env_config({"SOVERYN_CROSS_SURFACE_PER_SESSION_CAP": "250"})
    assert cfg.cross_surface_per_session_cap == 250


# ─── Fixtures (mirror tests/test_salience_startup_wiring.py shape) ───────────


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
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "startup continuity wiring memory",
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
) -> None:
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))


# ─── ContinuityConfig wiring per-agent ───────────────────────────────────────


def test_aetheria_agent_loop_gets_continuity_config(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """Aetheria's AgentLoop must receive a populated ContinuityConfig drawn
    from the env-resolved settings."""
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    monkeypatch.setenv("SOVERYN_CROSS_SURFACE_WINDOW_HOURS", "3")
    monkeypatch.setenv("SOVERYN_CROSS_SURFACE_TOKEN_BUDGET", "900")
    monkeypatch.setenv("SOVERYN_CROSS_SURFACE_PER_SESSION_CAP", "275")

    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    aetheria = app.extensions["soveryn"]["agent_loops"]["aetheria"]
    cfg = aetheria.continuity_config
    assert cfg is not None
    assert cfg.enabled is True
    assert cfg.window_hours == 3
    assert cfg.token_budget == 900
    assert cfg.per_session_cap == 275


def test_vett_agent_loop_gets_continuity_config_and_coord_store(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """Vett now gets an ENABLED continuity_config + a coord_store so her Active
    Focus block renders (board awareness + her send/receive state). The first
    gate in _build_continuity_brief returns "" without an enabled config — this
    is the production-path regression that the loop unit tests missed (they
    injected the config directly). Cross-session tails stay Aetheria-only; that
    behavioral split is verified in test_continuity_loop_integration."""
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    vett = app.extensions["soveryn"]["agent_loops"]["vett"]
    assert vett.continuity_config is not None
    assert vett.continuity_config.enabled is True
    assert vett.coord_store is not None


def test_scotty_agent_loop_does_not_get_continuity_config(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    _configure_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    scotty = app.extensions["soveryn"]["agent_loops"]["scotty"]
    assert scotty.continuity_config is None
