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
from soveryn.platform.lattice.legacy import LAYER_PRIVATE, LatticeStore
from soveryn.platform.lattice.teach import (
    ENTITY_TAG_PREFIX,
    HISTORICAL_SNAPSHOT_TAG,
    remember_fact,
)

RECALL_CAP = 3000
# Share of the recall cap reserved for lessons (kernel.lesson.* / kernel.gotcha.*).
# Unused lesson budget flows to recent facts.
LESSON_BUDGET = 1200
LESSON_PREFIXES = ("kernel.lesson.", "kernel.gotcha.")
LESSON_POOL = 40
RECENT_POOL = 24
LESSON_HEADER = "Lessons (current; a newer fact on the same topic replaces the old):"
RECENT_HEADER = "Recent facts:"
_ID_OK = re.compile(r"^[A-Za-z0-9._:-]+$")
_TOPIC_QUERY_OK = re.compile(r"^[a-z0-9][a-z0-9._:-]*$")


def _stores() -> tuple[LatticeStore, AtticStore]:
    from soveryn.config.loader import load_env_config

    env = load_env_config()
    return LatticeStore(env.recall_lattice_db), AtticStore()


def node_topic(node) -> str | None:
    """Entity slug (``entity:<slug>`` tag) of a teach-loop fact, if any."""
    for tag in getattr(node, "tags", None) or ():
        if isinstance(tag, str) and tag.startswith(ENTITY_TAG_PREFIX):
            return tag[len(ENTITY_TAG_PREFIX) :]
    return None


def is_lesson(node) -> bool:
    return (node_topic(node) or "").startswith(LESSON_PREFIXES)


