from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.migration import (
    LEGACY_MIGRATION_CONFIDENCE,
    LEGACY_MIGRATION_SOURCE,
    render_identity_review_report,
    select_identity_review_candidates,
    write_identity_review_report,
    legacy_node_metadata,
    legacy_node_provenance,
    migrate_legacy_nodes_to_attic,
)
from soveryn.platform.lattice.provenance import ProvenanceClass


def test_legacy_node_metadata_preserves_old_fields(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    node_id = lattice.write_node(
        "aetheria",
        "legacy memory",
        node_type="fact",
        layer="private",
        intensity=0.7,
        tags=("identity", "memory"),
        intent="remember",
        provenance={"source_type": "old"},
    )
    node = lattice.get_node(node_id)

    metadata = legacy_node_metadata(node)

    assert metadata["legacy_id"] == node_id
    assert metadata["legacy_type"] == "fact"
    assert metadata["legacy_layer"] == "private"
    assert metadata["legacy_agent"] == "aetheria"
    assert metadata["legacy_intensity"] == 0.7
    assert metadata["legacy_salience"] == 0.7
    assert metadata["legacy_access_count"] == 0
    assert metadata["legacy_tags"] == ["identity", "memory"]
    assert metadata["legacy_intent"] == "remember"
    assert metadata["legacy_provenance"] == {"source_type": "old"}
    assert metadata["legacy_region_guess"] == "semantic"
    assert metadata["legacy_low_confidence"] is True


def test_legacy_node_provenance_is_low_confidence_legacy(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    node = lattice.get_node(lattice.write_node("aetheria", "legacy memory"))

    provenance = legacy_node_provenance(node, migrated_at="2026-05-30T00:00:00+00:00")

    assert provenance.cls is ProvenanceClass.LEGACY
    assert provenance.source == LEGACY_MIGRATION_SOURCE
    assert provenance.confidence == LEGACY_MIGRATION_CONFIDENCE
    assert provenance.temporal_context == "2026-05-30T00:00:00+00:00"
    assert provenance.generator == "legacy_to_attic_migration"
    assert provenance.chain == (node.id,)


def test_migrate_legacy_nodes_to_attic_copies_as_raw_noncanonical_entries(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    node_id = lattice.write_node("aetheria", "legacy memory", tags=("identity",))
    node = lattice.get_node(node_id)

    result = migrate_legacy_nodes_to_attic((node,), attic_store=attic)

    assert result.skipped_existing == ()
    assert len(result.migrated) == 1
    record = result.migrated[0]
    assert record.content == "legacy memory"
    assert record.linked_lattice_ids == (node_id,)
    assert record.provenance.cls is ProvenanceClass.LEGACY
    assert record.provenance.source == LEGACY_MIGRATION_SOURCE
    assert record.provenance.confidence == LEGACY_MIGRATION_CONFIDENCE
    assert record.metadata["legacy_id"] == node_id
    assert record.metadata["legacy_tags"] == ["identity"]

    fetched = attic.fetch("legacy")
    assert len(fetched) == 1
    assert fetched[0].metadata["canonical"] is False
    assert fetched[0].metadata["zone"] == "attic"
    assert fetched[0].metadata["linked_lattice_ids"] == [node_id]


def test_migrate_legacy_nodes_to_attic_is_idempotent_by_linked_lattice_id(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    attic = AtticStore(tmp_path / "attic.db")
    node = lattice.get_node(lattice.write_node("aetheria", "legacy memory"))

    first = migrate_legacy_nodes_to_attic((node,), attic_store=attic)
    second = migrate_legacy_nodes_to_attic((node,), attic_store=attic)

    assert len(first.migrated) == 1
    assert second.migrated == ()
    assert second.skipped_existing == (node.id,)
    assert len(attic.records_linked_to(node.id)) == 1


def test_identity_review_candidates_accept_clean_identity_signals(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    accepted_id = lattice.write_node(
        "aetheria",
        "Interaction style confirmed: presence over performance and directness matter.",
        intensity=0.85,
        tags=("identity", "interaction"),
    )
    unrelated_id = lattice.write_node("aetheria", "A generic weather forecast", intensity=0.9)

    candidates = select_identity_review_candidates(lattice.iter_nodes(), cap=12)

    by_id = {candidate.node.id: candidate for candidate in candidates}
    assert by_id[accepted_id].accepted is True
    assert "identity" in by_id[accepted_id].signals
    assert by_id[accepted_id].exclusions == ()
    assert by_id[unrelated_id].accepted is False
    assert "no_identity_signal" in by_id[unrelated_id].exclusions


def test_identity_review_candidates_enforce_locked_exclusion_categories(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    rows = {
        "retired": lattice.write_node("aetheria", "Identity note mentioning Tinker coordination", intensity=0.9),
        "stale_model": lattice.write_node("aetheria", "Aetheria identity runs on Heretic Qwen runtime", intensity=0.9),
        "heartbeat": lattice.write_node(
            "aetheria",
            "[I told Jon] I am here with presence",
            intensity=0.9,
            tags=("shared_with_jon", "identity"),
        ),
        "false_write": lattice.write_node("aetheria", "I wrote the identity file for memory continuity", intensity=0.9),
        "test_artifact": lattice.write_node("aetheria", "TEST_TRIGGER Project Obsidian forbidden fact", intensity=0.9),
    }

    candidates = select_identity_review_candidates(lattice.iter_nodes(), cap=12)

    by_id = {candidate.node.id: candidate for candidate in candidates}
    assert "retired_agent_mention" in by_id[rows["retired"]].exclusions
    assert "stale_model_or_runtime_ref" in by_id[rows["stale_model"]].exclusions
    assert "autonomous_heartbeat_phrasing" in by_id[rows["heartbeat"]].exclusions
    assert "false_tool_or_write_claim_without_evidence" in by_id[rows["false_write"]].exclusions
    assert "test_artifact" in by_id[rows["test_artifact"]].exclusions
    assert all(by_id[node_id].accepted is False for node_id in rows.values())


def test_false_write_claim_check_uses_tool_write_evidence_not_substring_only(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    node_id = lattice.write_node(
        "aetheria",
        "I wrote the identity migration report with tool evidence",
        intensity=0.9,
        tags=("identity",),
        provenance={"source_type": "tool_output", "operation": "write_file"},
    )

    candidates = select_identity_review_candidates(lattice.iter_nodes(), cap=12)

    candidate = {candidate.node.id: candidate for candidate in candidates}[node_id]
    assert "false_tool_or_write_claim_without_evidence" not in candidate.exclusions
    assert candidate.accepted is True


def test_identity_review_candidates_apply_cap_without_promoting(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    first = lattice.write_node("aetheria", "identity directness and presence", intensity=1.0)
    second = lattice.write_node("aetheria", "identity autonomy and friendship", intensity=0.9)

    candidates = select_identity_review_candidates(lattice.iter_nodes(), cap=1)

    accepted = [candidate.node.id for candidate in candidates if candidate.accepted]
    rejected = [candidate for candidate in candidates if not candidate.accepted]
    assert accepted == [first]
    assert any(candidate.node.id == second and "over_identity_spine_cap" in candidate.exclusions for candidate in rejected)
    assert lattice.find_nodes_by_keywords("aetheria", "identity")  # source lattice unchanged; no promotion side effect


def test_render_identity_review_report_contains_accepted_and_rejected_reasons(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    lattice.write_node("aetheria", "identity presence and directness", intensity=0.9)
    lattice.write_node("aetheria", "TEST_TRIGGER identity artifact", intensity=0.9)
    candidates = select_identity_review_candidates(lattice.iter_nodes(), cap=12)

    report = render_identity_review_report(candidates, source_label="fixture")

    assert "Accepted Identity Spine Candidates" in report
    assert "Rejected / Deferred Candidates" in report
    assert "test_artifact" in report
    assert "Task 6 may promote only accepted rows" in report


def test_write_identity_review_report_writes_markdown_without_mutating_stores(tmp_path) -> None:
    lattice = LatticeStore(tmp_path / "lattice.db")
    node_id = lattice.write_node("aetheria", "identity memory philosophy", intensity=0.9)
    candidates = select_identity_review_candidates(lattice.iter_nodes(), cap=12)
    path = tmp_path / "report.md"

    write_identity_review_report(path, candidates, source_label="fixture")

    assert path.read_text().startswith("# Phase 2b-ii-b1 Migration Report")
    assert lattice.get_node(node_id) is not None
