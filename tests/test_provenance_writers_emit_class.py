"""Every provenance payload written must be readable by the provenance parser.

`_provenance_from_payload` requires BOTH `cls` and `source`, and returns None
without either. A None provenance drops the entry to Channel B, where it is
never assertable.

On 2026-08-03 that had happened to 1,045 nodes — 39% of the lattice. Every one
carried real, specific provenance:

    {"source": "heartbeat", "pulse_id": "db9f456d-…", "ts": "2026-06-02T12:00"}
    {"dream_run_id": "84420f66-…", "passes_visible": {…}}
    {"archived_lesson_id": "19cee227-…", "board": "Blueprint", "owner": "aetheria"}

A pulse she executed, a dream run she produced, a board she archived. None had
`cls`, so the reader discarded all of it and only 12 nodes in the whole lattice
were assertable. The writers and the reader had drifted apart with nothing
checking that they agreed.

This test is that check: construct what each writer constructs, and assert the
reader can parse it back.
"""
from __future__ import annotations

import pytest

from soveryn.agents.aetheria.tool_results import _provenance_from_payload
from soveryn.platform.lattice.provenance import ProvenanceClass

VALID = {c.value for c in ProvenanceClass}


def _assert_readable(payload: dict, who: str) -> None:
    prov = _provenance_from_payload(payload)
    assert prov is not None, (
        f"{who} writes provenance the reader cannot parse: {payload!r}. "
        "Both 'cls' and 'source' are required — without them the entry is "
        "unassertable no matter how specific the rest of the payload is."
    )
    assert str(prov.cls) in VALID, f"{who} wrote an unknown class {prov.cls!r}"


def test_reader_rejects_payload_without_class():
    """Guard the guard — the requirement this test exists to enforce is real."""
    assert _provenance_from_payload({"source": "heartbeat", "pulse_id": "x"}) is None
    assert _provenance_from_payload({"cls": "witnessed"}) is None


def test_heartbeat_pulse_provenance_is_readable():
    _assert_readable(
        {"cls": "witnessed", "source": "heartbeat",
         "pulse_id": "db9f456d-0fa1-4f20-be2e-481ccca438ec",
         "ts": "2026-06-02T12:00:00"},
        "heartbeat/daemon.py",
    )


def test_library_write_provenance_is_readable():
    _assert_readable(
        {"cls": "witnessed", "source": "library_write", "written_by": "vett"},
        "platform/library/tools.py",
    )


def test_coordination_provenance_is_readable():
    from soveryn.platform.coordination.store import _provenance_for

    class _Board:
        value = "Blueprint"

    class _Status:
        value = "Archived"

    class _Node:
        board = _Board()
        status = _Status()
        owner = "aetheria"
        lattice_ref = None
        archived_lesson_id = "19cee227-731d-47b3-a4aa-e7099a9e2eba"

    _assert_readable(_provenance_for(_Node()), "coordination/store.py::_provenance_for")


def test_x_post_provenance_is_readable():
    posted_id = "1234567890"
    _assert_readable(
        {"cls": "witnessed",
         "source": f"https://x.com/i/web/status/{posted_id}",
         "posted_id": posted_id, "edited_by_jon": False},
        "presence/x_memory.py",
    )


def test_intent_ledger_provenance_is_readable():
    _assert_readable(
        {"cls": "witnessed", "source": "deliberate_share",
         "kind": "deliberate_share", "why": "signal", "stance": "flag"},
        "platform/intent/ledger.py",
    )


@pytest.mark.parametrize("cls", sorted(VALID))
def test_every_declared_class_parses(cls):
    """The enum and the parser must agree on the whole vocabulary.

    INFERRED additionally requires `derived_from` — an inference must name what
    it was inferred from, or it is an assertion wearing a class. That is the
    cite-or-drop rule applied to the taxonomy itself, and it is why a bare
    {"cls": "inferred"} is correctly refused.
    """
    payload = {"cls": cls, "source": "test"}
    if cls == "inferred":
        payload["derived_from"] = ["node-1"]
    prov = _provenance_from_payload(payload)
    assert prov is not None, f"{cls!r} is in ProvenanceClass but the parser rejects it"


def test_inferred_without_derived_from_is_refused():
    """The constraint above, asserted directly so it cannot be relaxed quietly."""
    assert _provenance_from_payload({"cls": "inferred", "source": "test"}) is None
