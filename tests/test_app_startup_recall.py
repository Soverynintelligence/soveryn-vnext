"""Tests for recall wiring at app startup (Aetheria only, read-only)."""

from datetime import datetime, timezone
from pathlib import Path
import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.loader import EnvConfig
from soveryn.config.runtime import ACTIVE_AGENTS, MODEL_ROOT
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore
from soveryn.platform.lattice.provenance import ProvenanceClass


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def seeded_recall_lattice(tmp_path):
    """A lattice with a single Aetheria node so recall has something to find."""
    store = LatticeStore(tmp_path / "recall_lattice.db")
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, access_count, tags, created_at, updated_at)"
            " VALUES (?, 'fact', 'private', 'aetheria', 'past memory', 0.5, 0.5, 0, '[]', ?, ?)",
            ("test-node-1", datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat()),
        )
    return tmp_path / "recall_lattice.db"


@pytest.fixture
def fake_souls_dir(tmp_path):
    d = tmp_path / "souls"
    d.mkdir()
    (d / "aetheria.md").write_text("# Aetheria\n", encoding="utf-8")
    (d / "vett.md").write_text("# Vett\n", encoding="utf-8")
    (d / "scotty.md").write_text("# Scotty\n", encoding="utf-8")
    return d


@pytest.fixture
def fake_pinned(tmp_path):
    p = tmp_path / "pinned.md"
    p.write_text("# Pinned\n", encoding="utf-8")
    return p


def test_aetheria_gets_recall_when_recall_lattice_exists(
    tmp_path, fake_chat, seeded_recall_lattice, fake_souls_dir, fake_pinned, monkeypatch
):
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(seeded_recall_lattice))
    conv = ConversationStore(tmp_path / "conv.db")
    app = create_app(conv_store=conv)
    state = app.extensions["soveryn"]
    aetheria = state["agent_loops"]["aetheria"]
    assert aetheria.recall_k == 5
    assert aetheria.recall_threshold == pytest.approx(0.70)
    assert aetheria.lattice_store is not None



def test_aetheria_gets_identity_spine_store_when_vnext_lattice_exists(
    tmp_path, fake_chat, seeded_recall_lattice, fake_souls_dir, fake_pinned, monkeypatch
):
    identity_lattice = LatticeStore(tmp_path / "lattice_vnext.db")
    identity_lattice.write_node(
        "aetheria",
        "identity spine entry",
        node_type="identity",
        provenance={
            "cls": ProvenanceClass.CONSOLIDATED.value,
            "source": "legacy_identity_review",
            "confidence": 1.0,
            "temporal_context": "fixture",
            "generator": "test",
            "chain": ["raw-attic-id"],
            "derived_from": [],
            "trigger": "migration_identity_review",
        },
    )
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(seeded_recall_lattice))
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(tmp_path / "lattice_vnext.db"))
    conv = ConversationStore(tmp_path / "conv.db")

    app = create_app(conv_store=conv)

    aetheria = app.extensions["soveryn"]["agent_loops"]["aetheria"]
    assert aetheria.identity_spine_store is not None
    spine = aetheria.identity_spine_store.iter_nodes(agent="aetheria")
    assert len(spine) == 1
    assert spine[0].provenance["source"] == "legacy_identity_review"

def test_vett_and_scotty_do_not_get_recall(
    tmp_path, fake_chat, seeded_recall_lattice, fake_souls_dir, fake_pinned, monkeypatch
):
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(seeded_recall_lattice))
    conv = ConversationStore(tmp_path / "conv.db")
    app = create_app(conv_store=conv)
    state = app.extensions["soveryn"]
    for name in ("vett", "scotty"):
        loop = state["agent_loops"][name]
        assert loop.recall_k == 0, f"{name} should not have recall enabled"
        assert loop.lattice_store is None, f"{name} should have no lattice_store"


def test_aetheria_runs_without_recall_if_recall_lattice_missing(
    tmp_path, fake_chat, fake_souls_dir, fake_pinned, monkeypatch, caplog
):
    """When the configured recall lattice doesn't exist, Aetheria starts up
    successfully with recall disabled (degrades gracefully, logs a warning)."""
    nonexistent = tmp_path / "does_not_exist.db"
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(nonexistent))
    conv = ConversationStore(tmp_path / "conv.db")
    app = create_app(conv_store=conv)
    state = app.extensions["soveryn"]
    aetheria = state["agent_loops"]["aetheria"]
    assert aetheria.recall_k == 0
    assert aetheria.lattice_store is None


def test_env_config_default_recall_path_points_at_prod_lattice():
    """Default recall_lattice_db points at prod's lattice.db so out-of-the-box
    deployments give Aetheria her history without any env config."""
    from soveryn.config.loader import DEFAULT_RECALL_LATTICE_DB
    assert str(DEFAULT_RECALL_LATTICE_DB).endswith("/soveryn_memory/lattice.db")
    assert "lattice_vnext" not in str(DEFAULT_RECALL_LATTICE_DB)
