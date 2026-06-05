"""Tests for soveryn.agents.dream.prompt — three-pass prompt construction.

Spec: each pass has a distinct synthesis-asking frame, not data-asking.
The prompts must contain no JSON-schema directives, no scratchpad markup,
and the synthesis pass must visibly fold in prior passes.
"""

from soveryn.agents.dream.prompt import (
    DreamBriefing,
    NodeSummary,
    render_association_pass,
    render_contradiction_pass,
    render_synthesis_pass,
)


def _briefing() -> DreamBriefing:
    return DreamBriefing(
        hours_since_last_dream=24.0,
        nodes=(
            NodeSummary(id="n-1", agent="aetheria", node_type="memory",
                        content_head="EU Digital Europe funding 2026 round"),
            NodeSummary(id="n-2", agent="vett", node_type="library",
                        content_head="UK Sovereign AI grant scope notes"),
        ),
        board_summary="Signal: 0 / Blueprint: 3 open / Friction: 0",
        recent_daemon_activity="heartbeat 14 eligible ticks; patrol dry-run 4 ticks",
        recent_library_writes_count=2,
    )


# ─── Association pass ──────────────────────────────────────────────────────

def test_association_pass_includes_node_references_with_ids():
    """The pass must let Aetheria reference nodes by ID for downstream
    edge extraction. Format: [node:n-1]."""
    p = render_association_pass(_briefing())
    assert "[node:n-1]" in p
    assert "[node:n-2]" in p


def test_association_pass_uses_open_frame_not_json_schema():
    p = render_association_pass(_briefing())
    # No JSON schema directives
    assert "JSON" not in p
    assert "schema" not in p.lower()
    # No scratchpad markup
    assert "<think" not in p
    assert "[RESOLVE" not in p
    # Open synthesis-asking frame
    assert "associations" in p.lower() or "connections" in p.lower()


def test_association_pass_mentions_recent_context():
    p = render_association_pass(_briefing())
    assert "24" in p  # hours since last dream
    assert "Signal" in p or "Blueprint" in p


# ─── Contradiction pass ────────────────────────────────────────────────────

def test_contradiction_pass_folds_in_prior_associations():
    prior = "Sample associations text mentioning [node:n-1] connections."
    p = render_contradiction_pass(_briefing(), prior_associations=prior)
    assert prior in p
    assert "contradict" in p.lower() or "conflict" in p.lower()


# ─── Synthesis pass ────────────────────────────────────────────────────────

def test_synthesis_pass_folds_in_both_prior_passes():
    p = render_synthesis_pass(
        _briefing(),
        prior_associations="ASSOC_PASS_OUTPUT_HERE",
        prior_contradictions="CONTRA_PASS_OUTPUT_HERE",
    )
    assert "ASSOC_PASS_OUTPUT_HERE" in p
    assert "CONTRA_PASS_OUTPUT_HERE" in p
    # Synthesis-asking frame, not summarization
    assert "emerge" in p.lower() or "integrate" in p.lower()


def test_synthesis_pass_invites_node_reference_use():
    """For downstream edge extraction — synthesis should be encouraged to
    use [node:ID] when naming connections worth strengthening."""
    p = render_synthesis_pass(
        _briefing(),
        prior_associations="x",
        prior_contradictions="y",
    )
    assert "[node:" in p  # the instruction mentions the format


# ─── No-output / silence framing ──────────────────────────────────────────

def test_all_passes_permit_silence_explicitly():
    """A quiet night with nothing worth surfacing should produce silence,
    not a forced report. Each prompt must explicitly allow that."""
    p1 = render_association_pass(_briefing())
    p2 = render_contradiction_pass(_briefing(), "x")
    p3 = render_synthesis_pass(_briefing(), "x", "y")
    for p in (p1, p2, p3):
        assert "nothing" in p.lower() or "silence" in p.lower() or "quiet" in p.lower()
