from soveryn.agents.aetheria.speech_assembler import assemble_recall
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.types import Entry


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
