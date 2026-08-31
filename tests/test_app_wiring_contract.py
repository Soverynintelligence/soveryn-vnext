"""Production build-path wiring contract.

This file exists because the same class of bug has shipped twice:
  - document_store came out None in the live app (the build block reassigns
    agent_loops, so the re-expose guard never fired) — masked because the
    route test injected its own store.
  - Vett's continuity_config came out None in the live app (_continuity_for
    returned None for non-aetheria), so her Active Focus block never rendered
    — masked because the loop unit tests injected an enabled config directly.

Both were "all green, silently dead in prod." The root cause is structural:
unit/route tests inject their dependencies, so they never exercise what
`create_app()` actually wires. This file is the antidote — it boots the REAL
app factory with NO injected agent_loops/stores and asserts the wiring that,
if wrong, kills a feature with no error. When you add a capability that's
gated per-agent or hangs off app.extensions, add its invariant here.

Path discipline: every test uses tmp_path + monkeypatched env. No production
DB is touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore


# ─── Fixtures (mirror tests/test_continuity_startup_wiring.py) ───────────────

@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    for agent in ACTIVE_AGENTS:
        (souls_dir / f"{agent}.md").write_text(f"# {agent}\n", encoding="utf-8")
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned relationship substrate\n", encoding="utf-8")
    return pinned


@pytest.fixture
def recall_lattice_path(tmp_path) -> Path:
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "wiring contract fixture memory",
        provenance={
            "cls": "witnessed", "source": "test", "confidence": 0.9,
            "temporal_context": "fixture", "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


@pytest.fixture
def app(tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path):
    """The REAL app factory, no injected agent_loops — only a tmp conv_store
    for isolation. This is the whole point: exercise production wiring."""
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))
    return create_app(conv_store=ConversationStore(tmp_path / "conv.db"))


def _ext(app):
    return app.extensions["soveryn"]


def _loops(app):
    return _ext(app)["agent_loops"]


def _tool_names(loop, agent: str) -> set[str]:
    return {t.name for t in loop.tool_registry.iter_tools_for_agent(agent)}


# ─── Shared stores are exposed (the document_store class) ─────────────────────

def test_critical_stores_are_wired_not_none(app):
    ext = _ext(app)
    # document_store None was the live bug — assert every load-bearing store
    # actually came through the build.
    for key in ("conv_store", "agent_loops", "tool_registry",
                "coord_store", "document_store"):
        assert ext.get(key) is not None, f"app.extensions['{key}'] is None in prod build"


def test_all_active_agents_have_a_loop(app):
    loops = _loops(app)
    assert set(loops) == set(ACTIVE_AGENTS)


# ─── Per-agent capability wiring (the continuity_config class) ────────────────

def test_aetheria_full_capability_wiring(app):
    a = _loops(app)["aetheria"]
    assert a.continuity_config is not None and a.continuity_config.enabled
    assert a.coord_store is not None
    assert a.lattice_store is not None          # recall
    assert a.pinned_text                         # relationship substrate, non-empty


def test_vett_capability_wiring(app):
    v = _loops(app)["vett"]
    # Active Focus needs BOTH an enabled config and a coord_store — the live gap.
    assert v.continuity_config is not None and v.continuity_config.enabled
    assert v.coord_store is not None
    # Research-weight timeout fix (the "can't message vett" root cause).
    assert v.chat_timeout_seconds == 300.0
    # 2026-07-11: raised 8->16 (deeper research directives exhausted the round
    # budget); coupled with dispatch_timeout 1200s. See startup.py:707.
    assert v.max_tool_rounds == 16


def test_scotty_stays_bounded(app):
    s = _loops(app)["scotty"]
    # Scotty is a bounded executor: no board view, no cross-surface continuity.
    assert s.continuity_config is None
    assert s.coord_store is None


# ─── The generalizing invariant that encodes the lesson ──────────────────────

def test_coord_store_implies_enabled_continuity_config(app):
    """A coord_store with no enabled continuity_config = the Active Focus block
    silently never renders (the brief's first gate returns ""). That exact
    combination is the bug; assert it can never recur for ANY agent."""
    for name, loop in _loops(app).items():
        if loop.coord_store is not None:
            assert loop.continuity_config is not None and loop.continuity_config.enabled, (
                f"{name} has a coord_store but no enabled continuity_config — "
                f"its Active Focus block will silently never render"
            )


# ─── Per-agent tool presence (silent-death if a capability tool is missing) ──

def test_aetheria_has_signature_tools(app):
    names = _tool_names(_loops(app)["aetheria"], "aetheria")
    for tool in ("direct_message_agent", "create_coordination_node",
                 "create_document", "generate_image"):
        assert tool in names, f"aetheria missing {tool!r}: {sorted(names)}"


def test_vett_has_signature_tools(app):
    names = _tool_names(_loops(app)["vett"], "vett")
    for tool in ("read_file", "list_directory", "create_document"):
        assert tool in names, f"vett missing {tool!r}: {sorted(names)}"
    assert "request_direction" not in names


def test_kernel_and_eve_request_direction(app):
    kernel = _tool_names(_loops(app)["kernel"], "kernel")
    eve = _tool_names(_loops(app)["eve"], "eve")
    assert "request_direction" in kernel
    assert "request_direction" in eve


def test_eve_has_decode_qr_kernel_does_not(app):
    """Desk tools are Eve-only. Vett is merged into Eve; Scotty is off chat.

    Negative checks use the shared registry so this test does not require
    a Vett or Scotty Messages loop.
    """
    eve = _tool_names(_loops(app)["eve"], "eve")
    for tool in ("decode_qr", "make_qr", "compose_image"):
        assert tool in eve, f"eve missing {tool!r}"
    registry = _ext(app)["tool_registry"]
    for agent in ("kernel", "aetheria"):
        names = {t.name for t in registry.iter_tools_for_agent(agent)}
        for tool in ("decode_qr", "make_qr", "compose_image"):
            assert tool not in names, f"{agent} must not have {tool}"


def test_scotty_tool_scope(app):
    names = _tool_names(_loops(app)["scotty"], "scotty")
    assert "read_file" in names
    assert "request_direction" not in names
    # Documents are an Aetheria+Vett capability — Scotty must NOT have it.
    assert "create_document" not in names, "scotty should not have document tools"


# ─── X presence tools: Eve only (Aetheria pulled off) ────────────────────────

def test_aetheria_has_no_x_tools(app):
    names = _tool_names(_loops(app)["aetheria"], "aetheria")
    assert "read_x" not in names
    assert "post_to_x" not in names


def test_x_tools_scoped_to_eve(app):
    eve_names = _tool_names(_loops(app)["eve"], "eve")
    assert "read_x" in eve_names
    assert "post_to_x" in eve_names
    for agent in ("aetheria", "vett", "scotty", "kernel"):
        names = _tool_names(_loops(app)[agent], agent)
        assert "read_x" not in names, f"{agent} must not have 'read_x'"
        assert "post_to_x" not in names, f"{agent} must not have 'post_to_x'"


def test_create_app_boots_with_no_x_creds(tmp_path, monkeypatch, fake_souls_dir, fake_pinned, recall_lattice_path):
    """create_app() must succeed with zero X_* env vars set — the post_to_x
    publisher_fn must construct XClient.from_env() LAZILY (on first publish
    call), never at app-boot time."""
    for name in (
        "X_BEARER_TOKEN", "X_API_KEY", "X_API_SECRET",
        "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))
    app = create_app(conv_store=ConversationStore(tmp_path / "conv2.db"))
    names = _tool_names(_loops(app)["eve"], "eve")
    assert "read_x" in names
    assert "post_to_x" in names
    aeth = _tool_names(_loops(app)["aetheria"], "aetheria")
    assert "read_x" not in aeth
    assert "post_to_x" not in aeth
