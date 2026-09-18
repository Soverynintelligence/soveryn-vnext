"""Kernel lattice CLI — remember / search / get / recall on the house Lattice.

Used by the flag-gated Pi extension and by tests. Does not write souls.
Flag for Messages is SOVERYN_KERNEL_LATTICE; this CLI is safe to call anytime
(it only writes when `remember` is invoked).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from soveryn.platform.lattice.attic import AtticStore
from soveryn.platform.lattice.fact_rail import CANONICAL_FACT_TAG
from soveryn.platform.lattice.legacy import LatticeStore
from soveryn.platform.lattice.teach import HISTORICAL_SNAPSHOT_TAG, remember_fact

RECALL_CAP = 3000
_ID_OK = re.compile(r"^[A-Za-z0-9._:-]+$")


def _stores() -> tuple[LatticeStore, AtticStore]:
    from soveryn.config.loader import load_env_config

    env = load_env_config()
    return LatticeStore(env.recall_lattice_db), AtticStore()


def _node_public(node) -> dict[str, Any]:
    return {
        "id": node.id,
        "content": node.content,
        "tags": list(node.tags or []),
        "updated_at": getattr(node, "updated_at", None),
        "agent": getattr(node, "agent", None),
    }


def cmd_remember(args: argparse.Namespace) -> dict[str, Any]:
    content = (args.content or "").strip()
    if not content:
        return {"ok": False, "error": "content must be non-empty"}
    if len(content) > 400:
        return {"ok": False, "error": "content must be ≤400 chars"}
    lattice, attic = _stores()
    return remember_fact(
        content,
        entity=(args.entity or "").strip() or None,
        source=(args.source or "jon").strip() or "jon",
        as_of=(args.as_of or "").strip() or None,
        lattice_store=lattice,
        attic_store=attic,
        agent="kernel",
    )


def cmd_search(args: argparse.Namespace) -> dict[str, Any]:
    q = (args.query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}
    lattice, _attic = _stores()
    hits = lattice.find_canonical_facts("kernel", q, limit=max(1, int(args.limit or 8)))
    return {"ok": True, "count": len(hits), "facts": [_node_public(n) for n in hits]}


def cmd_get(args: argparse.Namespace) -> dict[str, Any]:
    lid = (args.id or "").strip()
    if not lid or not _ID_OK.match(lid):
        return {"ok": False, "error": "invalid lattice id"}
    lattice, _attic = _stores()
    node = lattice.get_node(lid)
    if node is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "fact": _node_public(node)}


def recent_canonical(lattice: LatticeStore, *, limit: int = 12):
    tag_like = f"%{CANONICAL_FACT_TAG}%"
    hist_like = f"%{HISTORICAL_SNAPSHOT_TAG}%"
    with lattice._conn() as conn:
        rows = conn.execute(
            "SELECT id FROM nodes "
            "WHERE IFNULL(tags, '[]') LIKE ? "
            "  AND IFNULL(tags, '[]') NOT LIKE ? "
            "  AND layer != 'dream' "
            "ORDER BY updated_at DESC LIMIT ?",
            (tag_like, hist_like, max(1, limit)),
        ).fetchall()
    nodes = []
    for row in rows:
        node = lattice.get_node(row[0] if not hasattr(row, "keys") else row["id"])
        if node is not None:
            nodes.append(node)
    return nodes


def format_recall(nodes, *, cap: int = RECALL_CAP) -> str:
    if not nodes:
        return ""
    lines = ["[HOUSE LATTICE]"]
    for node in nodes:
        text = (node.content or "").strip().replace("\n", " ")
        lines.append(f"- {text}")
    blob = "\n".join(lines)
    if len(blob) > cap:
        blob = blob[: cap - 1].rstrip() + "…"
    return blob


def cmd_recall(args: argparse.Namespace) -> dict[str, Any]:
    lattice, _attic = _stores()
    q = (args.query or "").strip()
    if q:
        nodes = list(lattice.find_canonical_facts("kernel", q, limit=12))
    else:
        nodes = recent_canonical(lattice, limit=12)
    text = format_recall(nodes, cap=int(args.cap or RECALL_CAP))
    return {"ok": True, "text": text, "count": len(nodes), "chars": len(text)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kernel_memory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_rem = sub.add_parser("remember")
    p_rem.add_argument("--content", required=True)
    p_rem.add_argument("--entity", default="")
    p_rem.add_argument("--source", default="jon")
    p_rem.add_argument("--as-of", dest="as_of", default="")

    p_s = sub.add_parser("search")
    p_s.add_argument("--query", required=True)
    p_s.add_argument("--limit", type=int, default=8)

    p_g = sub.add_parser("get")
    p_g.add_argument("--id", required=True)

    p_r = sub.add_parser("recall")
    p_r.add_argument("--query", default="")
    p_r.add_argument("--cap", type=int, default=RECALL_CAP)

    args = parser.parse_args(argv)
    dispatch = {
        "remember": cmd_remember,
        "search": cmd_search,
        "get": cmd_get,
        "recall": cmd_recall,
    }
    out = dispatch[args.cmd](args)
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
