from soveryn.agents.representation.parse import parse_conclusions, Conclusion

def test_parses_valid_lines_and_drops_premiseless():
    raw = (
        "abductive | fairly confident | Jon prefers the sharp honest read | [node:a1],[node:b2]\n"
        "deductive | tentative | Jon stated he works in long focused sessions | [node:c3]\n"
        "deductive | confident | This line has no premises so must be dropped | \n"
        "garbage line with no pipes\n"
    )
    out = parse_conclusions(raw)
    # Only the multi-premise abductive survives — single-premise (any mode) and
    # premise-less are dropped (>=2-premise-for-all rule, gate 2026-06-19).
    assert len(out) == 1
    assert out[0] == Conclusion(mode="abductive", confidence="fairly confident",
                                content="Jon prefers the sharp honest read",
                                premises=("a1", "b2"))


def test_two_premises_required_for_every_mode():
    """A durable trait needs corroboration across turns — >=2 premises for
    EVERY mode (gate 2026-06-19). Originally inductive-only; the model dodged it
    by relabeling single-turn generalizations as 'deductive'. Single-premise of
    ANY mode is now dropped; only multi-premise survives."""
    raw = (
        "inductive | confident | Jon is interested in current events | [node:a1]\n"           # 1 → DROP
        "deductive | confident | Jon seeks confirmation of daily objectives | [node:c3]\n"     # 1 → DROP (the dodge)
        "abductive | confident | Jon is likely winding down | [node:d4]\n"                     # 1 → DROP
        "inductive | confident | Jon consistently values task completion | [node:a1],[node:b2]\n"  # 2 → keep
        "deductive | confident | Jon repeatedly directs work toward closure | [node:e5],[node:f6]\n"  # 2 → keep
    )
    out = parse_conclusions(raw)
    contents = [c.content for c in out]
    assert contents == [
        "Jon consistently values task completion",
        "Jon repeatedly directs work toward closure",
    ]
    assert all(len(c.premises) >= 2 for c in out)

def test_invalid_mode_dropped():
    assert parse_conclusions("vibes | sure | x | [node:a]") == []
