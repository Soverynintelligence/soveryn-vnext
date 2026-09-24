"""Task 4 of Path Consolidation: SOVERYN_LEGACY_TEMPLATES_DIR default.

create_app() must set SOVERYN_LEGACY_TEMPLATES_DIR to a path under
~/soveryn_vnext/data/templates_legacy — never under soveryn_complete.

Fixture pattern mirrors tests/test_continuity_startup_wiring.py so the
test boots a real create_app() against a tmp_path-rooted env (no prod
files touched).
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
    (souls_dir / "kernel.md").write_text("# Kernel\n", encoding="utf-8")
    (souls_dir / "eve.md").write_text("# Eve\n", encoding="utf-8")
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
        "templates path test memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


def test_legacy_templates_dir_default_under_data_root(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """SOVERYN_LEGACY_TEMPLATES_DIR default should be under
    ~/soveryn_vnext/data/templates_legacy, NOT under soveryn_complete."""
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))

    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    legacy = str(app.config["SOVERYN_LEGACY_TEMPLATES_DIR"])
    assert "soveryn_complete" not in legacy, (
        f"templates dir still points at museum: {legacy}"
    )
    assert "templates_legacy" in legacy
    assert "soveryn_vnext" in legacy


def test_legacy_templates_dir_uses_path_home_not_hardcoded_user(
    tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path,
):
    """Default must derive from Path.home(), so it works for any user —
    not just jon-deoliveira."""
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))

    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    legacy = str(app.config["SOVERYN_LEGACY_TEMPLATES_DIR"])
    expected = str(Path.home() / "soveryn_vnext" / "data" / "templates_legacy")
    assert legacy == expected
