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
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned\n", encoding="utf-8")
    return pinned


@pytest.fixture
def recall_lattice(tmp_path) -> Path:
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "startup registry memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


def _configure_startup_env(monkeypatch, *, fake_souls_dir, fake_pinned, recall_lattice) -> None:
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice))


def test_startup_creates_tool_registry_for_aetheria(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice,
) -> None:
    _configure_startup_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice=recall_lattice,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))

    registry = app.extensions["soveryn"].get("tool_registry")
    assert registry is not None
    aetheria_loop = app.extensions["soveryn"]["agent_loops"]["aetheria"]
    schemas = aetheria_loop._tool_schemas()
    names = {schema["function"]["name"] for schema in schemas}
    assert names == {
        "search_lattice_by_embedding",
        "search_lattice_by_keywords",
        "get_lattice_node",
        "recent_lattice_entries",
    }


def test_other_agents_do_not_get_aetheria_tools(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice,
) -> None:
    _configure_startup_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice=recall_lattice,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))

    for agent in ("vett", "scotty"):
        loop = app.extensions["soveryn"]["agent_loops"][agent]
        assert loop._tool_schemas() == ()
