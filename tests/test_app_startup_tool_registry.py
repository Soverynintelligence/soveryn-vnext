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
    # Post-consolidation (2026-06-01): lattice_db and recall_lattice_db are
    # the same physical file. Post-path-consolidation (2026-06-10): the
    # default no longer points at an existing museum file, so coord-tool
    # registration (gated on env.lattice_db.is_file()) needs the test's
    # own fixture DB explicitly.
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(recall_lattice))


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
    # Dream-recall tools (added 2026-06-05 — Aetheria-only, not auto-injected;
    # she queries her own dream layer when she chooses to look).
    assert {"recent_dreams", "search_dreams"} <= names
    # Web tools (added 2026-06-04 — sovereign metasearch via SearXNG +
    # trafilatura content extraction). Aetheria + Vett only; Scotty's
    # surface stays mechanical/local.
    assert {"web_search", "fetch_url"} <= names
    # Document tools (D3, 2026-06-18 — deliverable document create/list/read/update;
    # shared space across Aetheria + Vett; Scotty is not a document author).
    assert {
        "create_document", "list_documents", "read_document", "update_document",
    } <= names


def test_aetheria_has_interactive_rail_caps_others_do_not(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice,
) -> None:
    """Context window + history budget are fleet-wide (all three run on
    32K-context servers, so every loop must trim transcript to fit before
    send — added 2026-06-17 after Vett's read_file reads overflowed the
    shared vett-scotty server). The *generation* caps stay Aetheria-
    interactive-only: (b) pathological runaway generation (max_tokens=768),
    and (c) server-side reasoning budget (thinking_budget_tokens=0). See
    startup.py inline comments for the rationale on each."""
    _configure_startup_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice=recall_lattice,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    loops = app.extensions["soveryn"]["agent_loops"]
    # Context window + history budget are fleet-wide: every loop trims
    # transcript to fit the 32K server window before send.
    for agent in ("aetheria", "vett", "scotty"):
        assert loops[agent].context_window == 32_768, agent
        assert loops[agent].history_token_budget == 8_000, agent
    # The generation caps stay Aetheria-interactive-only.
    assert loops["aetheria"].max_tokens == 768
    assert loops["aetheria"].thinking_budget_tokens == 0
    assert loops["vett"].max_tokens != 768
    assert loops["scotty"].max_tokens != 768


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
    # read_file + list_directory are read-only inspection tools shared by all
    # three agents (Vett gained them 2026-06-17 so she can research improvements
    # against the real system, not her own tool surface). git/pytest remain
    # Scotty's executor-only surface.
    read_only_fs_tools = {"read_file", "list_directory"}
    scotty_executor_tools = {"git_status", "git_diff", "run_pytest"}
    # Library tools are owned by each agent (shared write surface).
    library_tools = {"write_library_node", "search_library"}
    # Dream tools are Aetheria-only — Vett and Scotty don't dream.
    dream_tools = {"recent_dreams", "search_dreams"}
    # Web tools are Aetheria+Vett only (sovereign metasearch + content fetch).
    web_tools = {"web_search", "fetch_url"}
    # Document tools (D3, 2026-06-18) — Aetheria + Vett only; Scotty is not
    # a document author (bounded mechanical surface, not deliverable production).
    document_tools = {
        "create_document", "list_documents", "read_document", "update_document",
    }
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
            # Scotty is deliberately denied web tools — local-host surface only.
            assert names.isdisjoint(web_tools), \
                f"scotty sees web tools (should not): {names & web_tools}"
            # Scotty is NOT a document author — deliverable tools are
            # Aetheria + Vett only.
            assert names.isdisjoint(document_tools), \
                f"scotty sees document tools (should not): {names & document_tools}"
        else:
            # Vett DOES get read-only repo inspection (read_file + list_directory)
            # as of 2026-06-17 — she researches improvements against the real
            # system, not a proxy of her tool surface.
            assert read_only_fs_tools <= names, \
                f"vett missing read-only fs tools: {read_only_fs_tools - names}"
            # But Vett must NOT see Scotty's executor surface (git/pytest).
            assert names.isdisjoint(scotty_executor_tools), \
                f"vett sees Scotty executor tools: {names & scotty_executor_tools}"
            # Vett DOES get web tools.
            assert web_tools <= names, \
                f"vett missing web tools: {web_tools - names}"
            # Vett DOES get document tools (D3, 2026-06-18).
            assert document_tools <= names, \
                f"vett missing document tools: {document_tools - names}"
        assert names.isdisjoint(dream_tools), \
            f"{agent} sees dream tools (should not): {names & dream_tools}"
