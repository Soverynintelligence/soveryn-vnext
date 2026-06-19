"""Active Focus renderer — non-archived coordination boards → context block."""
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.coordination.store import CoordinationStore
from soveryn.platform.coordination.types import CoordBoard
from soveryn.platform.continuity.active_focus import render_active_focus, BLOCK_HEADER


def _store(tmp_path):
    db = tmp_path / "l.db"
    LatticeStore(db)
    return CoordinationStore(db)


def test_empty_boards_render_nothing(tmp_path):
    store = _store(tmp_path)
    assert render_active_focus(store.list_nodes()) == ""


def test_renders_active_nodes_newest_first_with_board_and_status(tmp_path):
    store = _store(tmp_path)
    store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria",
                      content="Hardware Moat audit: Quadro vs Blackwell vLLM optimization")
    n2 = store.create_node(board=CoordBoard.SIGNAL, owner="vett",
                           content="New EU sovereign-AI funding window opened")
    out = render_active_focus(store.list_nodes())
    assert BLOCK_HEADER in out
    assert "Hardware Moat audit" in out and "EU sovereign-AI funding" in out
    assert "Blueprint" in out and "Signal" in out and "Open" in out
    # newest first: the Signal node (created second) appears before the Blueprint
    assert out.index("EU sovereign-AI funding") < out.index("Hardware Moat audit")


def test_archived_excluded(tmp_path):
    store = _store(tmp_path)
    n = store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria", content="done and gone")
    # Archiving goes through archive_node (writes a paired Lesson Learned),
    # NOT update_status — which refuses transitions into Archived.
    store.archive_node(n.id, lesson_learned_content="shipped it", acting_agent="aetheria")
    # list_nodes() excludes archived by default → Active Focus is empty
    assert render_active_focus(store.list_nodes()) == ""


def test_cap_limits_output(tmp_path):
    store = _store(tmp_path)
    for i in range(8):
        store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria", content=f"blueprint number {i}")
    out = render_active_focus(store.list_nodes(), cap=3)
    assert out.count("— [") == 3  # only 3 rendered
