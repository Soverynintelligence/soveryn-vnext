from soveryn.agents.aetheria.speech_assembler import assemble_recall
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.types import Entry


def _quotable_section(rendered: str) -> str:
    if not rendered.startswith("Stateable recall:"):
        return ""
    return rendered.split("\n\nUncertain context:", maxsplit=1)[0]


def _entry(
    entry_id: str,
    content: str,
    cls: ProvenanceClass | None,
    *,
    source: str = "test_source",
    derived_from: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> Entry:
    provenance = None
    if cls is not None:
        provenance = Provenance(
            cls=cls,
            source=source,
            confidence=0.9,
            temporal_context="fixture",
            generator="test",
            derived_from=derived_from,
        )
    return Entry(
        id=entry_id,
        content=content,
        metadata=metadata or {},
        provenance=provenance,
    )


def test_assemble_recall_renders_channel_a_as_quotable_section() -> None:
    entries = (
        _entry("a-1", "we kept live recall dark", ProvenanceClass.WITNESSED),
        _entry("a-2", "the port is 5001", ProvenanceClass.TOLD, source="user"),
    )

    assert assemble_recall(entries) == (
        "Stateable recall:\n"
        "- I remember we kept live recall dark\n"
        "- You told me the port is 5001"
    )


def test_assemble_recall_renders_channel_b_as_uncertainty_section() -> None:
    raw_content = "raw legacy content must not be stated"
    entries = (
        _entry(
            "b-1",
            raw_content,
            ProvenanceClass.LEGACY,
            source="legacy_lattice",
            metadata={"canonical": False},
        ),
    )

    rendered = assemble_recall(entries)

    assert rendered == (
        "Uncertain context:\n"
        "- I have an uncertain older note related to this, but I can't treat it as memory yet."
    )
    assert raw_content not in rendered


def test_assemble_recall_composes_mixed_channels_in_deterministic_sections() -> None:
    raw_a = "raw legacy claim one"
    raw_b = "raw legacy claim two"
    entries = (
        _entry("a-1", "memory claims require provenance", ProvenanceClass.CONSOLIDATED),
        _entry("b-1", raw_a, ProvenanceClass.LEGACY, metadata={"canonical": False}),
        _entry(
            "a-2",
            "threshold changes were compensating",
            ProvenanceClass.INFERRED,
            derived_from=("audit-entry",),
        ),
        _entry("b-2", raw_b, None),
    )

    rendered = assemble_recall(entries)

    assert rendered == (
        "Stateable recall:\n"
        "- I've come to understand memory claims require provenance\n"
        "- I infer threshold changes were compensating because audit-entry\n"
        "\n"
        "Uncertain context:\n"
        "- I have 2 uncertain older notes related to this, but I can't treat them as memory yet."
    )
    assert raw_a not in rendered
    assert raw_b not in rendered

def test_quotable_section_contains_only_supplied_channel_a_content() -> None:
    supplied_a = "Aetheria uses provenance phrases for memory"
    supplied_b = "raw legacy content that must not be quotable"
    rendered = assemble_recall(
        (
            _entry("a-1", supplied_a, ProvenanceClass.WITNESSED),
            _entry(
                "b-1",
                supplied_b,
                ProvenanceClass.LEGACY,
                metadata={"canonical": False},
            ),
        )
    )

    quotable = _quotable_section(rendered)

    assert supplied_a in quotable
    assert supplied_b not in quotable
    assert "raw legacy content" not in quotable


def test_channel_b_content_never_appears_in_quotable_section() -> None:
    raw_claims = (
        "Channel B says a fabricated claim",
        "Another unreviewed note with private content",
    )
    rendered = assemble_recall(
        (
            _entry("a-1", "only this is stateable", ProvenanceClass.TOLD, source="user"),
            _entry("b-1", raw_claims[0], ProvenanceClass.LEGACY),
            _entry("b-2", raw_claims[1], None),
        )
    )

    quotable = _quotable_section(rendered)

    assert "only this is stateable" in quotable
    for raw_claim in raw_claims:
        assert raw_claim not in quotable


def test_unsupplied_content_cannot_appear_in_assembled_context() -> None:
    unsupplied = "this sentence was never supplied to the assembler"
    rendered = assemble_recall(
        (
            _entry("a-1", "supplied channel a content", ProvenanceClass.CONSOLIDATED),
            _entry("b-1", "supplied raw channel b content", ProvenanceClass.LEGACY),
        )
    )

    assert unsupplied not in rendered
