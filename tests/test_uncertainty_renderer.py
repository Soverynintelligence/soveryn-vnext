from soveryn.agents.aetheria.uncertainty_renderer import render_uncertainty
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.types import Entry


def _legacy_entry(entry_id: str, content: str) -> Entry:
    return Entry(
        id=entry_id,
        content=content,
        metadata={"canonical": False},
        provenance=Provenance(
            cls=ProvenanceClass.LEGACY,
            source="legacy_lattice",
            confidence=0.4,
            temporal_context="migration-fixture",
            generator="test",
        ),
    )


def test_zero_channel_b_entries_render_empty_string() -> None:
    assert render_uncertainty(()) == ""


def test_single_channel_b_entry_renders_uncertainty_class_without_content() -> None:
    secret_content = "Aetheria absolutely remembers the forbidden raw legacy claim"
    rendered = render_uncertainty((_legacy_entry("raw-1", secret_content),))

    assert rendered == (
        "I have an uncertain older note related to this, "
        "but I can't treat it as memory yet."
    )
    assert secret_content not in rendered
    assert "forbidden raw legacy claim" not in rendered


def test_multiple_channel_b_entries_render_count_without_content() -> None:
    raw_a = "Jon said the raw note should never be quoted"
    raw_b = "The old lattice claims something unreviewed"
    rendered = render_uncertainty(
        (
            _legacy_entry("raw-1", raw_a),
            _legacy_entry("raw-2", raw_b),
        )
    )

    assert rendered == (
        "I have 2 uncertain older notes related to this, "
        "but I can't treat them as memory yet."
    )
    assert raw_a not in rendered
    assert raw_b not in rendered
    assert "never be quoted" not in rendered
    assert "something unreviewed" not in rendered
