"""One-shot seed of house / CWG teach facts into live lattice_vnext.db.

Idempotent by entity: same content → no-op; different → close-and-supersede.

Usage (from repo root)::

    python -m soveryn.platform.lattice.seed_teach
    python -m soveryn.platform.lattice.seed_teach --dry-run
"""

from __future__ import annotations

from soveryn.paths import SoverynPaths

import argparse
import json
import os
import sys
from pathlib import Path

from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.teach import remember_fact

# Optional untracked customer facts (PII). Env overrides the default path.
CUSTOMER_FACTS_ENV = "SOVERYN_SEED_CUSTOMER_FACTS"
CUSTOMER_FACTS_FILENAME = "seed_customer_facts.json"

# Spec seed list (2026-09-06 lattice teach loop). Content ≤400 chars.
# Customer-specific names, notes, and phone numbers live in the optional
# local file — never in this public list.
SEED_FACTS: tuple[tuple[str, str], ...] = (
    (
        "house.rule.no_street_address",
        "CWG has no public street address (home = office); service-area business only.",
    ),
    (
        "cwg.ads.pmax",
        "CWG Google Ads Performance Max is paused; account and conversion tag kept.",
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
    return SoverynPaths.root() / "data" / "memory" / "lattice_vnext.db"


def customer_facts_path() -> Path:
    override = (os.environ.get(CUSTOMER_FACTS_ENV) or "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / "soveryn_vnext" / "data" / "memory" / CUSTOMER_FACTS_FILENAME


def load_customer_facts(path: Path | None = None) -> tuple[tuple[str, str], ...]:
    """Read optional local customer facts. Missing or unreadable → empty."""
    target = path if path is not None else customer_facts_path()
    try:
        if not target.is_file():
            return ()
        raw = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return ()
    if not isinstance(raw, list):
        return ()
    facts: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            entity, content = str(item[0]).strip(), str(item[1]).strip()
        elif isinstance(item, dict):
            entity = str(item.get("entity") or "").strip()
            content = str(item.get("content") or "").strip()
        else:
            continue
        if entity and content:
            facts.append((entity, content))
    return tuple(facts)


def all_seed_facts() -> tuple[tuple[str, str], ...]:
    return SEED_FACTS + load_customer_facts()


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

    facts = all_seed_facts()
    if args.dry_run:
        for entity, content in facts:
            print(f"DRY {entity}: {content}")
        return 0

    lattice = LatticeStore(db)
    attic = AtticStore()
    results = []
    for entity, content in facts:
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
