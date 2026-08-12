"""Channel-aware tool render contracts (e264382 + Memory Grades list/detail)."""

from soveryn.agents.aetheria.tool_results import classify_and_render
from soveryn.platform.lattice.content_caps import (
    CHANNEL_A_BODY_MAX_CHARS,
    CHANNEL_B_BODY_MAX_CHARS,
    CHANNEL_B_TOOL_TOP_N,
)
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
    assert out["context_only_returned"] == 0
    assert out["context_only_omitted"] == 0


# CONTRACT (e264382, 2026-08-03) + Memory Grades (2026-08-11):
#
# Channel B returns content + caveat (never count-only-only — that produced
# false amnesia). List mode may truncate/top-N bodies but must still return
# some content when B matches exist. Counts cover the full result set.


def test_channel_b_entries_returned_but_labelled() -> None:
    nodes = (
        _node(node_id="b1", provenance_cls=ProvenanceClass.LEGACY, content="SECRET CONTENT"),
        _node(node_id="b2", provenance_cls=ProvenanceClass.LEGACY, content="OTHER SECRET"),
    )
    out = classify_and_render(nodes)
    assert out["stateable"] == []
    assert out["uncertain_count_by_class"] == {"legacy": 2}
    assert len(out["context_only"]) == 2
    assert {e["content"] for e in out["context_only"]} == {"SECRET CONTENT", "OTHER SECRET"}
    for e in out["context_only"]:
        assert e["provenance_class"] == "legacy"
        assert "UNVERIFIED" in e["caveat"]
    assert out["context_only_returned"] == 2
    assert out["context_only_omitted"] == 0


def test_mixed_channels_split_correctly() -> None:
    nodes = (
        _node(node_id="a1", provenance_cls=ProvenanceClass.WITNESSED, content="visible"),
        _node(node_id="b1", provenance_cls=ProvenanceClass.LEGACY, content="hidden"),
    )
    out = classify_and_render(nodes)
    assert len(out["stateable"]) == 1
    assert out["stateable"][0]["id"] == "a1"
    assert out["uncertain_count_by_class"] == {"legacy": 1}
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
    assert "HIDDEN" not in repr(out["stateable"])
    assert [e["content"] for e in out["context_only"]] == ["HIDDEN"]


def test_empty_input_returns_empty_shape() -> None:
    out = classify_and_render(())
    assert out == {
        "stateable": [],
        "context_only": [],
        "uncertain_count_by_class": {},
        "context_only_returned": 0,
        "context_only_omitted": 0,
    }


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


def test_list_mode_truncates_long_channel_b_bodies() -> None:
    long = "X" * (CHANNEL_B_BODY_MAX_CHARS + 500)
    nodes = (
        _node(node_id="b1", provenance_cls=ProvenanceClass.LEGACY, content=long),
    )
    out = classify_and_render(nodes, mode="list")
    assert len(out["context_only"]) == 1
    e = out["context_only"][0]
    assert e["truncated"] is True
    assert e["original_chars"] == len(long)
    assert len(e["content"]) <= CHANNEL_B_BODY_MAX_CHARS
    assert e["content"].endswith("…")
    assert "UNVERIFIED" in e["caveat"]
    # Never count-only-only
    assert e["content"]


def test_list_mode_top_n_channel_b_with_honest_counts() -> None:
    nodes = tuple(
        _node(
            node_id=f"b{i}",
            provenance_cls=ProvenanceClass.LEGACY,
            content=f"body-{i}",
        )
        for i in range(CHANNEL_B_TOOL_TOP_N + 4)
    )
    out = classify_and_render(nodes, mode="list")
    assert out["uncertain_count_by_class"] == {"legacy": CHANNEL_B_TOOL_TOP_N + 4}
    assert out["context_only_returned"] == CHANNEL_B_TOOL_TOP_N
    assert out["context_only_omitted"] == 4
    assert len(out["context_only"]) == CHANNEL_B_TOOL_TOP_N
    # Preserves input order (search rank / recency)
    assert [e["id"] for e in out["context_only"]] == [
        f"b{i}" for i in range(CHANNEL_B_TOOL_TOP_N)
    ]
    # Never count-only when B matches exist
    assert all(e["content"] for e in out["context_only"])


def test_list_mode_truncates_long_channel_a_rendered() -> None:
    long = "Y" * (CHANNEL_A_BODY_MAX_CHARS + 200)
    nodes = (
        _node(node_id="a1", provenance_cls=ProvenanceClass.WITNESSED, content=long),
    )
    out = classify_and_render(nodes, mode="list")
    assert len(out["stateable"]) == 1
    e = out["stateable"][0]
    assert e.get("truncated") is True
    assert e["original_chars"] == len(long)
    # Phrase-wrapped but body contribution was capped
    assert "I remember" in e["rendered"]
    assert len(e["rendered"]) < len(long) + 50


def test_detail_mode_returns_raw_content_for_channel_a() -> None:
    content = "full detail body for assertable memory"
    nodes = (
        _node(node_id="a1", provenance_cls=ProvenanceClass.WITNESSED, content=content),
    )
    out = classify_and_render(nodes, mode="detail")
    assert len(out["stateable"]) == 1
    e = out["stateable"][0]
    assert e["content"] == content
    assert "I remember" in e["rendered"]
    assert e["content_source"] == "lattice"
    assert out["context_only"] == []


def test_detail_mode_returns_raw_content_and_caveat_for_channel_b() -> None:
    content = "unverified full note " * 20
    nodes = (
        _node(node_id="b1", provenance_cls=ProvenanceClass.LEGACY, content=content),
    )
    out = classify_and_render(nodes, mode="detail")
    assert out["stateable"] == []
    assert len(out["context_only"]) == 1
    e = out["context_only"][0]
    assert e["content"] == content
    assert "UNVERIFIED" in e["caveat"]
    assert e["content_source"] == "lattice"
    assert out["context_only_omitted"] == 0


def test_detail_mode_missing_full_text_ref_sets_flag() -> None:
    nodes = (
        _node(
            node_id="b1",
            provenance_cls=ProvenanceClass.LEGACY,
            content="lattice head only",
        ),
    )
    # Inject full_text_ref into provenance
    assert nodes[0].provenance is not None
    nodes[0].provenance["full_text_ref"] = "journal_archive:missing-id"
    # Node is frozen? Check if provenance is mutable
    out = classify_and_render(nodes, mode="detail")
    e = out["context_only"][0]
    assert e["content"] == "lattice head only"
    assert e.get("full_text_missing") is True
    assert e.get("full_text_ref") == "journal_archive:missing-id"
