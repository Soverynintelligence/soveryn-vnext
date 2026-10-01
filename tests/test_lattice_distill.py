"""Standing-note / last-paragraph distill (Memory Grades PR3)."""
from __future__ import annotations

from soveryn.platform.lattice.content_caps import (
    DREAM_SYNTHESIS_LATTICE_MAX,
    resolve_full_text_ref,
    write_dream_archive,
)
from soveryn.platform.lattice.distill import (
    distill_for_lattice,
    distill_reflection_head,
    dream_lattice_head,
)


def test_prefers_standing_note_label():
    text = (
        "I wandered through the lattice for a while and read old signals.\n\n"
        "Standing note: The dock is quiet tonight; hold the blueprint.\n"
    )
    head = distill_reflection_head(text)
    assert "dock is quiet" in head
    assert "wandered" not in head


def test_falls_back_to_last_paragraph_not_first():
    text = (
        "PREAMBLE that should never be the lattice head because it is throat clearing.\n\n"
        "Middle material about nothing important.\n\n"
        "Final takeaway: the real conclusion lives here and must be preferred."
    )
    head = distill_reflection_head(text)
    assert "Final takeaway" in head
    assert "PREAMBLE" not in head


def test_distill_for_lattice_respects_reflection_cap():
    para = "Sentence one. " * 80
    head = distill_for_lattice("reflection", para)
    assert len(head) <= 500


def test_dream_lattice_head_capped():
    essay = "Night synthesis. " * 200
    head = dream_lattice_head(essay)
    assert len(head) <= DREAM_SYNTHESIS_LATTICE_MAX


def test_resolve_thoughts_log_ref(tmp_path):
    log = tmp_path / "heartbeat_thoughts.jsonl"
    log.write_text(
        '{"pulse_id":"abc","note":"full pulse essay here"}\n',
        encoding="utf-8",
    )
    got = resolve_full_text_ref(
        "thoughts_log:pulse_id=abc", data_root=tmp_path
    )
    assert got == "full pulse essay here"


def test_resolve_dream_archive_ref(tmp_path):
    write_dream_archive(tmp_path, "run-1", "full dream synthesis body")
    got = resolve_full_text_ref("dream_archive:run-1", data_root=tmp_path)
    assert got is not None
    assert "full dream synthesis body" in got
