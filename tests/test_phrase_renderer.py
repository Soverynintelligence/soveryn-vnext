import pytest

from soveryn.agents.aetheria.phrase_renderer import PhraseRenderError, render_phrase
from soveryn.platform.lattice.provenance import Provenance, ProvenanceClass
from soveryn.platform.lattice.types import Entry, Region


def _entry(
    cls: ProvenanceClass | None,
    *,
    content: str = "the memory content",
    region: Region = Region.UNKNOWN,
    source: str = "test_source",
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
        content=content,
        region=region,
        provenance=provenance,
    )


def test_witnessed_renders_as_memory_phrase() -> None:
    phrase = render_phrase(_entry(ProvenanceClass.WITNESSED, content="we restarted Aetheria"))

    assert phrase == "I remember we restarted Aetheria"


def test_told_by_user_requires_attribution_not_memory_language() -> None:
    phrase = render_phrase(
        _entry(ProvenanceClass.TOLD, content="the server lives on port 5001", source="user")
    )

    assert phrase == "You told me the server lives on port 5001"
    assert "I remember" not in phrase


def test_told_by_tool_requires_tool_attribution() -> None:
    phrase = render_phrase(
        _entry(ProvenanceClass.TOLD, content="GPU temperature is 57C", source="tool_output")
    )

    assert phrase == "The tool output said GPU temperature is 57C"
    assert "I remember" not in phrase


def test_told_by_named_notes_requires_source_attribution() -> None:
    phrase = render_phrase(
        _entry(ProvenanceClass.TOLD, content="Phase 2b-i is complete", source="phase_notes")
    )

    assert phrase == "The notes from phase_notes say Phase 2b-i is complete"
    assert "I remember" not in phrase


def test_nonlegacy_consolidated_renders_as_understanding() -> None:
    phrase = render_phrase(
        _entry(ProvenanceClass.CONSOLIDATED, content="memory needs provenance")
    )

    assert phrase == "I've come to understand memory needs provenance"


def test_inferred_renders_as_inference_with_basis() -> None:
    phrase = render_phrase(
        _entry(
            ProvenanceClass.INFERRED,
            content="the recall threshold was compensating for structure",
            derived_from=("audit-entry", "plan-entry"),
        )
    )

    assert phrase == (
        "I infer the recall threshold was compensating for structure "
        "because audit-entry, plan-entry"
    )
    assert "I remember" not in phrase
    assert "I know" not in phrase
    assert " is true" not in phrase


def test_legacy_reviewed_identity_renders_as_carried_identity() -> None:
    phrase = render_phrase(
        _entry(
            ProvenanceClass.CONSOLIDATED,
            content="the no-ghost-memory rule matters",
            region=Region.IDENTITY,
            source="legacy_identity_review",
        )
    )

    assert phrase == "From older reviewed notes, I carry the no-ghost-memory rule matters"


def test_legacy_reviewed_nonidentity_renders_as_older_reviewed_notes() -> None:
    phrase = render_phrase(
        _entry(
            ProvenanceClass.CONSOLIDATED,
            content="the baseline had 747 tests",
            region=Region.EPISODIC,
            source="legacy_review",
        )
    )

    assert phrase == "I found this in older reviewed notes: the baseline had 747 tests"


def test_raw_legacy_is_not_rendered_as_channel_a() -> None:
    with pytest.raises(PhraseRenderError):
        render_phrase(_entry(ProvenanceClass.LEGACY))


def test_unprovenanced_entry_is_not_rendered_as_channel_a() -> None:
    with pytest.raises(PhraseRenderError):
        render_phrase(_entry(None))
