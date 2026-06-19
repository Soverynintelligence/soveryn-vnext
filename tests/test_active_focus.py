"""Active Focus renderer — non-archived coordination boards → context block."""
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.coordination.store import CoordinationStore
from soveryn.platform.coordination.types import CoordBoard
from soveryn.platform.continuity.active_focus import (
    render_active_focus,
    derive_dispatch_states,
    BLOCK_HEADER,
)
from soveryn.memory.conversation_store import ConversationStore


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


# ─── dispatch-state suffix ───────────────────────────────────────────────────

def test_self_owned_node_without_directive_reads_not_yet_dispatched(tmp_path):
    store = _store(tmp_path)
    store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria", content="my plan")
    out = render_active_focus(store.list_nodes(), self_agent="aetheria")
    assert "not yet dispatched" in out


def test_other_owned_node_gets_no_dispatch_suffix(tmp_path):
    store = _store(tmp_path)
    store.create_node(board=CoordBoard.SIGNAL, owner="vett", content="vett's signal")
    # Viewer is Aetheria; the node is Vett's — not hers to dispatch, so no
    # suffix and no false "not yet dispatched" noise.
    out = render_active_focus(store.list_nodes(), self_agent="aetheria")
    assert "not yet dispatched" not in out
    assert "sent to" not in out


def test_no_self_agent_means_no_not_yet_dispatched_default(tmp_path):
    store = _store(tmp_path)
    store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria", content="my plan")
    out = render_active_focus(store.list_nodes())  # no self_agent
    assert "not yet dispatched" not in out


def test_dispatch_state_label_overrides_default(tmp_path):
    store = _store(tmp_path)
    n = store.create_node(board=CoordBoard.BLUEPRINT, owner="aetheria", content="hand this off")
    out = render_active_focus(
        store.list_nodes(),
        dispatch_states={n.id: "sent to vett, awaiting reply"},
    )
    assert "sent to vett, awaiting reply" in out
    assert "not yet dispatched" not in out


def test_derive_dispatch_states_reads_direct_sessions(tmp_path):
    conv = ConversationStore(tmp_path / "conv.db")
    # A directive that was SENT but never got a reply (1 turn) — the timeout case.
    sent_sid = conv.new_session("vett", title="[direct:coord-AAA]")
    conv.save_turn(sent_sid, "vett", "user", "do the hardware audit")
    # A directive the peer actually replied to (2 turns).
    done_sid = conv.new_session("vett", title="[direct:coord-BBB]")
    conv.save_turn(done_sid, "vett", "user", "research funding")
    conv.save_turn(done_sid, "vett", "assistant", "here are three venues")
    # A non-direct session is ignored.
    conv.new_session("vett", title="ordinary research thread")

    states = derive_dispatch_states(conv)
    assert states["coord-AAA"] == "sent to vett, awaiting reply"
    assert states["coord-BBB"] == "sent to vett, replied"
    assert len(states) == 2


def test_derive_then_render_closes_the_confabulation_gap(tmp_path):
    """End-to-end: an Aetheria-owned Open node that WAS dispatched (but only
    got as far as 'sent, no reply') reads as sent — not 'not yet dispatched'.
    This is the exact Hardware Moat case that produced the confabulation."""
    store = _store(tmp_path)
    conv = ConversationStore(tmp_path / "conv.db")
    n = store.create_node(
        board=CoordBoard.BLUEPRINT, owner="aetheria",
        content="Hardware Moat audit: Quadro vs Blackwell",
    )
    sid = conv.new_session("vett", title=f"[direct:{n.id}]")
    conv.save_turn(sid, "vett", "user", "the directive text")  # sent, no reply

    out = render_active_focus(
        store.list_nodes(),
        dispatch_states=derive_dispatch_states(conv),
    )
    assert "sent to vett, awaiting reply" in out
    assert "not yet dispatched" not in out
