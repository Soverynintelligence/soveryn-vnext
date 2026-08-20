#!/usr/bin/env python3
"""Night librarian (~03:00): backfill Lattice nodes missing embeddings.

Uses the configured embeddings server (Spark Nemotron-Embed-8B after the move).
Does NOT use Lightning chat weights — vectors must stay in embed-8B space.

Embed-on-write still runs all day for new nodes; this pass catches stragglers.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def _find_db(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if p.is_file():
            return p
    # The live Lattice is data/memory/lattice_vnext.db. The three bare
    # "lattice.db" paths below never existed, so this pass had been exiting 1
    # every night since it was installed (fixed 2026-08-20). Real path first,
    # legacy names kept as fallbacks.
    for cand in (
        REPO / "data" / "memory" / "lattice_vnext.db",
        Path.home() / "soveryn_vnext" / "data" / "memory" / "lattice_vnext.db",
        REPO / "data" / "lattice.db",
        Path.home() / "soveryn_vnext" / "data" / "lattice.db",
        Path.home() / "soveryn_data" / "lattice.db",
    ):
        if cand.is_file():
            return cand
    raise SystemExit(
        "lattice db not found; looked for data/memory/lattice_vnext.db "
        "(and legacy lattice.db paths). Pass --db to override."
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--limit", type=int, default=400)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = _find_db(args.db)
    print(f"night librarian db={db}")

    from soveryn.platform.lattice.legacy import embed_text

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cols = {r[1] for r in con.execute("PRAGMA table_info(nodes)").fetchall()}
    if "embedding" not in cols:
        print("no embedding column")
        return 0

    # Prefer content-ish columns that exist
    text_cols = [c for c in ("content", "body", "text", "title", "summary") if c in cols]
    if not text_cols:
        print("no text columns on nodes")
        return 0
    coalesce = ", ".join(f"NULLIF(TRIM({c}), '')" for c in text_cols)
    sql = f"""
        SELECT id, COALESCE({coalesce}, '') AS blob
        FROM nodes
        WHERE embedding IS NULL
          AND COALESCE({coalesce}, '') != ''
        ORDER BY rowid ASC
        LIMIT ?
    """
    rows = con.execute(sql, (args.limit,)).fetchall()
    print(f"missing embeddings: {len(rows)} (limit={args.limit})")
    if args.dry_run or not rows:
        return 0

    ok = fail = 0
    t0 = time.perf_counter()
    for row in rows:
        text = (row["blob"] or "")[:8000]
        try:
            vec = embed_text(text, prompt="document")
            emb_json = json.dumps(list(vec))
            if "embedding_f32" in cols:
                # use store encoder if available
                try:
                    from soveryn.platform.lattice.legacy import _encode_embedding_blob
                    blob = _encode_embedding_blob(vec)
                    con.execute(
                        "UPDATE nodes SET embedding = ?, embedding_f32 = ? WHERE id = ?",
                        (emb_json, blob, row["id"]),
                    )
                except Exception:
                    con.execute(
                        "UPDATE nodes SET embedding = ? WHERE id = ?",
                        (emb_json, row["id"]),
                    )
            else:
                con.execute(
                    "UPDATE nodes SET embedding = ? WHERE id = ?",
                    (emb_json, row["id"]),
                )
            con.commit()
            ok += 1
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"  fail {row['id']}: {e}", file=sys.stderr)
            if fail >= 15:
                break

    print(f"done ok={ok} fail={fail} wall={time.perf_counter()-t0:.1f}s")
    con.close()
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
