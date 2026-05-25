"""Tests for soveryn.agents.recall.format_recall_context."""

from soveryn.agents.recall import (
    ELLIPSIS,
    MAX_CONTENT_CHARS_PER_NODE,
    MAX_TAGS_DISPLAYED,
    format_recall_context,
)
from soveryn.memory.lattice import Node


def _node(content="x", tags=(), provenance=None, intensity=0.5, layer="private"):
    return Node(
        id="id-1",
        type="fact",
        layer=layer,
        agent="aetheria",
        content=content,
        intensity=intensity,
        salience=intensity,
        access_count=0,
        tags=tags,
        created_at="now",
        updated_at="now",
        embedding=None,
        intent=None,
        provenance=provenance,
    )


def test_empty_returns_empty_string():
    """No nodes → empty string so AgentLoop omits the system message."""
    assert format_recall_context((), threshold=0.7) == ""


def test_single_node_basic_render():
    node = _node(content="Jon prefers Signal")
    out = format_recall_context(((node, 0.85),), threshold=0.7)
    assert "Your memory on this — 1 entry from your own prior conversations" in out
    assert "(semantic match >= 0.70)" in out
    assert "1. [0.85] Jon prefers Signal" in out


def test_multiple_nodes_numbered_in_input_order():
    n1 = _node(content="alpha")
    n2 = _node(content="beta")
    n3 = _node(content="gamma")
    out = format_recall_context(((n1, 0.9), (n2, 0.8), (n3, 0.75)), threshold=0.7)
    lines = out.splitlines()
    assert lines[0].startswith("Your memory on this — 3 entries from your own prior conversations")
    assert "(semantic match >= 0.70)" in lines[0]
    assert any("1. [0.90] alpha" in l for l in lines)
    assert any("2. [0.80] beta" in l for l in lines)
    assert any("3. [0.75] gamma" in l for l in lines)


def test_pluralization_singular_vs_plural():
    n = _node()
    assert "1 entry " in format_recall_context(((n, 0.8),), threshold=0.7)
    assert "2 entries " in format_recall_context(((n, 0.8), (n, 0.7)), threshold=0.7)


def test_content_truncated_at_200_chars():
    long = "x" * 500
    out = format_recall_context(((_node(content=long), 0.9),), threshold=0.7)
    # Find the entry line
    body_line = [l for l in out.splitlines() if l.startswith("1. ")][0]
    # Strip "1. [0.90] " prefix to inspect just the body+suffix
    body = body_line.split("] ", 1)[1]
    # No suffix on this node (no tags, no provenance), so body should end with ellipsis
    assert body.endswith(ELLIPSIS)
    assert len(body) == MAX_CONTENT_CHARS_PER_NODE


def test_newlines_in_content_are_flattened():
    out = format_recall_context(
        ((_node(content="line1\nline2\nline3"), 0.9),),
        threshold=0.7,
    )
    body_line = [l for l in out.splitlines() if l.startswith("1. ")][0]
    # No literal newline mid-content
    assert "\n" not in body_line
    assert "line1 line2 line3" in body_line


def test_source_provenance_appended():
    out = format_recall_context(
        ((_node(content="x", provenance={"source_type": "declared_fact"}), 0.9),),
        threshold=0.7,
    )
    assert "— source: declared_fact" in out


def test_tags_appended_when_no_source():
    out = format_recall_context(
        ((_node(content="x", tags=("alpha", "beta")), 0.9),),
        threshold=0.7,
    )
    assert "— tags: alpha, beta" in out


def test_source_wins_over_tags():
    out = format_recall_context(
        ((_node(
            content="x",
            tags=("alpha", "beta"),
            provenance={"source_type": "witnessed"},
        ), 0.9),),
        threshold=0.7,
    )
    assert "— source: witnessed" in out
    assert "tags:" not in out


def test_tags_capped_at_three():
    out = format_recall_context(
        ((_node(content="x", tags=("a", "b", "c", "d", "e")), 0.9),),
        threshold=0.7,
    )
    assert "— tags: a, b, c" in out
    assert "d" not in out.split("— tags:")[1]


def test_no_suffix_when_no_source_and_no_tags():
    out = format_recall_context(((_node(content="bare"), 0.9),), threshold=0.7)
    line = [l for l in out.splitlines() if l.startswith("1. ")][0]
    # Should end with "bare", no " — "
    assert line.endswith("bare")
    assert " — " not in line


def test_empty_provenance_dict_falls_through_to_tags():
    out = format_recall_context(
        ((_node(content="x", tags=("only-tag",), provenance={}), 0.9),),
        threshold=0.7,
    )
    assert "— tags: only-tag" in out


def test_provenance_with_non_string_source_falls_through_to_tags():
    out = format_recall_context(
        ((_node(content="x", tags=("t",), provenance={"source_type": 42}), 0.9),),
        threshold=0.7,
    )
    assert "— tags: t" in out


def test_deterministic_output_for_same_input():
    nodes = ((_node(content="a"), 0.9), (_node(content="b"), 0.8))
    out1 = format_recall_context(nodes, threshold=0.7)
    out2 = format_recall_context(nodes, threshold=0.7)
    assert out1 == out2


def test_threshold_appears_in_header_two_decimal_places():
    out = format_recall_context(((_node(), 0.9),), threshold=0.857)
    assert "semantic match >= 0.86" in out
