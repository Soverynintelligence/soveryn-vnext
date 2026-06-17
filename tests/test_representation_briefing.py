"""TDD — Task 4: briefing assembly.

Verifies that build_briefing collects recent user/assistant turns from
ConversationStore and existing 'conclusion' nodes from LatticeStore, renders
each with a [node:ID] prefix, and returns the full source_node_ids list.
"""
from __future__ import annotations

import pytest

from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.memory.conversation_store import ConversationStore
from soveryn.agents.representation.briefing import build_briefing


OWNER = "aetheria"
SUBJECT = "jon"


def test_build_briefing_returns_turns_and_prior_conclusions(tmp_path):
    # ── Store setup (mirrors test_lattice_embed_on_write.py pattern) ──────────
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conversations.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    # Write a session with two turns for the owner agent
    session_id = conv_store.new_session(OWNER, title="test session")
    conv_store.save_turn(session_id, OWNER, "user", "What is it that motivates Jon, day to day?")
    conv_store.save_turn(session_id, OWNER, "assistant", "He consistently values directness over comfort.")

    # Write one existing conclusion node for this subject
    conclusion_node_id = lattice_store.write_node(
        agent=OWNER,
        content="Jon values directness",
        node_type="conclusion",
        layer="private",
        provenance={"kind": "conclusion", "subject": SUBJECT},
    )

    # ── Call under test ───────────────────────────────────────────────────────
    briefing_text, prior_conclusions_text, source_node_ids = build_briefing(
        conv_store,
        lattice_store,
        owner_agent=OWNER,
        subject=SUBJECT,
        turns_per_briefing=20,
    )

    # ── Assertions ────────────────────────────────────────────────────────────
    # Turn contents should appear in briefing_text with [node:...] prefixes
    assert "[node:" in briefing_text, "briefing_text should contain [node:...] prefixes"
    assert "What is it that motivates Jon, day to day?" in briefing_text, "user turn content should be in briefing_text"
    assert "He consistently values directness over comfort." in briefing_text, "assistant turn content should be in briefing_text"
    # Turns are labelled by IDENTITY (gate fix 2026-06-17), not generic user/assistant
    assert "Jon:" in briefing_text and "Aetheria:" in briefing_text, "turns should be identity-labelled"
    assert "user:" not in briefing_text and "assistant:" not in briefing_text, "no generic role labels"

    # Prior conclusion should appear with its node id
    assert conclusion_node_id in prior_conclusions_text, (
        "prior_conclusions_text should contain the conclusion node id"
    )
    assert "Jon values directness" in prior_conclusions_text, (
        "prior_conclusions_text should contain the conclusion content"
    )
    assert "[node:" in prior_conclusions_text, "prior_conclusions_text should have [node:...] prefix"

    # source_node_ids should be non-empty and include the conclusion node id
    assert len(source_node_ids) > 0, "source_node_ids should be non-empty"
    assert conclusion_node_id in source_node_ids, (
        "conclusion node id should be in source_node_ids"
    )
    # All turn ids in source_node_ids should start with 'turn:'
    turn_ids = [nid for nid in source_node_ids if nid.startswith("turn:")]
    assert len(turn_ids) == 2, "should have 2 turn ids (user + assistant)"


def test_build_briefing_caps_turns(tmp_path):
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conversations.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    session_id = conv_store.new_session(OWNER)
    for i in range(10):
        conv_store.save_turn(session_id, OWNER, "user", f"substantive question number {i} about the work")
        conv_store.save_turn(session_id, OWNER, "assistant", f"a thorough answer number {i} with real detail")

    briefing_text, _, source_node_ids = build_briefing(
        conv_store,
        lattice_store,
        owner_agent=OWNER,
        subject=SUBJECT,
        turns_per_briefing=4,
    )

    turn_ids = [nid for nid in source_node_ids if nid.startswith("turn:")]
    assert len(turn_ids) == 4, f"expected 4 turns capped, got {len(turn_ids)}"


def test_build_briefing_empty_history_no_error(tmp_path):
    """Empty conv store + no conclusions should return empty strings, not raise."""
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conversations.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    briefing_text, prior_conclusions_text, source_node_ids = build_briefing(
        conv_store,
        lattice_store,
        owner_agent=OWNER,
        subject=SUBJECT,
        turns_per_briefing=20,
    )

    assert briefing_text == ""
    assert prior_conclusions_text == ""
    assert source_node_ids == []


def test_build_briefing_filters_conclusions_by_subject(tmp_path):
    """Only conclusions whose provenance.subject matches are included."""
    lattice_db = tmp_path / "lattice.db"
    conv_db = tmp_path / "conversations.db"

    lattice_store = LatticeStore(lattice_db)
    conv_store = ConversationStore(conv_db)

    # Write two conclusions: one for 'jon', one for 'vett'
    jon_id = lattice_store.write_node(
        agent=OWNER,
        content="Jon values directness",
        node_type="conclusion",
        layer="private",
        provenance={"kind": "conclusion", "subject": "jon"},
    )
    _vett_id = lattice_store.write_node(
        agent=OWNER,
        content="Vett is curious",
        node_type="conclusion",
        layer="private",
        provenance={"kind": "conclusion", "subject": "vett"},
    )

    _, prior_conclusions_text, source_node_ids = build_briefing(
        conv_store,
        lattice_store,
        owner_agent=OWNER,
        subject="jon",
        turns_per_briefing=20,
    )

    assert jon_id in prior_conclusions_text
    assert "Vett is curious" not in prior_conclusions_text
    assert jon_id in source_node_ids
