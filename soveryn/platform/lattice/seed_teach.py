"""One-shot seed of house / CWG teach facts into live lattice_vnext.db.

Idempotent by entity: same content → no-op; different → close-and-supersede.

Usage (from repo root)::

    python -m soveryn.platform.lattice.seed_teach
    python -m soveryn.platform.lattice.seed_teach --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.teach import remember_fact

# Spec seed list (2026-09-06 lattice teach loop). Content ≤400 chars.
SEED_FACTS: tuple[tuple[str, str], ...] = (
    (
        "house.rule.no_street_address",
        "CWG has no public street address (home = office); service-area business + (910) 581-3970 only.",
    ),
    (
        "cwg.ads.pmax",
        "CWG Google Ads Performance Max is paused; account and conversion tag kept.",
    ),
    (
        "cwg.job.dan_ward",
        "Dan Ward rebuild is ON HOLD — do not quote or lock dollars.",
    ),
    (
        "cwg.job.valkanoff",
        "Andrew Valkanoff: paid; do not contact; CWG owes two fish; twice-yearly service $170.",
    ),
    (
        "cwg.rule.travel",
        "Builds: travel where customer pays; green-water / maintenance stay local Sandhills (not Charlotte green-water).",
    ),
    (
        "lab.voice.tts",
        "Aetheria TTS = Kokoro (not F5).",
    ),
    (
        "lab.kernel.runtime",
        "Kernel = OpenCode + vLLM on Sparks; not Hermes runtime.",
    ),
    (
        "house.bench.vett",
        "Vett folded into Eve — no live Vett seat.",
    ),
    (
        "cwg.supplier.aquascape",
        "Aquascape Inc = supplier / trend signal for backyard ideas — not a peer competitor.",
    ),
    (
        "cwg.web.estimator",
        "Estimator locked; pondwright.com public build on hold.",
    ),
)


def default_lattice_db() -> Path:
    return Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Lattice teach-loop house facts")
    parser.add_argument(
        "--db",
        type=Path,
        default=default_lattice_db(),
        help="Path to lattice_vnext.db",
    )
    parser.add_argument(
        "--agent",
        default="aetheria",
        help="Agent credited on write (default aetheria)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned teaches without writing",
    )
    args = parser.parse_args(argv)

    db = args.db.expanduser().resolve()
    if not db.is_file():
        print(f"ERROR: lattice db not found: {db}", file=sys.stderr)
        return 2

    if args.dry_run:
        for entity, content in SEED_FACTS:
            print(f"DRY {entity}: {content}")
        return 0

    lattice = LatticeStore(db)
    attic = AtticStore()
    results = []
    for entity, content in SEED_FACTS:
        out = remember_fact(
            content,
            entity=entity,
            source="jon",
            as_of="2026-09-06",
            lattice_store=lattice,
            attic_store=attic,
            agent=args.agent,
            embed_fn=None,  # night librarian backfill; avoid live embed hit
        )
        results.append((entity, out))
        status = "ok" if out.get("ok") else "FAIL"
        extra = ""
        if out.get("unchanged"):
            extra = " (unchanged)"
        elif out.get("superseded_id"):
            extra = f" (superseded {out['superseded_id'][:8]}…)"
        print(f"{status} {entity} → {out.get('lattice_id', out)}{extra}")

    ok_n = sum(1 for _, r in results if r.get("ok"))
    print(f"done: {ok_n}/{len(results)} ok")
    return 0 if ok_n == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
