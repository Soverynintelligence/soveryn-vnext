from soveryn.agents.representation.parse import parse_conclusions, Conclusion

def test_parses_valid_lines_and_drops_premiseless():
    raw = (
        "abductive | fairly confident | Jon prefers the sharp honest read | [node:a1],[node:b2]\n"
        "deductive | tentative | Jon stated he works in long focused sessions | [node:c3]\n"
        "deductive | confident | This line has no premises so must be dropped | \n"
        "garbage line with no pipes\n"
    )
    out = parse_conclusions(raw)
    assert len(out) == 2
    assert out[0] == Conclusion(mode="abductive", confidence="fairly confident",
                                content="Jon prefers the sharp honest read",
                                premises=("a1", "b2"))
    assert out[1].premises == ("c3",)  # deductive single-premise is valid → kept


def test_inductive_requires_two_premises():
    """Induction generalizes from repeated evidence — a single-premise inductive
    'pattern' is the over-extraction bug (gate 2026-06-18). Drop it; keep
    multi-premise inductions and single-premise deductive/abductive."""
    raw = (
        "inductive | confident | Jon is interested in current events | [node:a1]\n"          # 1 premise → DROP
        "inductive | confident | Jon works in long focused sessions | [node:a1],[node:b2]\n"  # 2 premises → keep
        "deductive | confident | Jon said he is feeling good | [node:c3]\n"                    # deductive 1 → keep
        "abductive | confident | Jon is likely winding down | [node:d4]\n"                     # abductive 1 → keep
    )
    out = parse_conclusions(raw)
    contents = [c.content for c in out]
    assert "Jon is interested in current events" not in contents  # single-premise inductive dropped
    assert "Jon works in long focused sessions" in contents       # multi-premise inductive kept
    assert "Jon said he is feeling good" in contents              # deductive single-premise kept
    assert "Jon is likely winding down" in contents               # abductive single-premise kept
    assert len(out) == 3

def test_invalid_mode_dropped():
    assert parse_conclusions("vibes | sure | x | [node:a]") == []
