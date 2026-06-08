"""Tests for soveryn.platform.salience.markers.

Covers Task 2 of the Salience Engine plan:
    locked marker tables, speaker-aware filtering, case-insensitive
    phrase matching, word-boundary single-word matching, dedup,
    empty-content short circuit, ordering.
"""

from __future__ import annotations

from soveryn.platform.salience.markers import (
    HARD_LOCK,
    MARKER_CATEGORIES,
    PIVOT,
    SALIENCE_SIGNAL,
    SYNTHESIS,
    MarkerCategory,
    MarkerHit,
    detect_markers,
)


# ─── Table presence + weights ────────────────────────────────────────────────


def test_marker_categories_table_present():
    names = {c.name for c in MARKER_CATEGORIES}
    assert names == {"hard_lock", "synthesis", "pivot", "salience_signal"}


def test_marker_weights_match_locked_spec():
    by_name = {c.name: c for c in MARKER_CATEGORIES}
    assert by_name["hard_lock"].weight == 4
    assert by_name["synthesis"].weight == 3
    assert by_name["salience_signal"].weight == 3
    assert by_name["pivot"].weight == 2


def test_marker_category_constants_are_in_table():
    # The exported constants must be the SAME objects that live in
    # MARKER_CATEGORIES — keeps Aetheria's spec singular.
    assert HARD_LOCK in MARKER_CATEGORIES
    assert SYNTHESIS in MARKER_CATEGORIES
    assert PIVOT in MARKER_CATEGORIES
    assert SALIENCE_SIGNAL in MARKER_CATEGORIES


def test_marker_category_is_frozen():
    # Spec is locked; mutation should fail at the dataclass layer.
    cat = MarkerCategory(
        name="x", weight=1, roles=frozenset({"user"}),
        phrases=(), words=(),
    )
    import dataclasses
    try:
        cat.weight = 9  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("MarkerCategory should be frozen")


# ─── Hard lock ──────────────────────────────────────────────────────────────


def test_hard_lock_markers_match_in_user_voice():
    hits = detect_markers("the plan is locked. shipped.", role="user")
    surfaces = {h.marker for h in hits}
    assert "locked" in surfaces
    assert "shipped" in surfaces
    for h in hits:
        if h.marker in ("locked", "shipped"):
            assert h.category == "hard_lock"
            assert h.weight == 4


def test_hard_lock_does_not_fire_in_assistant_voice():
    """Hard Lock is Jon's-voice anchors — Aetheria shouldn't be able to
    lock her own opinions through these markers."""
    hits = detect_markers("I think the plan is locked. shipped.", role="assistant")
    surfaces = {h.marker for h in hits}
    assert "locked" not in surfaces
    assert "shipped" not in surfaces


def test_hard_lock_phrase_match_in_user_voice():
    hits = detect_markers("on this, the call is mine.", role="user")
    surfaces = {h.marker for h in hits}
    assert "the call is" in surfaces


# ─── Synthesis ──────────────────────────────────────────────────────────────


def test_synthesis_markers_fire_only_in_assistant_voice():
    hits_a = detect_markers("the realization is that drift is gravity.", role="assistant")
    assert any(h.category == "synthesis" and h.marker == "the realization is" for h in hits_a)
    hits_u = detect_markers("the realization is that drift is gravity.", role="user")
    assert not any(h.category == "synthesis" for h in hits_u)


# ─── Pivot ──────────────────────────────────────────────────────────────────


def test_pivot_markers_fire_in_either_voice():
    for role in ("user", "assistant"):
        hits = detect_markers("actually no, look at it this way.", role=role)
        assert any(h.category == "pivot" for h in hits), f"role={role}"


# ─── Salience signal ────────────────────────────────────────────────────────


def test_salience_signal_markers_fire_only_in_user_voice():
    hits_u = detect_markers("interesting — good catch.", role="user")
    surfaces = {h.marker for h in hits_u}
    assert "interesting" in surfaces
    assert "good catch" in surfaces
    hits_a = detect_markers("interesting — good catch.", role="assistant")
    surfaces_a = {h.marker for h in hits_a}
    assert "interesting" not in surfaces_a
    assert "good catch" not in surfaces_a


# ─── Matching semantics ─────────────────────────────────────────────────────


def test_detect_markers_is_case_insensitive():
    hits = detect_markers("THE REALIZATION IS this.", role="assistant")
    assert any(h.marker == "the realization is" for h in hits)


def test_detect_markers_word_boundary_for_short_markers():
    """Single-word markers must use word boundaries so 'undecided' doesn't
    match 'decided'."""
    hits = detect_markers("the team is undecided.", role="user")
    assert not any(h.marker == "decided" for h in hits)
    hits2 = detect_markers("we decided to go.", role="user")
    assert any(h.marker == "decided" for h in hits2)


def test_detect_markers_word_boundary_for_locked():
    # Sanity: similarly, 'unlocked' must not fire 'locked'.
    hits = detect_markers("the door is unlocked.", role="user")
    assert not any(h.marker == "locked" for h in hits)


def test_detect_markers_empty_content_returns_empty():
    assert detect_markers("", role="user") == ()
    assert detect_markers("   ", role="assistant") == ()


def test_detect_markers_no_duplicate_same_marker_hits():
    hits = detect_markers("locked locked locked", role="user")
    locked_hits = [h for h in hits if h.marker == "locked"]
    assert len(locked_hits) == 1


# ─── Ordering + multi-category ──────────────────────────────────────────────


def test_detect_markers_returns_stable_category_order():
    """When markers from multiple categories fire, the return order follows
    MARKER_CATEGORIES order (hard_lock, synthesis, pivot, salience_signal),
    then phrases-then-words within each category."""
    # User-only categories: hard_lock + salience_signal can co-fire.
    # "this is the part" (salience_signal phrase) + "locked" (hard_lock word).
    hits = detect_markers(
        "this is the part: the plan is locked. interesting, isn't it?",
        role="user",
    )
    # Hard lock entries should appear before salience_signal entries.
    categories = [h.category for h in hits]
    first_ss = categories.index("salience_signal") if "salience_signal" in categories else None
    last_hl = max(
        (i for i, c in enumerate(categories) if c == "hard_lock"),
        default=None,
    )
    assert last_hl is not None and first_ss is not None
    assert last_hl < first_ss


def test_detect_markers_phrases_before_words_within_category():
    # In hard_lock: "the call is" (phrase) and "shipped" (word).
    hits = detect_markers("the call is in: shipped.", role="user")
    markers = [h.marker for h in hits if h.category == "hard_lock"]
    assert markers.index("the call is") < markers.index("shipped")


def test_marker_hit_is_frozen_value_type():
    """Task 1's store relies on MarkerHit being a hashable frozen dataclass."""
    h = MarkerHit(category="hard_lock", marker="locked", weight=4)
    h2 = MarkerHit(category="hard_lock", marker="locked", weight=4)
    assert h == h2
    # Frozen → hashable
    assert hash(h) == hash(h2)


def test_detect_markers_returns_tuple():
    out = detect_markers("locked.", role="user")
    assert isinstance(out, tuple)
    assert all(isinstance(h, MarkerHit) for h in out)


def test_detect_markers_unknown_role_returns_empty():
    # No category includes role="system"; detection must just return ().
    out = detect_markers("the plan is locked. the realization is x.", role="system")
    assert out == ()
