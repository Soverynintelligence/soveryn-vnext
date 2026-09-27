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


# --- Recall budgeting: lessons pinned ahead of recency (2026-09-27) ---------

import argparse  # noqa: E402

from soveryn.platform.lattice import kernel_memory as km  # noqa: E402


def _teach(lattice, attic, content, topic):
    out = remember_fact(
        content, entity=topic, lattice_store=lattice, attic_store=attic, agent="kernel"
    )
    assert out["ok"] is True, out
    return out


def _recall(monkeypatch, lattice, attic, **kw):
    monkeypatch.setattr(km, "_stores", lambda: (lattice, attic))
    ns = argparse.Namespace(query="", cap=kw.get("cap", RECALL_CAP), lesson_budget=kw.get("lesson_budget"))
    return km.cmd_recall(ns)


def test_recall_keeps_old_lessons_under_flood_of_recent_facts(tmp_path, monkeypatch):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    _teach(lattice, attic, "Never force-push main; open a branch.", "kernel.lesson.git-push")
    _teach(lattice, attic, "Wrap Chrome in timeout 20s.", "kernel.gotcha.chrome-timeout")
    for i in range(20):  # 20 newer facts x ~330 chars would evict the lessons by recency
        _teach(lattice, attic, f"recent fact {i:02d} " + "r" * 310, f"kernel.misc.fact-{i:02d}")

    out = _recall(monkeypatch, lattice, attic)
    text = out["text"]
    assert out["ok"] is True
    assert len(text) <= RECALL_CAP
    assert text.startswith("[HOUSE LATTICE]\n" + km.LESSON_HEADER)
    assert "[kernel.lesson.git-push] Never force-push main" in text
    assert "[kernel.gotcha.chrome-timeout] Wrap Chrome" in text
    assert out["lessons"] == 2
    # rest of the budget is filled with the NEWEST non-lesson facts
    assert km.RECENT_HEADER in text
    assert "recent fact 19" in text
    assert "recent fact 00" not in text


def test_recall_lesson_section_respects_budget(tmp_path, monkeypatch):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    for i in range(10):
        _teach(lattice, attic, f"lesson {i:02d} " + "l" * 300, f"kernel.lesson.rule-{i:02d}")
    for i in range(5):
        _teach(lattice, attic, f"recent {i} " + "f" * 200, f"kernel.misc.r{i}")

    out = _recall(monkeypatch, lattice, attic)
    text = out["text"]
    lines = text.splitlines()
    start = lines.index(km.LESSON_HEADER)
    end = lines.index(km.RECENT_HEADER)
    lesson_block = "\n".join(lines[start:end])
    assert len(lesson_block) <= km.LESSON_BUDGET
    assert 1 <= out["lessons"] < 10
    assert "lesson 09" in text  # newest lesson wins the reserved space
    assert "recent 4" in text  # recent facts still get the remaining budget
    assert len(text) <= RECALL_CAP


def test_recall_without_lessons_keeps_flat_shape(tmp_path, monkeypatch):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    _teach(lattice, attic, "Live CRM is pondwright-cwg-ops", "kernel.crm.ops")
    out = _recall(monkeypatch, lattice, attic)
    assert out["text"] == "[HOUSE LATTICE]\n- Live CRM is pondwright-cwg-ops"
    assert out["lessons"] == 0


def test_recall_shows_only_newest_lesson_after_supersede(tmp_path, monkeypatch):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    a = _teach(lattice, attic, "Use grep | head on Chrome logs.", "kernel.lesson.chrome-logs")
    b = _teach(lattice, attic, "Never grep | head Chrome logs; use timeout 20s.", "kernel.lesson.chrome-logs")
    assert b["superseded_id"] == a["lattice_id"]
    text = _recall(monkeypatch, lattice, attic)["text"]
    assert "use timeout 20s" in text
    assert "Use grep | head on Chrome logs." not in text


def test_search_finds_topics_by_prefix(tmp_path, monkeypatch):
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    _teach(lattice, attic, "Never force-push main.", "kernel.lesson.git-push")
    _teach(lattice, attic, "Live CRM is pondwright-cwg-ops", "kernel.crm.ops")
    monkeypatch.setattr(km, "_stores", lambda: (lattice, attic))
    out = km.cmd_search(argparse.Namespace(query="kernel.lesson", limit=8))
    assert out["ok"] is True
    topics = [f["topic"] for f in out["facts"]]
    assert topics == ["kernel.lesson.git-push"]


def test_budgeted_recall_caps_and_empty():
    assert km.format_budgeted_recall([], []) == ""

    class _T:
        def __init__(self, i, topic, content):
            self.id, self.tags, self.content = f"n{i}", [f"entity:{topic}"], content

    lessons = [_T(i, f"kernel.lesson.t{i}", "x" * 390) for i in range(6)]
    recent = [_T(100 + i, f"kernel.misc.m{i}", "y" * 390) for i in range(12)]
    text = km.format_budgeted_recall(lessons, recent, cap=3000, lesson_budget=1200)
    assert len(text) <= 3000
    assert text.count("[kernel.lesson.") == 2  # 2 x ~415 chars fit in 1200 with header
    small = km.format_budgeted_recall(lessons, recent, cap=500, lesson_budget=1200)
    assert len(small) <= 500
