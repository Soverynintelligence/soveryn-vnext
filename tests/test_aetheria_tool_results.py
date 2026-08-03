from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.legacy import Node
from soveryn.platform.lattice.provenance import ProvenanceClass


def _node(
    *,
    node_id: str = "n1",
    type_: str = "memory",
    content: str = "some content",
    provenance_cls: ProvenanceClass = ProvenanceClass.WITNESSED,
    source: str = "test",
    canonical: bool = True,
) -> Node:
    return Node(
        id=node_id,
        agent="aetheria",
        type=type_,
        layer="private",
        content=content,
        intensity=0.5,
        salience=0.5,
        access_count=0,
        tags=(),
        created_at="2026-05-30T00:00:00Z",
        updated_at="2026-05-30T00:00:00Z",
        embedding=None,
        intent=None,
        provenance={
            "cls": provenance_cls.value,
            "source": source,
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
            "canonical": canonical,
        },
    )


def test_channel_a_entries_rendered_with_provenance_phrase() -> None:
    nodes = (_node(node_id="a1", provenance_cls=ProvenanceClass.WITNESSED),)
    out = classify_and_render(nodes)
    assert "stateable" in out
    assert len(out["stateable"]) == 1
    entry = out["stateable"][0]
    assert entry["id"] == "a1"
    assert entry["provenance_class"] == "witnessed"
    assert "I remember" in entry["rendered"]



# CONTRACT CHANGED 2026-08-03, by decision.
#
# Channel B was count-only: content withheld entirely so unverified memory could
# never be stated as fact. It worked, and it also produced amnesia — asked what
# she remembered about Jon, Vett found 10 matching rows, received {"legacy": 10},
# and truthfully reported she had nothing. Suppression did not prevent a false
# statement, it produced one.
#
# Channel B now returns content, explicitly typed with provenance_class and a
# caveat. Channel A is UNCHANGED — only provenanced entries are assertable.
# Assertion discipline moved to the agent directive, which can distinguish a
# claim about the world from a memory of one's own history.
#
# What these tests now guard: B content is present AND unmistakably labelled,
# and nothing from B ever appears in `stateable`.


def test_channel_b_entries_returned_but_labelled() -> None:
    nodes = (
        _node(node_id="b1", provenance_cls=ProvenanceClass.LEGACY, content="SECRET CONTENT"),
        _node(node_id="b2", provenance_cls=ProvenanceClass.LEGACY, content="OTHER SECRET"),
    )
    out = classify_and_render(nodes)
    # Still never assertable.
    assert out["stateable"] == []
    assert out["uncertain_count_by_class"] == {"legacy": 2}
    # But now recallable, and every entry carries its class and a caveat.
    assert len(out["context_only"]) == 2
    assert {e["content"] for e in out["context_only"]} == {"SECRET CONTENT", "OTHER SECRET"}
    for e in out["context_only"]:
        assert e["provenance_class"] == "legacy"
        assert "UNVERIFIED" in e["caveat"]


def test_mixed_channels_split_correctly() -> None:
    nodes = (
        _node(node_id="a1", provenance_cls=ProvenanceClass.WITNESSED, content="visible"),
        _node(node_id="b1", provenance_cls=ProvenanceClass.LEGACY, content="hidden"),
    )
    out = classify_and_render(nodes)
    assert len(out["stateable"]) == 1
    assert out["stateable"][0]["id"] == "a1"
    assert out["uncertain_count_by_class"] == {"legacy": 1}
    # B content is now returned (2026-08-03) — the guarantee is that it is
    # labelled and never promoted into `stateable`, not that it is invisible.
    assert [e["content"] for e in out["context_only"]] == ["hidden"]
    assert all(e["provenance_class"] == "legacy" for e in out["context_only"])
    assert "hidden" not in repr(out["stateable"])


def test_uncanonical_node_is_channel_b_even_if_provenance_witnessed() -> None:
    nodes = (
        _node(
            provenance_cls=ProvenanceClass.WITNESSED,
            canonical=False,
            content="HIDDEN",
        ),
    )
    out = classify_and_render(nodes)
    assert out["stateable"] == []
    assert out["uncertain_count_by_class"] == {"witnessed": 1}
    # A witnessed-but-uncanonical node is still Channel B: returned as
    # labelled context, never assertable.
    assert "HIDDEN" not in repr(out["stateable"])
    assert [e["content"] for e in out["context_only"]] == ["HIDDEN"]


def test_empty_input_returns_empty_shape() -> None:
    out = classify_and_render(())
    assert out == {"stateable": [], "context_only": [], "uncertain_count_by_class": {}}


def test_legacy_promoted_consolidated_source_renders_with_older_notes_phrase() -> None:
    nodes = (
        _node(
            node_id="lp1",
            type_="identity",
            provenance_cls=ProvenanceClass.CONSOLIDATED,
            source="legacy_identity_review",
            content="something",
        ),
    )
    out = classify_and_render(nodes)
    assert len(out["stateable"]) == 1
    rendered = out["stateable"][0]["rendered"]
    assert "older reviewed notes" in rendered
