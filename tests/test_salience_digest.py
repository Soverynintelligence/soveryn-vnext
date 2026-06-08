"""Tests for the heartbeat salience digest renderer.

Pure-function renderer over SalienceCandidate. No DB, no IO. Visible scoring
per Aetheria's locked spec (2026-06-08): C-Dist + Marker so she can read
off whether the engine is drifting.
"""

from __future__ import annotations

from soveryn.platform.salience.digest import build_salience_digest_section
from soveryn.platform.salience.markers import MarkerHit
from soveryn.platform.salience.store import SalienceCandidate


def _candidate(
    *,
    cid: str = "c1",
    role: str = "user",
    head: str = "...",
    markers: tuple[MarkerHit, ...] = (),
    heur: float = 0.0,
    novelty: float | None = None,
    combined: float = 0.0,
) -> SalienceCandidate:
    return SalienceCandidate(
        id=cid,
        session_id="s1",
        turn_rowid=1,
        turn_role=role,
        turn_content_head=head,
        detected_at="2026-06-08T12:00:00",
        markers=markers,
        heuristic_score=heur,
        novelty_score=novelty,
        combined_score=combined,
        status="pending",
        reviewed_at=None,
        library_node_id=None,
    )


def test_empty_candidates_returns_empty_string():
    assert build_salience_digest_section([]) == ""


def test_single_candidate_renders_marker_and_content_head():
    hit = MarkerHit(category="hard_lock", marker="locked", weight=4)
    c = _candidate(head="The plan is locked.", markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    assert "1 moment" in out          # singular framing
    assert "locked" in out            # marker visible
    assert "The plan is locked." in out
    assert "Marker:" in out           # scoring label per spec
    assert "[c1]" in out              # candidate_id visible for promote tool


def test_multiple_candidates_render_with_visible_scoring():
    hits1 = (MarkerHit("synthesis", "the realization is", 3),)
    c1 = _candidate(
        cid="c1", role="assistant",
        head="the realization is X.", markers=hits1,
        heur=3.0, novelty=0.42, combined=5.1,
    )
    hits2 = (MarkerHit("pivot", "actually no", 2),)
    c2 = _candidate(
        cid="c2", role="user",
        head="actually no, Y.", markers=hits2,
        heur=2.0, novelty=None, combined=2.0,
    )
    out = build_salience_digest_section([c1, c2])
    # Caller-supplied order is preserved (store sorts by combined_score DESC).
    assert out.index("the realization is") < out.index("actually no")
    # Visible scoring per locked spec: C-Dist + Marker.
    assert "C-Dist: 0.42" in out
    assert 'Marker: "the realization is"' in out
    assert 'Marker: "actually no"' in out


def test_caps_at_five_candidates():
    hits = (MarkerHit("hard_lock", "locked", 4),)
    cands = [
        _candidate(
            cid=f"c{i}", head=f"item {i}", markers=hits,
            heur=4.0, combined=float(10 - i),
        )
        for i in range(8)
    ]
    out = build_salience_digest_section(cands)
    for i in range(5):
        assert f"item {i}" in out
    assert "item 5" not in out  # capped
    assert "item 6" not in out
    assert "item 7" not in out
    # Header reflects the post-cap count, not the input length.
    assert "5 moments" in out


def test_closing_question_uses_review_framing_not_decide():
    """Review framing, not produce-something. Avoid the failure mode of
    pressuring action ("should you save this?")."""
    hit = MarkerHit("hard_lock", "locked", 4)
    c = _candidate(head="x", markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    lower = out.lower()
    assert "should you save" not in lower
    # Inviting framing — at minimum one of these review-y phrases is present.
    assert (
        "resonate" in lower
        or "land" in lower
        or "feel like" in lower
    )


def test_includes_candidate_ids_so_promote_tool_can_reference_them():
    """Aetheria calls promote_salience_candidate(id=...) — the id must
    appear in the digest, bracketed, so she can read it off the prompt."""
    hit = MarkerHit("hard_lock", "locked", 4)
    c = _candidate(cid="abc-xyz-123", head="x", markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    assert "[abc-xyz-123]" in out


def test_content_head_is_truncated_in_render():
    """Long content heads get further truncated for prompt readability."""
    hit = MarkerHit("hard_lock", "locked", 4)
    long_head = "locked " + ("x" * 300)
    c = _candidate(head=long_head, markers=(hit,), heur=4.0, combined=4.0)
    out = build_salience_digest_section([c])
    assert "…" in out


def test_novelty_only_candidate_renders_novelty_label():
    """Phase 2 novelty-only path: empty markers tuple, novelty_score set —
    marker label is rendered as "(novelty only)" so the source is honest."""
    c = _candidate(
        head="something genuinely new",
        markers=(),
        heur=0.0,
        novelty=0.55,
        combined=2.75,
    )
    out = build_salience_digest_section([c])
    assert '(novelty only)' in out
    assert "C-Dist: 0.55" in out


def test_no_cdist_when_novelty_is_none():
    """Markers-only candidate — no C-Dist field at all (not 'C-Dist: 0.00',
    not 'C-Dist: None'). Heuristic-only means heuristic-only in the render."""
    hit = MarkerHit("hard_lock", "locked", 4)
    c = _candidate(head="locked in", markers=(hit,), heur=4.0, novelty=None, combined=4.0)
    out = build_salience_digest_section([c])
    assert "C-Dist" not in out
    assert 'Marker: "locked"' in out


def test_plural_vs_singular_moment():
    hit = MarkerHit("hard_lock", "locked", 4)
    one = [_candidate(cid="a", head="a", markers=(hit,), combined=1.0)]
    two = [
        _candidate(cid="a", head="a", markers=(hit,), combined=2.0),
        _candidate(cid="b", head="b", markers=(hit,), combined=1.0),
    ]
    out_one = build_salience_digest_section(one)
    out_two = build_salience_digest_section(two)
    assert "1 moment " in out_one  # singular, with trailing space so "moments" doesn't match
    assert "2 moments" in out_two
    assert "1 moments" not in out_one
