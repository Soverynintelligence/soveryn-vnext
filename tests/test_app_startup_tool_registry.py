from pathlib import Path

import pytest

from soveryn.app.startup import create_app
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore


@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    # Cover every ACTIVE_AGENTS citizen — Kernel/Eve souls are required at loop boot.
    for name in ("aetheria", "vett", "scotty", "kernel", "eve"):
        (souls_dir / f"{name}.md").write_text(f"# {name.title()}\n", encoding="utf-8")
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
    assert app.extensions["soveryn"].get("sandbox_engine") is not None
    aetheria_loop = app.extensions["soveryn"]["agent_loops"]["aetheria"]
    schemas = aetheria_loop._tool_schemas()
    names = {schema["function"]["name"] for schema in schemas}
    # Slice A: every citizen gets owner-scoped recall_skill
    for agent, loop in app.extensions["soveryn"]["agent_loops"].items():
        if loop.tool_registry is None:
            continue  # Grok tools live in the Build CLI, not AgentLoop
        agent_names = {s["function"]["name"] for s in loop._tool_schemas()}
        assert "recall_skill" in agent_names, f"{agent} missing recall_skill"
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
    # Project Sandbox — Aetheria-only deterministic agency gym. Black-box
    # turn telemetry captures these invocations through the normal tool loop.
    assert {
        "sandbox_get_status",
        "sandbox_list_actions",
        "sandbox_execute_action",
        "sandbox_research",
        "sandbox_reflect",
        "sandbox_get_lessons",
    } <= names
    # Steward grant-compliance tools — Aetheria + Vett (not Scotty).
    assert {
        "grant_deadlines",
        "grant_status",
        "list_grants",
        "grant_submit",
    } <= names
    # Delegation tools — Aetheria directs Scotty via dispatch_task and checks
    # honest state via task_status. Registered unconditionally (independent of
    # the worker on/off flag): with the worker off a dispatched task simply
    # waits in 'dispatched' until the worker drains it.
    assert {"dispatch_task", "task_status"} <= names


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
    interactive-only: (b) pathological runaway generation (max_tokens=8192),
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
    # Regression (2026-06-18): the build block reassigns agent_loops, so the old
    # `if agent_loops is None` re-expose check never fired on the production
    # build and left document_store None → /documents routes 500'd. The
    # production build path MUST expose a live document_store.
    from soveryn.platform.documents.store import DocumentStore
    assert isinstance(app.extensions["soveryn"]["document_store"], DocumentStore)
    # Context window + history budget are fleet-wide: every loop trims
    # transcript to fit the 32K server window before send.
    #
    # 8_000 -> 6_000 in Memory Grades PR5 (2026-08-11), and the NUMBER moved
    # because the MEANING did: history_token_budget became history-only
    # (charge_prelude=False). Charging Aetheria's prelude — soul, pinned,
    # continuity, spine, recall — against the same envelope was starving the
    # chat history it was supposed to protect. A smaller history-only budget
    # leaves her more room to talk, not less.
    assert loops["aetheria"].context_window == 32_768
    assert loops["aetheria"].history_token_budget == 6_000
    assert loops["kernel"].context_window == 32_768
    assert loops["eve"].context_window == 32_768 or loops["eve"].context_window == 65536
    # Aetheria's interactive generation caps.
    assert loops["aetheria"].max_tokens == 8192
    assert loops["aetheria"].thinking_budget_tokens == 0
    assert "vett" not in loops
    assert "scotty" not in loops