def _node_public(node) -> dict[str, Any]:
    return {
        "id": node.id,
        "topic": node_topic(node),
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


def topic_matches(lattice: LatticeStore, query: str, *, limit: int = 8):
    """Current canonical facts whose topic slug contains ``query`` (e.g. ``kernel.lesson``)."""
    q = (query or "").strip().lower()
    if q.startswith(ENTITY_TAG_PREFIX):
        q = q[len(ENTITY_TAG_PREFIX) :]
    if not q or not _TOPIC_QUERY_OK.match(q):
        return []
    rows = _current_canonical_rows(
        lattice,
        extra_sql="AND IFNULL(tags, '[]') LIKE ?",
        extra_params=(f"%{ENTITY_TAG_PREFIX}%{q}%",),
        limit=max(limit, 1) * 4,
    )
    out = []
    for node in rows:
        if q in (node_topic(node) or ""):
            out.append(node)
            if len(out) >= limit:
                break
    return out


def cmd_search(args: argparse.Namespace) -> dict[str, Any]:
    q = (args.query or "").strip()
    if not q:
        return {"ok": False, "error": "query required"}
    lattice, _attic = _stores()
    limit = max(1, int(args.limit or 8))
    hits = list(topic_matches(lattice, q, limit=limit))
    seen = {n.id for n in hits}
    for node in lattice.find_canonical_facts("kernel", q, limit=limit):
        if node.id not in seen and len(hits) < limit:
            hits.append(node)
            seen.add(node.id)
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


def _current_canonical_rows(
    lattice: LatticeStore,
    *,
    extra_sql: str = "",
    extra_params: tuple = (),
    limit: int = 12,
):
    """Current (non-historical) canonical facts, newest first. Read-only."""
    tag_like = f"%{CANONICAL_FACT_TAG}%"
    hist_like = f"%{HISTORICAL_SNAPSHOT_TAG}%"
    with lattice._conn() as conn:
        rows = conn.execute(
            "SELECT id FROM nodes "
            "WHERE IFNULL(tags, '[]') LIKE ? "
            "  AND IFNULL(tags, '[]') NOT LIKE ? "
            "  AND layer != 'dream' "
            "  AND NOT (agent != 'kernel' AND layer = ?) "
            f"  {extra_sql} "
            "ORDER BY updated_at DESC LIMIT ?",
            (tag_like, hist_like, LAYER_PRIVATE, *extra_params, max(1, limit)),
        ).fetchall()
    nodes = []
    for row in rows:
        node = lattice.get_node(row[0] if not hasattr(row, "keys") else row["id"])
        if node is not None:
            nodes.append(node)
    return nodes


def recent_canonical(lattice: LatticeStore, *, limit: int = 12):
    return _current_canonical_rows(lattice, limit=limit)


def lesson_canonical(lattice: LatticeStore, *, limit: int = LESSON_POOL):
    """Current lesson facts (topic starts with a LESSON_PREFIXES entry), newest first."""
    likes = " OR ".join("IFNULL(tags, '[]') LIKE ?" for _ in LESSON_PREFIXES)
    params = tuple(f"%{ENTITY_TAG_PREFIX}{p}%" for p in LESSON_PREFIXES)
    rows = _current_canonical_rows(
        lattice, extra_sql=f"AND ({likes})", extra_params=params, limit=limit
    )
    return [n for n in rows if is_lesson(n)]


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


def _bullet(node, *, with_topic: bool = False) -> str:
    text = (node.content or "").strip().replace("\n", " ")
    topic = node_topic(node) if with_topic else None
    return f"- [{topic}] {text}" if topic else f"- {text}"


def format_budgeted_recall(
    lessons,
    recent,
    *,
    cap: int = RECALL_CAP,
    lesson_budget: int = LESSON_BUDGET,
) -> str:
    """[HOUSE LATTICE] block: lessons first (up to ``lesson_budget`` chars incl.
    their sub-header), then recent facts until ``cap``. Whole bullets only.
    With no lessons the output keeps the old flat shape.
    """
    lessons = list(lessons or [])
    recent = list(recent or [])
    if not lessons and not recent:
        return ""
    cap = max(1, int(cap))
    lesson_budget = max(0, min(int(lesson_budget), cap))
    lines = ["[HOUSE LATTICE]"]
    used = len(lines[0])
    seen: set[str] = set()
    n_lessons = 0

    if lessons and lesson_budget > 0:
        section = [LESSON_HEADER]
        section_used = len(LESSON_HEADER)
        for node in lessons:
            if node.id in seen:
                continue
            line = _bullet(node, with_topic=True)
            if section_used + 1 + len(line) > lesson_budget or used + 1 + section_used + 1 + len(line) > cap:
                continue
            section.append(line)
            section_used += 1 + len(line)
            seen.add(node.id)
        if len(section) > 1:
            lines.extend(section)
            used += 1 + section_used
            n_lessons = len(section) - 1

    if n_lessons:
        rest = [n for n in recent if n.id not in seen]
        if rest and used + 1 + len(RECENT_HEADER) < cap:
            lines.append(RECENT_HEADER)
            used += 1 + len(RECENT_HEADER)
    else:
        rest = recent
    for node in rest:
        if node.id in seen:
            continue
        line = _bullet(node, with_topic=False)
        if used + 1 + len(line) > cap:
            continue
        lines.append(line)
        used += 1 + len(line)
        seen.add(node.id)
    if lines and lines[-1] == RECENT_HEADER:
        lines.pop()

    blob = "\n".join(lines)
    if len(blob) > cap:  # safety net; whole-bullet fill should never hit this
        blob = blob[: cap - 1].rstrip() + "…"
    return blob


def cmd_recall(args: argparse.Namespace) -> dict[str, Any]:
    lattice, _attic = _stores()
    q = (args.query or "").strip()
    cap = int(args.cap or RECALL_CAP)
    if q:
        nodes = list(lattice.find_canonical_facts("kernel", q, limit=12))
        text = format_recall(nodes, cap=cap)
        return {"ok": True, "text": text, "count": len(nodes), "chars": len(text)}
    lessons = lesson_canonical(lattice, limit=LESSON_POOL)
    recent = recent_canonical(lattice, limit=RECENT_POOL)
    budget = getattr(args, "lesson_budget", None)
    text = format_budgeted_recall(
        lessons,
        recent,
        cap=cap,
        lesson_budget=LESSON_BUDGET if budget is None else int(budget),
    )
    lines = text.splitlines()
    bullets = sum(1 for line in lines if line.startswith("- "))
    shown_lessons = 0
    if LESSON_HEADER in lines:
        for line in lines[lines.index(LESSON_HEADER) + 1 :]:
            if not line.startswith("- "):
                break
            shown_lessons += 1
    return {
        "ok": True,
        "text": text,
        "count": bullets,
        "lessons": shown_lessons,
        "chars": len(text),
    }


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
    p_r.add_argument("--lesson-budget", dest="lesson_budget", type=int, default=LESSON_BUDGET)

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
