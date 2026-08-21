"""ApprovalStore — SQLite store for Approval Gate requests, one row per egress call.

Keyed on a deterministic ``id`` derived from ``citizen + tool + now + args``
(never random). There is no session_id anywhere in this module: the gate is
per-tool-call, not per-session, so the citizen that fires the egress tool and
the human who approves it (possibly in a different thread) match on the
approval id alone.

Mirrors the connection style and conventions of the sibling
``soveryn/agents/presence/staged_store.py``: WAL journal mode, an explicit
``timeout_seconds`` on every connection, an idempotent schema bootstrap in
``__init__``, and — critically — **no wall-clock calls inside the module**.
``create`` and ``expire_stale`` take ``now`` as an explicit ISO-timestamp
argument so callers (and tests) stay deterministic.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0

STATE_PENDING = "pending"
STATE_APPROVED = "approved"
STATE_DENIED = "denied"
STATE_EXPIRED = "expired"
_TERMINAL_STATES = (STATE_APPROVED, STATE_DENIED, STATE_EXPIRED)


@dataclass(frozen=True)
class ApprovalRequest:
    """A single egress-tool call held at the Approval Gate.

    Attributes:
        id: Deterministic id derived from citizen + tool + now + args.
        citizen: The citizen (agent) that fired the egress tool (e.g. "aetheria").
        tool: The egress tool name (e.g. "email_send", "web_search", "x_post").
        args: The tool arguments as a dict (stored as a JSON string in SQLite).
        requested_at: ISO timestamp when the request was created.
        state: One of "pending", "approved", "denied", "expired".
        decided_at: ISO timestamp when a terminal state was reached, or None.
        decided_by: Who decided ("jon", "timeout", ...), or None while pending.
    """

    id: str
    citizen: str
    tool: str
    args: dict[str, Any]
    requested_at: str
    state: str
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None


def _make_id(citizen: str, tool: str, now: str, args: dict[str, Any]) -> str:
    """Deterministic id derived from citizen + tool + now + args (never random)."""
    arg_blob = json.dumps(args, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{citizen}|{tool}|{now}|{arg_blob}".encode("utf-8")).hexdigest()
    return digest[:16]


class ApprovalStore:
    """SQLite-backed store for Approval Gate requests.

    Schema is bootstrapped idempotently in __init__.
    """

    def __init__(
        self,
        db_path: Path,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self._bootstrap_schema()

    def _bootstrap_schema(self) -> None:
        """Create schema tables if they don't exist (idempotent)."""
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_requests (
                    id TEXT PRIMARY KEY,
                    citizen TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    args TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_approval_pending
                ON approval_requests (state, requested_at)
                """
            )

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout_seconds)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _row_to_request(row: sqlite3.Row) -> ApprovalRequest:
        return ApprovalRequest(
            id=row["id"],
            citizen=row["citizen"],
            tool=row["tool"],
            args=json.loads(row["args"]) if row["args"] else {},
            requested_at=row["requested_at"],
            state=row["state"],
            decided_at=row["decided_at"],
            decided_by=row["decided_by"],
        )

    def create(
        self,
        *,
        citizen: str,
        tool: str,
        args: dict[str, Any],
        now: str,
    ) -> ApprovalRequest:
        """Create a new pending approval request for an egress tool call."""
        req = ApprovalRequest(
            id=_make_id(citizen, tool, now, args),
            citizen=citizen,
            tool=tool,
            args=args,
            requested_at=now,
            state=STATE_PENDING,
        )
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO approval_requests
                (id, citizen, tool, args, requested_at, state, decided_at, decided_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    req.id,
                    req.citizen,
                    req.tool,
                    json.dumps(req.args, sort_keys=True, default=str),
                    req.requested_at,
                    req.state,
                    req.decided_at,
                    req.decided_by,
                ),
            )
        return req

    def get(self, approval_id: str) -> Optional[ApprovalRequest]:
        """Return the approval request by id, or None."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id, citizen, tool, args, requested_at, state, decided_at, decided_by "
                "FROM approval_requests WHERE id = ?",
                (approval_id,),
            ).fetchone()
        return self._row_to_request(row) if row is not None else None

    def set_state(
        self,
        approval_id: str,
        *,
        state: str,
        now: str,
        decided_by: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """Move a request to a terminal state. Returns the updated request or None.

        Idempotent: setting an already-terminal request to the same terminal
        state is a no-op (returns the existing row). Setting a terminal request
        to a *different* state is a no-op too — once decided, it stays decided.
        """
        existing = self.get(approval_id)
        if existing is None:
            return None
        if existing.state in _TERMINAL_STATES:
            return existing
        if state not in _TERMINAL_STATES:
            return existing
        updated = ApprovalRequest(
            id=existing.id,
            citizen=existing.citizen,
            tool=existing.tool,
            args=existing.args,
            requested_at=existing.requested_at,
            state=state,
            decided_at=now,
            decided_by=decided_by,
        )
        with self._conn() as conn:
            conn.execute(
                "UPDATE approval_requests SET state = ?, decided_at = ?, decided_by = ? "
                "WHERE id = ?",
                (state, now, decided_by, approval_id),
            )
        return updated

    def pending_for(self, citizen: str) -> list[ApprovalRequest]:
        """All pending requests for a citizen, oldest first (for the decision surface)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, citizen, tool, args, requested_at, state, decided_at, decided_by "
                "FROM approval_requests WHERE citizen = ? AND state = 'pending' "
                "ORDER BY requested_at ASC",
                (citizen,),
            ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def pending_all(self) -> list[ApprovalRequest]:
        """All pending requests house-wide, oldest first (CC Needs-you / Gate strip)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, citizen, tool, args, requested_at, state, decided_at, decided_by "
                "FROM approval_requests WHERE state = 'pending' "
                "ORDER BY requested_at ASC"
            ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def expire_stale(self, now: str, ttl_seconds: float) -> list[ApprovalRequest]:
        """Flip any ``pending`` request older than ttl_seconds to ``expired``.

        Compares ``requested_at`` to ``now`` (both ISO timestamps). Returns the
        requests that were flipped so callers can note them. Fail-safe: an
        unanswered egress call never leaves the house.
        """
        now_dt = datetime.fromisoformat(now)
        expired: list[ApprovalRequest] = []
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, citizen, tool, args, requested_at, state, decided_at, decided_by "
                "FROM approval_requests WHERE state = 'pending'"
            ).fetchall()
            for row in rows:
                req_dt = datetime.fromisoformat(row["requested_at"])
                age = (now_dt - req_dt).total_seconds()
                if age > ttl_seconds:
                    conn.execute(
                        "UPDATE approval_requests SET state = 'expired', "
                        "decided_at = ?, decided_by = 'timeout' WHERE id = ?",
                        (now, row["id"]),
                    )
                    row = conn.execute(
                        "SELECT id, citizen, tool, args, requested_at, state, decided_at, decided_by "
                        "FROM approval_requests WHERE id = ?",
                        (row["id"],),
                    ).fetchone()
                    expired.append(self._row_to_request(row))
        return expired


