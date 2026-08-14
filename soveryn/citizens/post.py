"""House Post — how citizens talk without inventing a cloud chat room.

Messages are house-local, durable, and visible. They land in SQLite *and* on
the recipient's desk (`inbox/`), so a citizen (or Jon) can open a file without
the board. They are not free-form multiplayer chat: kinds are deliberate.

Kinds
-----
  memo       ordinary note
  request    ask another citizen (or the Chief of Staff) for something
  directive  COS → citizen assignment / standing order
  report     citizen → COS (or peer) result
  ack        short receipt

Chief of Staff
--------------
Aetheria holds the COS role (duty `aetheria:chief_of_staff`). Jon and peers can
address her with a `request`; she routes by commissioning Vett/Scotty and/or
sending a `directive`. Routing is *structural* here — the actual LLM judgment
is still a commission she runs when the worker drains her queue.
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any

from soveryn.citizens.census import DESK_DIRS

CHIEF_OF_STAFF_ID = "aetheria"

KINDS = frozenset({"memo", "directive", "report", "request", "ack"})
STATES = frozenset({"unread", "read", "acted"})


def send(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    body: str,
    at: str,
    kind: str = "memo",
    subject: str | None = None,
    commission_id: str | None = None,
) -> str:
    """Post a message. Returns the post id. Writes desk inbox when workspace known."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {sorted(KINDS)}")
    if not body.strip():
        raise ValueError("post body required")
    if from_id == to_id:
        raise ValueError("cannot post to self — use notes/")
    post_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO house_post "
        "(id, from_id, to_id, kind, subject, body, state, commission_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'unread', ?, ?)",
        (
            post_id,
            from_id,
            to_id,
            kind,
            (subject or "").strip() or None,
            body.strip(),
            commission_id,
            at,
        ),
    )
    conn.commit()
    _write_desk_copy(conn, post_id, from_id, to_id, kind, subject, body, at)
    return post_id


def _write_desk_copy(
    conn: sqlite3.Connection,
    post_id: str,
    from_id: str,
    to_id: str,
    kind: str,
    subject: str | None,
    body: str,
    at: str,
) -> None:
    row = conn.execute(
        "SELECT workspace_path FROM citizens WHERE id = ?", (to_id,)
    ).fetchone()
    if row is None or not row["workspace_path"]:
        return
    root = Path(row["workspace_path"])
    for name in DESK_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    subj = (subject or kind).replace("/", "-")[:60]
    path = root / "inbox" / f"{at.replace(':', '')}_{kind}_{post_id[:8]}.md"
    path.write_text(
        f"# House Post · {kind}\n\n"
        f"- **id:** {post_id}\n"
        f"- **from:** {from_id}\n"
        f"- **to:** {to_id}\n"
        f"- **at:** {at}\n"
        f"- **subject:** {subj}\n\n"
        f"{body.strip()}\n",
        encoding="utf-8",
    )


def list_for(
    conn: sqlite3.Connection,
    citizen_id: str,
    *,
    box: str = "inbox",
    limit: int = 50,
    state: str | None = None,
) -> list[dict[str, Any]]:
    """box=inbox → to_id; box=outbox → from_id; box=all → either."""
    limit = max(1, min(int(limit), 200))
    if box == "inbox":
        q = "SELECT * FROM house_post WHERE to_id = ?"
        args: list[Any] = [citizen_id]
    elif box == "outbox":
        q = "SELECT * FROM house_post WHERE from_id = ?"
        args = [citizen_id]
    else:
        q = "SELECT * FROM house_post WHERE to_id = ? OR from_id = ?"
        args = [citizen_id, citizen_id]
    if state:
        if state not in STATES:
            raise ValueError(f"state must be one of {sorted(STATES)}")
        q += " AND state = ?"
        args.append(state)
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def recent(conn: sqlite3.Connection, *, limit: int = 30) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM house_post ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    ]


def mark_read(conn: sqlite3.Connection, post_id: str, *, at: str) -> bool:
    cur = conn.execute(
        "UPDATE house_post SET state = 'read', read_at = ? "
        "WHERE id = ? AND state = 'unread'",
        (at, post_id),
    )
    conn.commit()
    return cur.rowcount > 0


def mark_acted(conn: sqlite3.Connection, post_id: str, *, at: str) -> bool:
    cur = conn.execute(
        "UPDATE house_post SET state = 'acted', read_at = COALESCE(read_at, ?) "
        "WHERE id = ?",
        (at, post_id),
    )
    conn.commit()
    return cur.rowcount > 0


def route_via_cos(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    assignee_id: str,
    body: str,
    at: str,
    subject: str | None = None,
) -> dict[str, str]:
    """Jon or a peer asks COS to put work on a citizen's commission queue.

    Writes:
      1. request  from_id → COS (audit)
      2. commission on assignee
      3. directive COS → assignee (with commission id)
    """
    from soveryn.citizens import commissions

    if assignee_id == CHIEF_OF_STAFF_ID:
        # Work for COS herself — commission only (no self-post).
        cid = commissions.enqueue(conn, CHIEF_OF_STAFF_ID, body, at=at)
        req = ""
        if from_id != CHIEF_OF_STAFF_ID:
            req = send(
                conn,
                from_id=from_id,
                to_id=CHIEF_OF_STAFF_ID,
                body=body,
                at=at,
                kind="request",
                subject=subject or "commission for COS",
                commission_id=cid,
            )
        return {
            "request_post_id": req,
            "commission_id": cid,
            "assignee_id": CHIEF_OF_STAFF_ID,
        }

    req = ""
    if from_id != CHIEF_OF_STAFF_ID:
        req = send(
            conn,
            from_id=from_id,
            to_id=CHIEF_OF_STAFF_ID,
            body=f"Please assign to **{assignee_id}**:\n\n{body.strip()}",
            at=at,
            kind="request",
            subject=subject or f"route to {assignee_id}",
        )
    cid = commissions.enqueue(conn, assignee_id, body, at=at)
    directive = send(
        conn,
        from_id=CHIEF_OF_STAFF_ID,
        to_id=assignee_id,
        body=(
            f"Directive from Chief of Staff"
            f"{'' if from_id == CHIEF_OF_STAFF_ID else f' (on behalf of {from_id})'}.\n\n"
            f"{body.strip()}\n\n"
            f"_Commission `{cid}` is on your queue._"
        ),
        at=at,
        kind="directive",
        subject=subject or "assignment",
        commission_id=cid,
    )
    if req:
        mark_acted(conn, req, at=at)
    return {
        "request_post_id": req,
        "directive_post_id": directive,
        "commission_id": cid,
        "assignee_id": assignee_id,
    }


def report_to_cos(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    body: str,
    at: str,
    commission_id: str | None = None,
    subject: str | None = None,
) -> str:
    """Citizen reports upward. No-op self-post if from_id is already COS."""
    if from_id == CHIEF_OF_STAFF_ID:
        return ""
    return send(
        conn,
        from_id=from_id,
        to_id=CHIEF_OF_STAFF_ID,
        body=body,
        at=at,
        kind="report",
        subject=subject or "commission report",
        commission_id=commission_id,
    )


def unread_for_cos(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    return list_for(
        conn, CHIEF_OF_STAFF_ID, box="inbox", limit=limit, state="unread"
    )
