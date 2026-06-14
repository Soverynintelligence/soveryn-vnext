"""One-shot consolidation: copy legacy lattice.db tables into lattice_vnext.db.

Goal: collapse the dual-DB scheme (vnext writes go to lattice_vnext.db, recall
reads from lattice.db) into a single source of truth. After this runs, vnext's
lattice_vnext.db holds everything: legacy nodes + edges + dream_log +
contradiction_flags, plus the 12 vnext-only seed nodes that already existed.

Design constraints:
- Idempotent. Safe to re-run; nothing duplicated on second run.
- Dry-run mode shows what would happen without writing.
- Backs up the destination DB before any write (the caller's own backup is
  the primary safety net; this is belt-and-braces).
- Phases run in FK order: nodes → edges → dream_log → contradiction_flags.
- Validates post-copy: row counts, zero orphan FK refs.
- Does NOT modify the legacy DB. Read-only against it.

Run as a module:
    python -m soveryn.platform.lattice.consolidate --dry-run
    python -m soveryn.platform.lattice.consolidate
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_LEGACY_DB = Path.home() / "soveryn_complete" / "soveryn_memory" / "lattice.db"
DEFAULT_VNEXT_DB = Path.home() / "soveryn_complete" / "soveryn_memory" / "lattice_vnext.db"


# Schema statements lifted verbatim from legacy lattice.db (no redesign).
SCHEMA_EDGES = """
CREATE TABLE IF NOT EXISTS edges (
    id                  TEXT PRIMARY KEY,
    source_id           TEXT NOT NULL,
    target_id           TEXT NOT NULL,
    relationship        TEXT NOT NULL,
    strength            REAL NOT NULL DEFAULT 0.5,
    bidirectional       INTEGER NOT NULL DEFAULT 1,
    archived            INTEGER NOT NULL DEFAULT 0,
    reinforcement_count INTEGER NOT NULL DEFAULT 1,
    reinforced_at       TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES nodes(id),
    FOREIGN KEY (target_id) REFERENCES nodes(id)
)
"""

SCHEMA_DREAM_LOG = """
CREATE TABLE IF NOT EXISTS dream_log (
    id            TEXT PRIMARY KEY,
    trigger       TEXT NOT NULL,
    agent         TEXT NOT NULL,
    nodes_read    INTEGER DEFAULT 0,
    edges_created INTEGER DEFAULT 0,
    nodes_merged  INTEGER DEFAULT 0,
    contradictions_flagged INTEGER DEFAULT 0,
    summary       TEXT,
    ran_at        TEXT NOT NULL,
    loop_health   REAL DEFAULT NULL
)
"""

SCHEMA_CONTRADICTION_FLAGS = """
CREATE TABLE IF NOT EXISTS contradiction_flags (
    id         TEXT PRIMARY KEY,
    edge_id    TEXT NOT NULL,
    node_a_id  TEXT NOT NULL,
    node_b_id  TEXT NOT NULL,
    flagged_at TEXT NOT NULL,
    reviewed   INTEGER NOT NULL DEFAULT 0,
    resolution TEXT,
    confidence_delta REAL DEFAULT 0.0,
    last_monitored TEXT
)
"""

SCHEMA_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_edges_archived ON edges(archived)",
    "CREATE INDEX IF NOT EXISTS idx_edges_rel      ON edges(relationship)",
    "CREATE INDEX IF NOT EXISTS idx_edges_source   ON edges(source_id)",
    "CREATE INDEX IF NOT EXISTS idx_edges_target   ON edges(target_id)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_agent    ON nodes(agent)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_created  ON nodes(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_layer    ON nodes(layer)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_salience ON nodes(salience DESC)",
    "CREATE INDEX IF NOT EXISTS idx_nodes_type     ON nodes(type)",
]


@dataclass
class PhaseReport:
    name: str
    legacy_count: int
    existing_count_dst: int
    to_copy: int
    copied: int = 0
    skipped_existing: int = 0


def _count(con: sqlite3.Connection, table: str) -> int:
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


def _existing_ids(con: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {r[0] for r in con.execute(f"SELECT id FROM {table}").fetchall()}
    except sqlite3.OperationalError:
        return set()


def extend_schema(dst: sqlite3.Connection, *, dry_run: bool) -> list[str]:
    """Add edges, dream_log, contradiction_flags + indexes if missing. Returns DDL applied."""
    existing_tables = {r[0] for r in dst.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    applied: list[str] = []
    statements = [
        ("edges", SCHEMA_EDGES),
        ("dream_log", SCHEMA_DREAM_LOG),
        ("contradiction_flags", SCHEMA_CONTRADICTION_FLAGS),
    ]
    for table_name, ddl in statements:
        if table_name not in existing_tables:
            applied.append(f"CREATE TABLE {table_name}")
            if not dry_run:
                dst.execute(ddl)
    for idx_ddl in SCHEMA_INDEXES:
        if not dry_run:
            dst.execute(idx_ddl)
        applied.append(idx_ddl.strip().split("\n")[0])
    if not dry_run:
        dst.commit()
    return applied


def _copy_rows(
    src: sqlite3.Connection,
    dst: sqlite3.Connection,
    table: str,
    *,
    id_col: str = "id",
    dry_run: bool,
) -> PhaseReport:
    """Copy rows from src.table → dst.table, skipping existing IDs. Idempotent."""
    legacy_count = _count(src, table)
    existing = _existing_ids(dst, table)
    src_rows = list(src.execute(f"SELECT * FROM {table}").fetchall())
    src_cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 0").description]
    id_idx = src_cols.index(id_col)

    to_copy_rows = [r for r in src_rows if r[id_idx] not in existing]
    report = PhaseReport(
        name=table,
        legacy_count=legacy_count,
        existing_count_dst=len(existing),
        to_copy=len(to_copy_rows),
        skipped_existing=len(src_rows) - len(to_copy_rows),
    )

    if dry_run:
        return report

    if to_copy_rows:
        placeholders = ",".join("?" * len(src_cols))
        col_list = ",".join(src_cols)
        dst.executemany(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            to_copy_rows,
        )
        dst.commit()
    report.copied = len(to_copy_rows)
    return report


def validate(dst: sqlite3.Connection) -> dict:
    """Run integrity checks against the consolidated DB."""
    nodes_count = _count(dst, "nodes")
    edges_count = _count(dst, "edges")
    dream_count = _count(dst, "dream_log")
    flags_count = _count(dst, "contradiction_flags")

    # Orphan edge check: source_id/target_id must resolve to a node.
    orphan_source = dst.execute("""
        SELECT COUNT(*) FROM edges WHERE source_id NOT IN (SELECT id FROM nodes)
    """).fetchone()[0]
    orphan_target = dst.execute("""
        SELECT COUNT(*) FROM edges WHERE target_id NOT IN (SELECT id FROM nodes)
    """).fetchone()[0]

    # Per-agent breakdown
    agent_breakdown = dict(dst.execute(
        "SELECT agent, COUNT(*) FROM nodes GROUP BY agent ORDER BY COUNT(*) DESC"
    ).fetchall())

    quick_check = dst.execute("PRAGMA quick_check").fetchone()[0]

    return {
        "nodes": nodes_count,
        "edges": edges_count,
        "dream_log": dream_count,
        "contradiction_flags": flags_count,
        "orphan_edges_source": orphan_source,
        "orphan_edges_target": orphan_target,
        "agent_breakdown": agent_breakdown,
        "quick_check": quick_check,
    }


def run(
    *,
    legacy_path: Path = DEFAULT_LEGACY_DB,
    vnext_path: Path = DEFAULT_VNEXT_DB,
    dry_run: bool = False,
) -> dict:
    if not legacy_path.is_file():
        raise FileNotFoundError(f"legacy lattice not found at {legacy_path}")
    if not vnext_path.is_file():
        raise FileNotFoundError(f"vnext lattice not found at {vnext_path}")

    # Belt-and-braces backup of destination (caller's own backup is primary).
    if not dry_run:
        ts = int(time.time())
        snap = vnext_path.with_suffix(f".db.consolidate-snap-{ts}")
        shutil.copy2(vnext_path, snap)
        snap_msg = str(snap)
    else:
        snap_msg = "(skipped — dry-run)"

    src = sqlite3.connect(str(legacy_path))
    dst = sqlite3.connect(str(vnext_path))

    # Open destination with FK enforcement ON so we'd catch bad refs at insert time.
    dst.execute("PRAGMA foreign_keys = ON")

    schema_applied = extend_schema(dst, dry_run=dry_run)
    node_report = _copy_rows(src, dst, "nodes", dry_run=dry_run)
    edge_report = _copy_rows(src, dst, "edges", dry_run=dry_run)
    dream_report = _copy_rows(src, dst, "dream_log", dry_run=dry_run)
    flag_report = _copy_rows(src, dst, "contradiction_flags", dry_run=dry_run)

    final = validate(dst) if not dry_run else None

    src.close()
    dst.close()

    return {
        "dry_run": dry_run,
        "destination_backup": snap_msg,
        "schema_applied": schema_applied,
        "nodes": node_report,
        "edges": edge_report,
        "dream_log": dream_report,
        "contradiction_flags": flag_report,
        "final_validation": final,
    }


def _print_phase(p: PhaseReport, dry_run: bool) -> None:
    verb = "would copy" if dry_run else "copied"
    print(f"  {p.name:25s}  legacy={p.legacy_count:6d}  dst_existing={p.existing_count_dst:6d}  "
          f"{verb}={p.to_copy:6d}  skipped_dup={p.skipped_existing}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="show plan, don't write")
    ap.add_argument("--legacy", type=Path, default=DEFAULT_LEGACY_DB)
    ap.add_argument("--vnext", type=Path, default=DEFAULT_VNEXT_DB)
    args = ap.parse_args()

    print(f"legacy: {args.legacy}")
    print(f"vnext:  {args.vnext}")
    print(f"dry_run: {args.dry_run}")
    print()

    result = run(legacy_path=args.legacy, vnext_path=args.vnext, dry_run=args.dry_run)

    print(f"destination backup: {result['destination_backup']}")
    print(f"schema applied ({len(result['schema_applied'])} statements):")
    for s in result["schema_applied"]:
        print(f"  {s}")
    print()
    print("phase summary:")
    for k in ("nodes", "edges", "dream_log", "contradiction_flags"):
        _print_phase(result[k], dry_run=args.dry_run)

    if result["final_validation"] is not None:
        v = result["final_validation"]
        print()
        print(f"final validation:")
        print(f"  quick_check: {v['quick_check']}")
        print(f"  nodes={v['nodes']}  edges={v['edges']}  dream={v['dream_log']}  flags={v['contradiction_flags']}")
        print(f"  orphan_edges (source_id): {v['orphan_edges_source']}")
        print(f"  orphan_edges (target_id): {v['orphan_edges_target']}")
        print(f"  agent_breakdown: {v['agent_breakdown']}")
        if v["orphan_edges_source"] or v["orphan_edges_target"] or v["quick_check"] != "ok":
            print("\n  *** VALIDATION FAILED ***")
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