class ApprovalBroker:
    """Blocks the agent loop until a human decides, or the request expires.

    Wraps an :class:`ApprovalStore`. The ``wait`` call runs inside the
    synchronous tool-dispatch path of the ``AgentLoop`` — the runtime is
    single-threaded per citizen commission, so sleeping here never deadlocks
    the batch worker. A decision arriving on another thread (the API route,
    the messenger bridge) is observed by polling the store; on timeout the
    request is flipped to ``expired`` and the gate denies the egress.
    """

    def __init__(
        self,
        store: ApprovalStore,
        *,
        ttl_seconds: float = 300.0,
        poll_interval_seconds: float = 0.5,
    ) -> None:
        self.store = store
        self.ttl_seconds = ttl_seconds
        self.poll_interval_seconds = poll_interval_seconds

    def request(
        self,
        *,
        citizen: str,
        tool: str,
        args: dict[str, Any],
        now: str,
    ) -> ApprovalRequest:
        """Create and return a pending approval request."""
        return self.store.create(citizen=citizen, tool=tool, args=args, now=now)

    def wait(self, approval_id: str) -> ApprovalRequest:
        """Block until the request reaches a terminal state.

        Returns the terminal request. If it times out first, flips it to
        ``expired`` and returns that — the caller treats anything that is not
        ``approved`` as a denial (fail-safe: no egress without a yes).
        """
        deadline = time.monotonic() + self.ttl_seconds
        while True:
            req = self.store.get(approval_id)
            if req is None:
                # vanished (e.g. store reset) — treat as denial, not egress
                return ApprovalRequest(
                    id=approval_id,
                    citizen="",
                    tool="",
                    args={},
                    requested_at="",
                    state=STATE_DENIED,
                    decided_by="missing",
                )
            if req.state in _TERMINAL_STATES:
                return req
            if time.monotonic() >= deadline:
                from datetime import datetime as _dt

                expired = self.store.set_state(
                    approval_id,
                    state=STATE_EXPIRED,
                    now=_dt.now().isoformat(),
                    decided_by="timeout",
                )
                return expired or req
            time.sleep(self.poll_interval_seconds)

    def decide(
        self,
        approval_id: str,
        *,
        approve: bool,
        decided_by: str,
        now: str,
    ) -> Optional[ApprovalRequest]:
        """Apply a human decision. Returns the updated request, or None if unknown."""
        state = STATE_APPROVED if approve else STATE_DENIED
        return self.store.set_state(
            approval_id, state=state, now=now, decided_by=decided_by
        )
