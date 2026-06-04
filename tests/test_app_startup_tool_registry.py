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
    # Aetheria's lattice read tools (Track 2)
    assert {
        "search_lattice_by_embedding",
        "search_lattice_by_keywords",
        "get_lattice_node",
        "recent_lattice_entries",
    } <= names
    # Coordination Board tools (boards phase, vnext 2026-06-01)
    assert {
        "read_coordination_nodes",
        "create_coordination_node",
        "update_coordination_status",
        "archive_coordination_node",
        "promote_coordination_node",
        "add_friction_block",
    } <= names
    # File-read tools (added 2026-06-03 so Aetheria can reference her own
    # design docs in docs/superpowers/specs/ and the code that implements
    # her behavior). NOT git/pytest — those are Scotty's surface.
    assert {"read_file", "list_directory"} <= names
    assert {"git_status", "git_diff", "run_pytest"}.isdisjoint(names), \
        "Aetheria should NOT see Scotty's git/pytest tools"
    # Library tools (added 2026-06-03 — shared write surface for verified
    # reference material; all three agents get them).
    assert {"write_library_node", "search_library"} <= names
    # Self-audit tool (added 2026-06-03 to close the introspection gap —
    # agents can't see intermediate tool calls in their conversation
    # history, so they confabulate absence of actions they actually took).
    assert "recent_self_audit" in names


def test_other_agents_do_not_get_aetheria_lattice_tools(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice,
) -> None:
    """Vett and Scotty must NOT see Aetheria-owned lattice tools (no capability
    leakage across agents through the shared registry), but they DO get the
    Coordination Board tools per the boards phase (vnext 2026-06-01)."""
    _configure_startup_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice=recall_lattice,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))

    aetheria_lattice_tools = {
        "search_lattice_by_embedding",
        "search_lattice_by_keywords",
        "get_lattice_node",
        "recent_lattice_entries",
    }
    coord_tools = {
        "read_coordination_nodes",
        "create_coordination_node",
        "update_coordination_status",
        "archive_coordination_node",
        "promote_coordination_node",
        "add_friction_block",
    }
    scotty_mechanical_tools = {
        "read_file",
        "list_directory",
        "git_status",
        "git_diff",
        "run_pytest",
    }
    # Library tools are owned by each agent (shared write surface).
    library_tools = {"write_library_node", "search_library"}
    for agent in ("vett", "scotty"):
        loop = app.extensions["soveryn"]["agent_loops"][agent]
        names = {schema["function"]["name"] for schema in loop._tool_schemas()}
        assert names.isdisjoint(aetheria_lattice_tools), \
            f"{agent} sees Aetheria-only tools: {names & aetheria_lattice_tools}"
        assert coord_tools <= names, \
            f"{agent} missing coord tools: {coord_tools - names}"
        assert library_tools <= names, \
            f"{agent} missing library tools: {library_tools - names}"
        assert "recent_self_audit" in names, \
            f"{agent} missing recent_self_audit tool"
        if agent == "scotty":
            assert scotty_mechanical_tools <= names, \
                f"scotty missing mechanical tools: {scotty_mechanical_tools - names}"
        else:
            # Vett must NOT see Scotty's owner-keyed mechanical tools (git/pytest).
            # Note: read_file + list_directory are in scotty_mechanical_tools but
            # Aetheria ALSO has them registered — Vett doesn't.
            assert names.isdisjoint(scotty_mechanical_tools), \
                f"vett sees Scotty-only tools: {names & scotty_mechanical_tools}"
