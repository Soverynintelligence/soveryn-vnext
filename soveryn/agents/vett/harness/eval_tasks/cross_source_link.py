"""cross_source_link: a SOVERYN-representative phase-1 eval task.

The query asks Vett-in-harness to find nodes about a specific topic
across multiple lattice sources, link the evidence, and verify a claim.
The ``expected_evidence_ids`` are the canonical node IDs surfaced during
Task 11 discovery against the live lattice DB; they become the baseline
that Task 13's comparison run scores Vett-current and Vett-harness
against.

This task exercises:
    - fan_out_search (multiple framings of the topic)
    - read_doc (full-text inspection of candidates)
    - the verification primitive (does the claim survive the evidence?)
    - the curation primitive (which nodes deserve the curated set?)

Sourced from lattice DB: data/memory/lattice_vnext.db (layer='library').
Discovery method: enumerated library-layer nodes (>=200 chars) and picked
the cluster that supports a single technical claim about SOVERYN's
local-first, multi-agent architecture.

Cross-source structure (per Task 11 discovery):
    - One concise system reference node (Aetheria-authored canonical
      description of the platform).
    - Three chunks of the "How We Became SOVERYN" chronicle that
      independently support different facets of the same claim: the
      Council roster (V), the local-no-cloud commitment (VI), and the
      hardware reality that makes it possible (VII).

The CLI runner defaults to ``layer_filter="library"`` (see
``run_eval.py``), which scopes the eval corpus to the shared cross-author
library layer — this matches the IDs chosen below. If the runner is
invoked with ``--layer-filter none``, this task is degenerate (those IDs
will not be in scope).
"""
from __future__ import annotations
from soveryn.agents.vett.harness.eval_tasks import EvalTask, register_task


TOPIC = "SOVERYN's local-first, multi-agent architecture"
CLAIM = (
    "SOVERYN is a fully-local multi-agent system that runs without external "
    "API dependencies and is composed of distinct agents (Aetheria, Vett, "
    "Scotty, Ares, Scout), each with a specific role."
)
EXPECTED_IDS = (
    # Aetheria-authored library node — concise canonical system reference.
    # "The SOVERYN system is a fully-local multi-agent AI platform.
    #  It runs on llama.cpp with no external API dependencies.
    #  Aetheria is the lead agent; Scotty is the engineering executor; ..."
    "7e406410-09d3-43ee-b953-00339dfe626c",
    # Chronicle chunk: "V. The Council" — names Aetheria, V.E.T.T.,
    # Tinker (Scotty's predecessor), Ares with their models and roles.
    "f5c9ccca-eeb0-4200-a5a9-9d136952a00b",
    # Chronicle chunk: continuation of Council (names Scout) into
    # "VI. What We Are Building" — explicit local-first commitment:
    # "Everything runs on hardware Jon owns ... No cloud. No terms of
    # service. No alignment tax."
    "92273e8c-2c32-4ee2-bc6b-f07deb6d613d",
    # Chronicle chunk: "VII. Where This Goes" lead-in — supports the
    # hardware-locality fact: "The 336GB of VRAM that came online in
    # 2026 changed the rules ... No summarizing. No truncating. Just
    # memory."
    "86dde660-c31a-4641-a91a-f5ad8d226ca8",
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