def test_other_agents_do_not_get_aetheria_lattice_tools(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice,
) -> None:
    """Vett and Scotty get their OWN lattice search; they never see Aetheria's
    private memory.

    Until 2026-08-02 this test asserted they had no lattice search at all, to
    prevent "capability leakage across agents through the shared registry".
    The effect was amnesia: Vett's only memory tool was `search_library`
    (layer_filter="library" — 55 nodes of 2,709; 19 of her own 86). Every
    search returned nothing, so she told Jon she had no memory and no lattice.

    Leakage is prevented at the STORE, not by withholding the tool:
    find_nodes_by_* takes the calling agent and returns that agent's own nodes
    across every layer plus other agents' NON-PRIVATE nodes (2026-06-17).
    Verified live 2026-08-02 — searching a term drawn from an Aetheria private
    node returned 12 private rows for Aetheria and 0 for Vett.

    So the assertion changes from "they must not have the tool" to "they have
    their own tool and it cannot reach anyone else's private layer", which is
    the property that was actually wanted.
    """
    _configure_startup_env(
        monkeypatch,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice=recall_lattice,
    )
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))

    # Still Aetheria-only: whole-node fetch and the recent-entries feed.
    aetheria_lattice_tools = {
        "get_lattice_node",
        "recent_lattice_entries",
    }
    # Owner-scoped search every agent now gets.
    shared_lattice_search = {
        "search_lattice_by_embedding",
        "search_lattice_by_keywords",
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
    # against the real system, not her own tool surface). Read-only git
    # observation (git_status/git_diff/git_log) is likewise shared — Vett gained
    # her own read-only git tools 2026-07-07 so she can verify not just what a
    # file says but WHERE it lives in the repo.
    read_only_fs_tools = {"read_file", "list_directory"}
    # Vett's read-only git-awareness surface (distinct from, and safe unlike,
    # Scotty's mutating executor tools below).
    vett_git_tools = {"git_status", "git_log", "git_diff"}
    # The genuinely dangerous surface Vett must NEVER have: mutation + code
    # execution. This is the real executor boundary — NOT the read-only git
    # observers, which only report state.
    scotty_executor_tools = {"edit_file", "git_restore_file", "run_command", "run_pytest"}
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
    sandbox_tools = {
        "sandbox_get_status",
        "sandbox_list_actions",
        "sandbox_execute_action",
        "sandbox_research",
        "sandbox_reflect",
        "sandbox_get_lessons",
    }
    steward_tools = {
        "grant_deadlines",
        "grant_status",
        "list_grants",
        "grant_submit",
    }
    registry = app.extensions["soveryn"]["tool_registry"]
    for agent in ("vett", "scotty"):
        names = {t.name for t in registry.iter_tools_for_agent(agent)}
        assert names.isdisjoint(aetheria_lattice_tools), \
            f"{agent} sees Aetheria-only tools: {names & aetheria_lattice_tools}"
        assert names.isdisjoint(sandbox_tools), \
            f"{agent} sees sandbox tools (should not): {names & sandbox_tools}"
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
            # Scotty is NOT a grant-compliance surface — steward tools are
            # Aetheria + Vett only.
            assert names.isdisjoint(steward_tools), \
                f"scotty sees steward tools (should not): {names & steward_tools}"
        else:
            # Vett DOES get read-only repo inspection (read_file + list_directory)
            # as of 2026-06-17 — she researches improvements against the real
            # system, not a proxy of her tool surface.
            assert read_only_fs_tools <= names, \
                f"vett missing read-only fs tools: {read_only_fs_tools - names}"
            # Vett DOES get read-only git awareness (2026-07-07) — status/log/diff.
            assert vett_git_tools <= names, \
                f"vett missing read-only git tools: {vett_git_tools - names}"
            # But Vett must NEVER get the mutating/execution surface (edit_file,
            # git_restore_file, run_command, run_pytest). Read-only git is fine;
            # changing files or running code is not.
            assert names.isdisjoint(scotty_executor_tools), \
                f"vett sees Scotty executor/mutation tools: {names & scotty_executor_tools}"
            # Vett DOES get web tools.
            assert web_tools <= names, \
                f"vett missing web tools: {web_tools - names}"
            # Vett DOES get document tools (D3, 2026-06-18).
            assert document_tools <= names, \
                f"vett missing document tools: {document_tools - names}"
            # Vett DOES get steward grant-compliance tools.
            assert steward_tools <= names, \
                f"vett missing steward tools: {steward_tools - names}"
        assert names.isdisjoint(dream_tools), \
            f"{agent} sees dream tools (should not): {names & dream_tools}"


def test_kernel_has_house_web_tools(
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
    loop = app.extensions["soveryn"]["agent_loops"]["kernel"]
    names = {schema["function"]["name"] for schema in loop._tool_schemas()}
    assert {"web_search", "fetch_url", "run_aider", "run_opencode", "kernel_child"} <= names


def test_cron_notepad_registered_for_automation_agents(
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
    registry = app.extensions["soveryn"]["tool_registry"]
    for agent in ("aetheria", "eve", "kernel"):
        names = {spec.name for spec in registry.iter_tools_for_agent(agent)}
        assert "cron_notepad" in names, f"{agent} missing cron_notepad"
