"""Kernel lattice memory: house facts, flag-gated Messages seat, recall cap."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.lattice import LatticeStore as MemoryLatticeStore
from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.kernel_memory import RECALL_CAP, _ID_OK, format_recall
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.teach import remember_fact


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={}
    )


@pytest.fixture
def seeded_recall_lattice(tmp_path):
    store = MemoryLatticeStore(tmp_path / "recall_lattice.db")
    with store._conn() as conn:
        conn.execute(
            "INSERT INTO nodes (id, type, layer, agent, content, intensity, salience, access_count, tags, created_at, updated_at)"
            " VALUES (?, 'fact', 'private', 'aetheria', 'past memory', 0.5, 0.5, 0, '[]', ?, ?)",
            (
                "test-node-1",
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return tmp_path / "recall_lattice.db"


@pytest.fixture
def fake_souls_dir(tmp_path):
    d = tmp_path / "souls"
    d.mkdir()
    (d / "aetheria.md").write_text("# Aetheria\n", encoding="utf-8")
    (d / "kernel.md").write_text("# Kernel\n", encoding="utf-8")
    (d / "eve.md").write_text("# Eve\n", encoding="utf-8")
    return d


@pytest.fixture
def fake_pinned(tmp_path):
    p = tmp_path / "pinned.md"
    p.write_text("# Pinned\n", encoding="utf-8")
    return p


class _N:
    def __init__(self, content: str, id: str = "x"):
        self.content = content
        self.id = id


def test_kernel_remember_visible_to_eve(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    out = remember_fact(
        "Live CRM is pondwright-cwg-ops, Eve Basic, not field token",
        entity="kernel.crm.ops",
        lattice_store=lattice,
        attic_store=attic,
        agent="kernel",
    )
    assert out["ok"] is True
    hits = lattice.find_canonical_facts("eve", "pondwright-cwg-ops")
    assert any("pondwright-cwg-ops" in (n.content or "") for n in hits)


def test_kernel_supersede_same_entity(tmp_path):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    a = remember_fact(
        "Do not grep Chrome logs with head",
        entity="kernel.gotcha.chrome-logs",
        lattice_store=lattice,
        attic_store=attic,
        agent="kernel",
    )
    b = remember_fact(
        "Wrap Chrome with timeout 20s; do not hang on Chrome logs",
        entity="kernel.gotcha.chrome-logs",
        lattice_store=lattice,
        attic_store=attic,
        agent="kernel",
    )
    assert b["superseded_id"] == a["lattice_id"]
    current = lattice.get_node(b["lattice_id"])
    assert "timeout 20s" in current.content


def test_recall_trim_cap():
    nodes = [_N("x" * 500) for _ in range(20)]
    text = format_recall(nodes, cap=200)
    assert len(text) <= 200
    assert text.startswith("[HOUSE LATTICE]")


def test_get_id_jail():
    assert _ID_OK.match("abc-123")
    assert not _ID_OK.match("../souls/kernel.md")
    assert not _ID_OK.match("/etc/passwd")
    assert not _ID_OK.match("a b")


def test_flag_off_kernel_has_no_recall(
    tmp_path, fake_chat, seeded_recall_lattice, fake_souls_dir, fake_pinned, monkeypatch
):
    from soveryn.app.startup import create_app
    from soveryn.memory.conversation_store import ConversationStore

    monkeypatch.delenv("SOVERYN_KERNEL_LATTICE", raising=False)
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(seeded_recall_lattice))
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    kernel = app.extensions["soveryn"]["agent_loops"]["kernel"]
    assert kernel.recall_k == 0
    names = {t.name for t in app.extensions["soveryn"]["tool_registry"].iter_tools_for_agent("kernel")}
    assert "remember_fact" not in names


def test_flag_on_kernel_gets_recall_and_tool(
    tmp_path, fake_chat, seeded_recall_lattice, fake_souls_dir, fake_pinned, monkeypatch
):
    from soveryn.app.startup import create_app
    from soveryn.memory.conversation_store import ConversationStore

    monkeypatch.setenv("SOVERYN_KERNEL_LATTICE", "1")
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(seeded_recall_lattice))
    app = create_app(conv_store=ConversationStore(tmp_path / "conv.db"))
    kernel = app.extensions["soveryn"]["agent_loops"]["kernel"]
    assert kernel.recall_k == 5
    assert kernel.lattice_store is not None
    names = {t.name for t in app.extensions["soveryn"]["tool_registry"].iter_tools_for_agent("kernel")}
    assert "remember_fact" in names
    assert RECALL_CAP == 3000
