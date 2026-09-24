"""Tests for Direct Agent Communication tool registration in app startup.

DAC-T7 wires the two new tools (direct_message_agent on Aetheria,
request_direction on Kernel + Eve) into the coord-store-gated block in
soveryn.app.startup. These tests assert ownership lands as designed and
that the wiring is gated by the same coord-store availability as the
other coord tools.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.app.startup import create_app
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore


@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    (souls_dir / "aetheria.md").write_text("# Aetheria\n", encoding="utf-8")
    (souls_dir / "vett.md").write_text("# Vett\n", encoding="utf-8")
    (souls_dir / "scotty.md").write_text("# Scotty\n", encoding="utf-8")
    (souls_dir / "kernel.md").write_text("# Kernel\n", encoding="utf-8")
    (souls_dir / "eve.md").write_text("# Eve\n", encoding="utf-8")
    (souls_dir / "grok.md").write_text("# Grok\n", encoding="utf-8")
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned\n", encoding="utf-8")
    return pinned


@pytest.fixture
def isolated_lattice(tmp_path) -> Path:
    """Single consolidated lattice DB for this test run — covers both the
    recall lattice and the coord-store lattice (consolidated 2026-06-01,
    same default path)."""
    store = LatticeStore(tmp_path / "lattice_vnext.db")
    store.write_node(
        "aetheria",
        "startup DAC wiring test seed",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "lattice_vnext.db"


@pytest.fixture
def app_state(tmp_path, monkeypatch, fake_souls_dir, fake_pinned, isolated_lattice):
    """Build the test app with both lattice paths pointing at our isolated DB
    so coord_store + coord_event_bus get initialized (and thus the DAC tool
    registrations fire). Returns the app.extensions['soveryn'] dict."""
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(isolated_lattice))
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(isolated_lattice))
    conv = ConversationStore(tmp_path / "conv.db")
    app = create_app(conv_store=conv)
    return app.extensions["soveryn"]


def test_direct_message_agent_registered_for_aetheria_only(app_state):
    """direct_message_agent is owned by Aetheria — she's the sender. Vett
    and Scotty must NOT see it (they pull her via request_direction, they
    don't push each other)."""
    registry = app_state["tool_registry"]
    aetheria_tool_names = {t.name for t in registry.iter_tools_for_agent("aetheria")}
    vett_tool_names = {t.name for t in registry.iter_tools_for_agent("vett")}
    scotty_tool_names = {t.name for t in registry.iter_tools_for_agent("scotty")}
    assert "direct_message_agent" in aetheria_tool_names
    assert "read_collab" in aetheria_tool_names
    assert "direct_message_agent" not in vett_tool_names
    assert "direct_message_agent" not in scotty_tool_names
    assert "read_collab" not in vett_tool_names


def test_request_direction_registered_for_kernel_and_eve_only(app_state):
    """request_direction lives on the live peers — they hit walls that need
    a judgment call. Vett/Scotty are parked; Aetheria receives the pings."""
    registry = app_state["tool_registry"]
    aetheria_tool_names = {t.name for t in registry.iter_tools_for_agent("aetheria")}
    kernel_tool_names = {t.name for t in registry.iter_tools_for_agent("kernel")}
    eve_tool_names = {t.name for t in registry.iter_tools_for_agent("eve")}
    vett_tool_names = {t.name for t in registry.iter_tools_for_agent("vett")}
    scotty_tool_names = {t.name for t in registry.iter_tools_for_agent("scotty")}
    assert "request_direction" not in aetheria_tool_names
    assert "request_direction" in kernel_tool_names
    assert "request_direction" in eve_tool_names
    assert "request_direction" not in vett_tool_names
    assert "request_direction" not in scotty_tool_names
