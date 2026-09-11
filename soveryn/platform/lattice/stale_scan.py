"""Lattice stale detectors (S5.1) — cheap flags, no model calls.

`lattice_stale_scan()` reads the existing LatticeStore (tags, provenance,
supersedes edges) and returns a list of flag dicts. It never writes, never
calls `remember_fact`, and never talks to an LLM.

CLI (CoS on-demand)::

    python -m soveryn.platform.lattice.stale_scan
    python -m soveryn.platform.lattice.stale_scan --db PATH --pinned PATH

Quiet when clean: empty list / `[]` on stdout, exit 0.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from soveryn.platform.lattice.legacy import LatticeStore, Node

try:
    from soveryn.platform.lattice.fact_rail import CANONICAL_FACT_TAG
except ImportError:  # teach rail not on this tree yet
    CANONICAL_FACT_TAG = "canonical_fact"

HISTORICAL_SNAPSHOT_TAG = "historical_snapshot"
ENTITY_TAG_PREFIX = "entity:"
SUPERSEDES_REL = "supersedes"

TTL_DAYS_DEFAULT = 90
TTL_DAYS_BY_ENTITY_PREFIX: dict[str, int] = {
    "house.rule.": 180,
    "cwg.job.": 60,
    "cwg.ads.": 30,
    "lab.": 90,
}
MAX_FLAGS_PER_DIGEST = 20

DETECTOR_TTL = "d1_ttl"
DETECTOR_COLLISION = "d2_entity_collision"
DETECTOR_PIN = "d3_pin_checklist"
DETECTOR_ORPHAN = "d4_orphan_historical"

SEVERITY_LOW = "low"
SEVERITY_MED = "med"
SEVERITY_HIGH = "high"

_SEV_RANK = {SEVERITY_HIGH: 0, SEVERITY_MED: 1, SEVERITY_LOW: 2}

ACTION_TTL = "Re-confirm with Jon or `remember_fact` same entity."
ACTION_COLLISION = (
    "Keep newest, close others via `close_and_supersede` / repair script; "
    "do not silent-delete."
)
ACTION_PIN = "Teach Lattice from Jon; or update pin to match current fact."
ACTION_ORPHAN = "Repair edges / re-run close path; do not invent content."


@dataclass(frozen=True)
class PinChecklistRow:
    """One lexical pin↔Lattice contradiction check. Not free NLP."""

    entity_slug: str
    pin_needle: str
    lattice_needle: str
    invert: bool = False


# Tiny v1 house checklist — injectable in tests. Inverse = swap needles.
DEFAULT_PIN_CHECKLIST: tuple[PinChecklistRow, ...] = (
    PinChecklistRow("cwg.ads.pmax", "paused", "live"),
    PinChecklistRow("house.travel", "hold", "active"),
)


def lattice_stale_scan(
    store: LatticeStore,
    *,
    now: datetime | None = None,
    ttl_days_default: int = TTL_DAYS_DEFAULT,
    ttl_days_by_entity_prefix: Mapping[str, int] | None = None,
    pinned_path: Path | str | None = None,
    pin_checklist: Sequence[PinChecklistRow] | None = None,
    max_flags: int = MAX_FLAGS_PER_DIGEST,
) -> list[dict[str, Any]]:
    """Run D1–D4 over ``store``. Returns flag dicts; empty when clean.

    Never mutates the store. ``pin_checklist`` replaces the default rows when
    provided (including an empty sequence, which disables D3).
    """
    when = _as_utc(now or datetime.now(timezone.utc))
    prefixes = dict(ttl_days_by_entity_prefix or TTL_DAYS_BY_ENTITY_PREFIX)
    checklist = (
        DEFAULT_PIN_CHECKLIST if pin_checklist is None else tuple(pin_checklist)
    )

    nodes = store.iter_nodes(include_library=True)
    edges = _iter_supersedes_edges(store)
    node_ids = {node.id for node in nodes}

    currents = [n for n in nodes if _is_current_canonical(n)]
    historicals = [n for n in nodes if HISTORICAL_SNAPSHOT_TAG in n.tags]

    flags: list[dict[str, Any]] = []
    flags.extend(_detect_ttl(currents, when, ttl_days_default, prefixes))
    flags.extend(_detect_collisions(currents))
    flags.extend(_detect_pin_checklist(currents, pinned_path, checklist))
    flags.extend(_detect_orphan_chains(currents, historicals, edges, node_ids))

    flags.sort(
        key=lambda f: (
            _SEV_RANK.get(str(f.get("severity")), 9),
            str(f.get("detector") or ""),
            str(f.get("lattice_id") or ""),
            str(f.get("summary") or ""),
        )
    )
    return flags[: max(0, int(max_flags))]


def _detect_ttl(
    currents: Sequence[Node],
    now: datetime,
    ttl_days_default: int,
    prefixes: Mapping[str, int],
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for node in currents:
        entity = _entity_slug(node.tags)
        as_of = _fact_as_of(node)
        if as_of is None:
            continue
        age = now - as_of
        ttl = _ttl_for_entity(entity, ttl_days_default, prefixes)
        if age < timedelta(days=ttl):
            continue
        days = age.days
        source = _as_of_source_label(node)
        flags.append(
            _flag(
                DETECTOR_TTL,
                lattice_id=node.id,
                entity=entity,
                summary=(
                    f"Current canonical_fact older than {ttl} days "
                    f"({source} {as_of.date().isoformat()}, {days} days)"
                ),
                severity=_ttl_severity(entity),
                suggested_action=ACTION_TTL,
            )
        )
    return flags


def _detect_collisions(currents: Sequence[Node]) -> list[dict[str, Any]]:
    by_entity: dict[str, list[Node]] = defaultdict(list)
    for node in currents:
        entity = _entity_slug(node.tags)
        if entity:
            by_entity[entity].append(node)

    flags: list[dict[str, Any]] = []
    for entity, group in by_entity.items():
        if len(group) < 2:
            continue
        ordered = sorted(group, key=lambda n: (n.created_at, n.id))
        ids = ", ".join(n.id for n in ordered)
        flags.append(
            _flag(
                DETECTOR_COLLISION,
                lattice_id=ordered[-1].id,
                entity=entity,
                summary=(
                    f"{len(ordered)} current canonical_facts share "
                    f"{ENTITY_TAG_PREFIX}{entity} (ids: {ids})"
                ),
                severity=SEVERITY_HIGH,
                suggested_action=ACTION_COLLISION,
            )
        )
    return flags


def _detect_pin_checklist(
    currents: Sequence[Node],
    pinned_path: Path | str | None,
    checklist: Sequence[PinChecklistRow],
) -> list[dict[str, Any]]:
    if not checklist or pinned_path is None:
        return []
    path = Path(pinned_path)
    if not path.is_file():
        return []
    pin_text = path.read_text(encoding="utf-8", errors="replace")
    if not pin_text:
        return []

    by_entity: dict[str, list[Node]] = defaultdict(list)
    for node in currents:
        entity = _entity_slug(node.tags)
        if entity:
            by_entity[entity].append(node)

    flags: list[dict[str, Any]] = []
    for row in checklist:
        pin_needle, lattice_needle = row.pin_needle, row.lattice_needle
        if row.invert:
            pin_needle, lattice_needle = lattice_needle, pin_needle
        if not pin_needle or not lattice_needle:
            continue
        if not _contains_needle(pin_text, pin_needle):
            continue
        for node in by_entity.get(row.entity_slug, ()):
            if not _contains_needle(node.content, lattice_needle):
                continue
            flags.append(
                _flag(
                    DETECTOR_PIN,
                    lattice_id=node.id,
                    entity=row.entity_slug,
                    summary=(
                        f"Pin has {pin_needle!r} but Lattice current has "
                        f"{lattice_needle!r} for {ENTITY_TAG_PREFIX}{row.entity_slug}"
                    ),
                    severity=SEVERITY_MED,
                    suggested_action=ACTION_PIN,
                )
            )
    return flags


def _detect_orphan_chains(
    currents: Sequence[Node],
    historicals: Sequence[Node],
    edges: Sequence[tuple[str, str, str]],
    node_ids: set[str],
) -> list[dict[str, Any]]:
    """D4: orphan historical, dangling supersedes, same-entity with no edge.

    ``edges`` items are ``(edge_id, source_id, target_id)``.
    """
    flags: list[dict[str, Any]] = []
    current_ids = {n.id for n in currents}

    inbound_from_current: dict[str, list[str]] = defaultdict(list)
    inbound_any: dict[str, list[str]] = defaultdict(list)
    outbound_from: dict[str, list[str]] = defaultdict(list)
    for _edge_id, source_id, target_id in edges:
        inbound_any[target_id].append(source_id)
        outbound_from[source_id].append(target_id)
        if source_id in current_ids:
            inbound_from_current[target_id].append(source_id)

    for hist in historicals:
        if not inbound_from_current.get(hist.id):
            entity = _entity_slug(hist.tags)
            flags.append(
                _flag(
                    DETECTOR_ORPHAN,
                    lattice_id=hist.id,
                    entity=entity,
                    summary=(
                        "historical_snapshot has no inbound supersedes "
                        "from a current fact"
                    ),
                    severity=SEVERITY_MED,
                    suggested_action=ACTION_ORPHAN,
                )
            )

    for edge_id, source_id, target_id in edges:
        missing: list[str] = []
        if source_id not in node_ids:
            missing.append(f"source {source_id}")
        if target_id not in node_ids:
            missing.append(f"target {target_id}")
        if not missing:
            continue
        flags.append(
            _flag(
                DETECTOR_ORPHAN,
                lattice_id=source_id if source_id in node_ids else None,
                entity=None,
                summary=(
                    f"supersedes edge {edge_id} points at missing id "
                    f"({', '.join(missing)})"
                ),
                severity=SEVERITY_MED,
                suggested_action=ACTION_ORPHAN,
            )
        )

    hist_by_entity: dict[str, list[Node]] = defaultdict(list)
    for hist in historicals:
        entity = _entity_slug(hist.tags)
        if entity:
            hist_by_entity[entity].append(hist)

    for node in currents:
        entity = _entity_slug(node.tags)
        if not entity:
            continue
        linked = set(outbound_from.get(node.id, ()))
        for hist in hist_by_entity.get(entity, ()):
            if hist.id == node.id:
                continue
            if not _is_older(hist, node):
                continue
            if hist.id in linked:
                continue
            flags.append(
                _flag(
                    DETECTOR_ORPHAN,
                    lattice_id=node.id,
                    entity=entity,
                    summary=(
                        f"current fact has {ENTITY_TAG_PREFIX}{entity} but older "
                        f"historical {hist.id} has no supersedes edge from current"
                    ),
                    severity=SEVERITY_MED,
                    suggested_action=ACTION_ORPHAN,
                )
            )
    return flags


def _is_current_canonical(node: Node) -> bool:
    tags = set(node.tags)
    if CANONICAL_FACT_TAG not in tags:
        return False
    if HISTORICAL_SNAPSHOT_TAG in tags:
        return False
    return node.type == "fact"


def _entity_slug(tags: Iterable[str]) -> str | None:
    for tag in tags:
        if tag.startswith(ENTITY_TAG_PREFIX) and len(tag) > len(ENTITY_TAG_PREFIX):
            return tag[len(ENTITY_TAG_PREFIX) :]
    return None


def _ttl_for_entity(
    entity: str | None,
    default: int,
    prefixes: Mapping[str, int],
) -> int:
    if not entity:
        return default
    # Longest matching prefix wins (cwg.ads. before cwg.).
    best: int | None = None
    best_len = -1
    for prefix, days in prefixes.items():
        if entity.startswith(prefix) and len(prefix) > best_len:
            best = days
            best_len = len(prefix)
    return default if best is None else best


def _ttl_severity(entity: str | None) -> str:
    if not entity:
        return SEVERITY_LOW
    if entity.startswith("cwg.job.") or entity.startswith("cwg.ads."):
        return SEVERITY_MED
    parts = entity.split(".")
    if "travel" in parts:
        return SEVERITY_MED
    return SEVERITY_LOW


def _fact_as_of(node: Node) -> datetime | None:
    prov = node.provenance if isinstance(node.provenance, dict) else {}
    for key in ("as_of", "temporal_context"):
        parsed = _parse_when(prov.get(key))
        if parsed is not None:
            return parsed
    return _parse_when(node.created_at)


def _as_of_source_label(node: Node) -> str:
    prov = node.provenance if isinstance(node.provenance, dict) else {}
    if _parse_when(prov.get("as_of")) is not None:
        return "as_of"
    if _parse_when(prov.get("temporal_context")) is not None:
        return "temporal_context"
    return "created_at"


def _parse_when(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        date_part = text[:10]
        rest = text[10:]
        if not rest:
            try:
                return datetime.fromisoformat(date_part).replace(tzinfo=timezone.utc)
            except ValueError:
                return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_older(left: Node, right: Node) -> bool:
    left_at = _parse_when(left.created_at) or datetime.min.replace(tzinfo=timezone.utc)
    right_at = _parse_when(right.created_at) or datetime.min.replace(tzinfo=timezone.utc)
    if left_at != right_at:
        return left_at < right_at
    return left.id < right.id


def _contains_needle(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def _iter_supersedes_edges(store: LatticeStore) -> tuple[tuple[str, str, str], ...]:
    with store._conn() as conn:
        rows = conn.execute(
            "SELECT id, source_id, target_id FROM edges "
            "WHERE relationship = ? AND IFNULL(archived, 0) = 0",
            (SUPERSEDES_REL,),
        ).fetchall()
    return tuple((str(r["id"]), str(r["source_id"]), str(r["target_id"])) for r in rows)


def _flag(
    detector: str,
    *,
    lattice_id: str | None,
    entity: str | None,
    summary: str,
    severity: str,
    suggested_action: str,
) -> dict[str, Any]:
    return {
        "detector": detector,
        "lattice_id": lattice_id,
        "entity": entity,
        "summary": summary,
        "severity": severity,
        "suggested_action": suggested_action,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan Lattice for stale / colliding / orphan current facts (D1–D4)."
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=None,
        help="Lattice SQLite path (default: SOVERYN_LATTICE_DB / lattice_vnext.db)",
    )
    parser.add_argument(
        "--pinned",
        type=Path,
        default=None,
        help="pinned_memory.md path (default: SOVERYN_PINNED_MEMORY_PATH)",
    )
    parser.add_argument(
        "--max-flags",
        type=int,
        default=MAX_FLAGS_PER_DIGEST,
        help=f"cap flags (default {MAX_FLAGS_PER_DIGEST})",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    from soveryn.config.loader import load_env_config

    cfg = load_env_config()
    db_path = args.db or cfg.lattice_db
    pinned = args.pinned or cfg.pinned_memory_path

    if not Path(db_path).is_file():
        print(f"lattice stale-scan: db not found: {db_path}", file=sys.stderr)
        return 2

    store = LatticeStore(Path(db_path))
    flags = lattice_stale_scan(
        store,
        pinned_path=pinned if Path(pinned).is_file() else None,
        max_flags=args.max_flags,
    )
    print(json.dumps(flags, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
