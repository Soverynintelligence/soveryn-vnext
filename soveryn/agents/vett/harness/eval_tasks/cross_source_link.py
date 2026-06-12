"""cross_source_link: a SOVERYN-representative phase-1 eval task.

The query asks Vett-in-harness to find nodes about a specific topic
across multiple lattice sources, link the evidence, and verify a claim.
The ``expected_evidence_ids`` are the canonical node IDs in the live
lattice; they form the baseline that Task 13 (and any subsequent
comparison run) scores Vett-current and Vett-harness against.

This task exercises:
    - fan_out_search (multiple framings of the topic)
    - read_doc (full-text inspection of candidates)
    - the verification primitive (does the claim survive the evidence?)
    - the curation primitive (which nodes deserve the curated set?)

Re-baseline 2026-06-12 (post-Subconscious cleanup arc):
    The original expected_evidence_ids were four chronicle chunks from
    the April 2026 "How_We_Became_SOVERYN" document. Those chunks were
    tagged ``historical_snapshot`` on 2026-06-12 once retrieval-side
    enforcement landed (commit fecdf78), so they no longer surface in
    default current-state queries. The original baseline was measuring
    retrieval against ghosts.

    The post-cleanup expected IDs are the three current-state library-
    layer nodes:
        - canonical hardware-state node (VRAM ceiling) — bc6e16f3
        - canonical system description (Aetheria-authored) — 7e406410
        - DAC pipe validation milestone (Scotty operational) — b42064cc

    The claim is recast to be a current-state synthesis that requires all
    three sources to verify, not a historical chronicle paraphrase.

Known asymmetry between Vett-current and Vett-in-harness paths:
    Vett-current's chat path receives chronicle content via some
    upstream prompt-build mechanism (NOT lattice retrieval — verified
    2026-06-12: her lattice_store is not even configured per
    startup.py:426, and the historical_snapshot filter at the lattice
    layer is provably correct). The leak source is upstream — likely
    library injection at vnext app level, tool descriptions, cross-
    surface continuity, or hardwired prompt context.

    Vett-current's response on the 2026-06-12 baseline run cited three
    historical_snapshot-tagged chronicle chunks AND correctly
    adjudicated them as historical, choosing the canonical anchors
    over the ghost references. Adjudication capability is itself a
    real measurement.

    The Vett-in-harness / Harness-1 paths operate on a strictly clean
    substrate (no ghost-hints injected). The comparison therefore
    measures: can a harness-bound model match Vett-current's content
    coverage while operating on less context? This is a sterner
    test, not an unfair one — but the asymmetry should be named.

Sourced from lattice DB: data/memory/lattice_vnext.db (layer='library').

The CLI runner defaults to ``layer_filter="library"`` (see
``run_eval.py``), which scopes the eval corpus to the shared cross-author
library layer — this matches the IDs chosen below. If the runner is
invoked with ``--layer-filter none``, this task is degenerate (those IDs
will not be in scope).
"""
from __future__ import annotations
from soveryn.agents.vett.harness.eval_tasks import EvalTask, register_task


TOPIC = "SOVERYN's current-state architecture, agent roster, and hardware fleet"
CLAIM = (
    "SOVERYN is a fully-local multi-agent AI platform with Scotty as the "
    "engineering agent (renamed from Tinker on 2026-05-02), running on a "
    "143 GiB VRAM fleet across three GPUs (2x Quadro RTX 8000 + 1x RTX PRO "
    "5000 Blackwell)."
)
EXPECTED_IDS = (
    # Canonical hardware-state node: 143 GiB VRAM ceiling, 3 GPUs.
    # Anchors the hardware claim. Written 2026-06-12 by Aetheria,
    # tags=[canonical_hardware_state, vram_ceiling, ground_truth].
    "bc6e16f3-a251-4791-8547-3f2a8da2058e",
    # Canonical system reference node: "The SOVERYN system is a
    # fully-local multi-agent AI platform. It runs on llama.cpp with
    # no external API dependencies." Authoritative current-state
    # description, library-layer, Aetheria-authored 2026-05-04.
    "7e406410-09d3-43ee-b953-00339dfe626c",
    # DAC pipe validation milestone: "First Direct Agent Communication
    # pipe validated — 2026-06-05. Scotty (execution)..." Proves Scotty
    # exists and is operational under current-state. Substitute for the
    # rename-announcement (which lived in the global layer and would
    # have been out of scope for library-filter retrieval).
    "b42064cc-fce8-4b84-940d-ff4faf2eec75",
)


CROSS_SOURCE_LINK = EvalTask(
    name="cross_source_link",
    query=(
        f"Search the lattice for evidence about this topic: {TOPIC}\n"
        f"Once you have candidate documents, verify this claim against them: {CLAIM}\n"
        "Curate the strongest evidence set, link the documents that mutually "
        "support the claim, and stop when you've reached a confident "
        "verification or determined the claim is unsupported."
    ),
    expected_evidence_ids=EXPECTED_IDS,
)


register_task(CROSS_SOURCE_LINK)
