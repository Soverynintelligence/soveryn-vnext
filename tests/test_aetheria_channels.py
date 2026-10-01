from soveryn.agents.aetheria.channels import Channel, classify_channel
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.types import Entry


def _entry(
    cls: ProvenanceClass | None,
    *,
    metadata: dict | None = None,
    source: str = "test",
    derived_from: tuple[str, ...] = (),
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
        id="entry-1",
        content="fixture content",
        metadata=metadata or {},
        provenance=provenance,
    )


def test_witnessed_told_and_consolidated_are_channel_a() -> None:
    assert classify_channel(_entry(ProvenanceClass.WITNESSED)) is Channel.A
    assert classify_channel(_entry(ProvenanceClass.TOLD)) is Channel.A
    assert classify_channel(_entry(ProvenanceClass.CONSOLIDATED)) is Channel.A


def test_promoted_legacy_marker_is_consolidated_and_channel_a() -> None:
    entry = _entry(ProvenanceClass.CONSOLIDATED, source="legacy_identity_review")

    assert classify_channel(entry) is Channel.A


def test_inferred_with_derived_from_is_channel_a() -> None:
    entry = _entry(ProvenanceClass.INFERRED, derived_from=("entry-source",))

    assert classify_channel(entry) is Channel.A


def test_raw_legacy_is_channel_b() -> None:
    assert classify_channel(_entry(ProvenanceClass.LEGACY)) is Channel.B


def test_unprovenanced_entry_is_channel_b() -> None:
    assert classify_channel(_entry(None)) is Channel.B


def test_attic_or_noncanonical_entry_is_channel_b_even_with_channel_a_provenance() -> None:
    entry = _entry(ProvenanceClass.WITNESSED, metadata={"canonical": False})

    assert classify_channel(entry) is Channel.B


def test_journal_grade_is_channel_b_even_when_witnessed() -> None:
    """Heartbeat/dream journal residue must not become assertable \"I remember…\"."""
    entry = _entry(
        ProvenanceClass.WITNESSED,
        source="heartbeat",
        metadata={
            "grade": "journal",
            "legacy_type": "reflection",
            "tags": ["heartbeat", "reflection", "grade:journal"],
            "provenance": {
                "cls": "witnessed",
                "source": "heartbeat",
                "grade": "journal",
            },
        },
    )
    assert classify_channel(entry) is Channel.B


def test_reflection_from_dream_daemon_is_channel_b() -> None:
    entry = _entry(
        ProvenanceClass.WITNESSED,
        source="dream_daemon",
        metadata={
            "legacy_type": "reflection",
            "tags": ["dream"],
            "provenance": {"cls": "witnessed", "source": "dream_daemon"},
        },
    )
    assert classify_channel(entry) is Channel.B


def test_identity_spine_atom_stays_channel_a() -> None:
    entry = _entry(
        ProvenanceClass.CONSOLIDATED,
        source="legacy_identity_review",
        metadata={"grade": "atom", "legacy_type": "identity"},
    )
    assert classify_channel(entry) is Channel.A
