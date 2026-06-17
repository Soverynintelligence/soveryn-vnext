from soveryn.agents.representation.parse import parse_conclusions, Conclusion

def test_parses_valid_lines_and_drops_premiseless():
    raw = (
        "abductive | fairly confident | Jon prefers the sharp honest read | [node:a1],[node:b2]\n"
        "inductive | tentative | Jon works in long focused sessions | [node:c3]\n"
        "deductive | confident | This line has no premises so must be dropped | \n"
        "garbage line with no pipes\n"
    )
    out = parse_conclusions(raw)
    assert len(out) == 2
    assert out[0] == Conclusion(mode="abductive", confidence="fairly confident",
                                content="Jon prefers the sharp honest read",
                                premises=("a1", "b2"))
    assert out[1].premises == ("c3",)

def test_invalid_mode_dropped():
    assert parse_conclusions("vibes | sure | x | [node:a]") == []
