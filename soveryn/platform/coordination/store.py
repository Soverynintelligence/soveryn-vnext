"""CoordinationStore — CRUD + state machine + cross-reference instrumentation.

Composes over LatticeStore. Coordination Nodes live in the existing nodes
table with type='coordination'; board/status/lattice_ref/owner live in the
provenance JSON column. Archive writes a paired Lesson Learned node
(type='lesson_learned') back into the same store so the resolution becomes
recallable memory.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from soveryn.platform.coordination.types import (
    COORDINATION_NODE_TYPE,
    LESSON_LEARNED_NODE_TYPE,
    CoordBoard,
    CoordStatus,
    CoordinationError,
    CoordinationNode,
    VALID_TRANSITIONS,
)


DEFAULT_CONNECTION_TIMEOUT_SECONDS = 30.0


class CoordinationStore:
    """SQLite-backed coordination store. Path-injected; no module state."""

    def __init__(self, db_path: Path, timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
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

    # ─── Read ───────────────────────────────────────────────────────────────

    def list_nodes(
        self,
        *,
        board: CoordBoard | None = None,
        status: CoordStatus | None = None,
        include_archived: bool = False,
        reading_agent: str | None = None,
    ) -> tuple[CoordinationNode, ...]:
        """Return Coordination Nodes filtered by board/status. Excludes Archived
        from "board view" by default — matches the spec ("Archive vanishes from
        the board"). Pass include_archived=True for audit/admin reads.

        If reading_agent is set, every returned node is logged to
        coord_references so cross-reference instrumentation captures the read.
        Phase-2 weight back-computation reads from that table.
        """
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE type = ? ORDER BY created_at ASC",
                (COORDINATION_NODE_TYPE,),
            ).fetchall()

        results: list[CoordinationNode] = []
        for r in rows:
            node = _row_to_coord_node(r)
            if board is not None and node.board != board:
                continue
            if status is not None and node.status != status:
                continue
            if not include_archived and node.status == CoordStatus.ARCHIVED:
                continue
            results.append(node)

        if reading_agent:
            self._log_references(reading_agent, [n.id for n in results])

        return tuple(results)

    def get_node(self, node_id: str, *, reading_agent: str | None = None) -> CoordinationNode | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE id = ? AND type = ?",
                (node_id, COORDINATION_NODE_TYPE),
            ).fetchone()
        if row is None:
            return None
        node = _row_to_coord_node(row)
        if reading_agent:
            self._log_references(reading_agent, [node.id])
        return node

    # ─── Write ──────────────────────────────────────────────────────────────

    def create_node(
        self,
        *,
        board: CoordBoard,
        owner: str,
        content: str,
        lattice_ref: str | None = None,
    ) -> CoordinationNode:
        """Create a new Coordination Node in the Open state."""
        if not content or not content.strip():
            raise CoordinationError("content must be non-empty")
        node_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        provenance = {
            "board": board.value,
            "status": CoordStatus.OPEN.value,
            "owner": owner,
            "lattice_ref": lattice_ref,
            "archived_lesson_id": None,
        }
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.3, 0.5, 0, NULL, ?, ?, NULL, NULL, ?)",
                (node_id, COORDINATION_NODE_TYPE, owner, content.strip(),
                 now, now, json.dumps(provenance, sort_keys=True)),
            )
        # If this node references an existing lattice node, log that as the
        # initial cross-reference so the source<->target link enters the table
        # from creation time.
        if lattice_ref:
            self._log_references(owner, [lattice_ref], source_node_id=node_id)
        return CoordinationNode(
            id=node_id, board=board, status=CoordStatus.OPEN, owner=owner,
            content=content.strip(), lattice_ref=lattice_ref,
            archived_lesson_id=None, created_at=now, updated_at=now,
        )

    def update_status(
        self,
        node_id: str,
        new_status: CoordStatus,
        *,
        acting_agent: str,
    ) -> CoordinationNode:
        """Transition a node's status. Validates against VALID_TRANSITIONS."""
        existing = self.get_node(node_id)
        if existing is None:
            raise CoordinationError(f"coord node {node_id!r} not found")
        allowed = VALID_TRANSITIONS[existing.status]
        if new_status not in allowed:
            raise CoordinationError(
                f"invalid transition {existing.status.value} -> {new_status.value} "
                f"(allowed: {sorted(s.value for s in allowed) or 'none — terminal state'})"
            )
        if new_status == CoordStatus.ARCHIVED:
            raise CoordinationError(
                "use archive_node(...) to transition into Archived; it requires "
                "a lesson_learned payload"
            )
        # Phase B (Friction-as-blocker): Blueprint -> Ready transition refused
        # while any non-Archived Friction node lists this blueprint in its
        # provenance.blocks list. Archived Frictions don't block — archiving
        # a Friction is the canonical resolution-unblock action.
        if (existing.board == CoordBoard.BLUEPRINT
                and new_status == CoordStatus.READY):
            blockers = self.blueprint_blockers(node_id)
            if blockers:
                raise CoordinationError(
                    f"blueprint {node_id!r} cannot move to Ready while blocked "
                    f"by {len(blockers)} unresolved Friction node(s): "
                    f"{[b.id for b in blockers]}. Archive the Friction(s) to unblock."
                )
        now = datetime.now().isoformat()
        provenance = _provenance_for(existing)
        provenance["status"] = new_status.value
        with self._conn() as conn:
            conn.execute(
                "UPDATE nodes SET provenance = ?, updated_at = ?, agent = agent "
                "WHERE id = ? AND type = ?",
                (json.dumps(provenance, sort_keys=True), now, node_id, COORDINATION_NODE_TYPE),
            )
        # Log the cross-reference: the acting agent touched this node.
        self._log_references(acting_agent, [node_id])
        return self.get_node(node_id)  # re-read for the canonical row

    # ─── Phase B: Friction-as-blocker ───────────────────────────────────────

    def add_block(
        self,
        friction_node_id: str,
        blueprint_node_id: str,
        *,
        acting_agent: str,
    ) -> CoordinationNode:
        """Declare that a Friction node blocks a Blueprint node from reaching
        Ready. Mutation lives in the Friction's provenance.blocks list.

        Idempotent: re-adding the same (friction, blueprint) pair is a no-op,
        not an error. The persona/relational layer decides when to remove
        blocks (typically by archiving the Friction with a resolution lesson).
        """
        friction = self.get_node(friction_node_id)
        if friction is None:
            raise CoordinationError(f"friction node {friction_node_id!r} not found")
        if friction.board != CoordBoard.FRICTION:
            raise CoordinationError(
                f"node {friction_node_id!r} is on board {friction.board.value}, "
                f"not Friction — only Friction nodes can block"
            )
        if friction.status == CoordStatus.ARCHIVED:
            raise CoordinationError(
                f"friction node {friction_node_id!r} is Archived — archived "
                f"Frictions cannot block (archive is the unblock action)"
            )
        blueprint = self.get_node(blueprint_node_id)
        if blueprint is None:
            raise CoordinationError(f"blueprint node {blueprint_node_id!r} not found")
        if blueprint.board != CoordBoard.BLUEPRINT:
            raise CoordinationError(
                f"node {blueprint_node_id!r} is on board {blueprint.board.value}, "
                f"not Blueprint — only Blueprint nodes can be blocked"
            )
        # Idempotent merge.
        with self._conn() as conn:
            row = conn.execute(
                "SELECT provenance FROM nodes WHERE id = ? AND type = ?",
                (friction_node_id, COORDINATION_NODE_TYPE),
            ).fetchone()
            provenance = json.loads(row["provenance"] or "{}")
            current_blocks = list(provenance.get("blocks") or [])
            if blueprint_node_id not in current_blocks:
                current_blocks.append(blueprint_node_id)
                provenance["blocks"] = current_blocks
                now = datetime.now().isoformat()
                conn.execute(
                    "UPDATE nodes SET provenance = ?, updated_at = ? "
                    "WHERE id = ? AND type = ?",
                    (json.dumps(provenance, sort_keys=True), now,
                     friction_node_id, COORDINATION_NODE_TYPE),
                )
        # Cross-reference: log the block declaration so reference_count reflects it.
        self._log_references(acting_agent, [blueprint_node_id],
                             source_node_id=friction_node_id)
        return self.get_node(friction_node_id)

    def blueprint_blockers(self, blueprint_node_id: str) -> tuple[CoordinationNode, ...]:
        """Return non-Archived Friction nodes whose provenance.blocks list
        contains this Blueprint's id. Used by update_status to refuse the
        Refining -> Ready transition and by list_nodes to enrich rows with
        a blocked_by field."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE type = ?",
                (COORDINATION_NODE_TYPE,),
            ).fetchall()
        results: list[CoordinationNode] = []
        for r in rows:
            provenance = json.loads(r["provenance"] or "{}")
            if provenance.get("board") != CoordBoard.FRICTION.value:
                continue
            if provenance.get("status") == CoordStatus.ARCHIVED.value:
                continue
            blocks_list = provenance.get("blocks") or []
            if blueprint_node_id in blocks_list:
                results.append(_row_to_coord_node(r))
        return tuple(results)

    def get_blocks(self, friction_node_id: str) -> tuple[str, ...]:
        """Return the list of Blueprint IDs blocked by this Friction node.
        Read accessor for tests + UI enrichment."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT provenance FROM nodes WHERE id = ? AND type = ?",
                (friction_node_id, COORDINATION_NODE_TYPE),
            ).fetchone()
        if row is None:
            return ()
        provenance = json.loads(row["provenance"] or "{}")
        return tuple(provenance.get("blocks") or [])

    def promote_node(
        self,
        source_node_id: str,
        *,
        target_board: CoordBoard,
        new_content: str,
        acting_agent: str,
        lesson_learned_content: str | None = None,
    ) -> tuple[CoordinationNode, CoordinationNode]:
        """Atomic promote: archive source + create target Blueprint/Friction in
        one transaction. The target carries lattice_ref=source_id so the link
        is preserved.

        Source must exist and not already be Archived. target_board must be
        Blueprint or Friction (promoting INTO Signal makes no semantic sense
        and is rejected at the tool layer; rejected here too as a safety net).
        new_content is the target's content (the *plan* or *contradiction*),
        not a copy of the source's content. lesson_learned_content overrides
        the auto-generated "Promoted to {target_board} {new_id}" message.

        Returns (source_now_archived, target_just_created).
        """
        if target_board == CoordBoard.SIGNAL:
            raise CoordinationError(
                "promote target cannot be Signal — Signal is the source side of the "
                "promote pipeline, not a destination"
            )
        if not new_content or not new_content.strip():
            raise CoordinationError("new_content must be non-empty")
        existing = self.get_node(source_node_id)
        if existing is None:
            raise CoordinationError(f"source coord node {source_node_id!r} not found")
        if existing.status == CoordStatus.ARCHIVED:
            raise CoordinationError(
                f"source coord node {source_node_id!r} is already Archived"
            )

        target_id = str(uuid.uuid4())
        lesson_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        effective_lesson = (
            lesson_learned_content.strip()
            if lesson_learned_content and lesson_learned_content.strip()
            else f"Promoted to {target_board.value} {target_id}"
        )

        target_provenance = {
            "board": target_board.value,
            "status": CoordStatus.OPEN.value,
            "owner": acting_agent,
            "lattice_ref": source_node_id,
            "archived_lesson_id": None,
        }
        lesson_provenance = {
            "source": "coordination_promote",
            "archived_coord_node_id": source_node_id,
            "promoted_to_coord_node_id": target_id,
            "promoted_to_board": target_board.value,
            "archived_by": acting_agent,
            "from_board": existing.board.value,
        }
        source_archived_provenance = _provenance_for(existing)
        source_archived_provenance["status"] = CoordStatus.ARCHIVED.value
        source_archived_provenance["archived_lesson_id"] = lesson_id

        with self._conn() as conn:
            # 1. Create the target coord node on the destination board.
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.3, 0.5, 0, NULL, ?, ?, NULL, NULL, ?)",
                (target_id, COORDINATION_NODE_TYPE, acting_agent,
                 new_content.strip(), now, now,
                 json.dumps(target_provenance, sort_keys=True)),
            )
            # 2. Write the Lesson Learned lattice node tying source -> target.
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.5, 0.7, 0, NULL, ?, ?, NULL, NULL, ?)",
                (lesson_id, LESSON_LEARNED_NODE_TYPE, acting_agent,
                 effective_lesson, now, now,
                 json.dumps(lesson_provenance, sort_keys=True)),
            )
            # 3. Archive the source coord node and link the lesson.
            conn.execute(
                "UPDATE nodes SET provenance = ?, updated_at = ? WHERE id = ? AND type = ?",
                (json.dumps(source_archived_provenance, sort_keys=True), now,
                 source_node_id, COORDINATION_NODE_TYPE),
            )
        # Cross-reference: source -> target (the promotion link). The
        # source -> lesson link gets logged separately so reference_count for
        # each endpoint reflects the actual touchpoints honestly.
        self._log_references(acting_agent, [target_id], source_node_id=source_node_id)
        self._log_references(acting_agent, [lesson_id], source_node_id=source_node_id)
        return (self.get_node(source_node_id), self.get_node(target_id))

    def archive_node(
        self,
        node_id: str,
        *,
        lesson_learned_content: str,
        acting_agent: str,
    ) -> CoordinationNode:
        """Archive a coord node AND write a paired Lesson Learned lattice node.

        Per spec: Archive != Delete. The coord node is marked Archived (vanishes
        from board view but stays in the table for audit). A Lesson Learned
        node is written into the lattice (type='lesson_learned') so the
        resolution becomes recallable memory. The two are cross-referenced
        through archived_lesson_id (coord -> lesson) and provenance
        (lesson -> coord).
        """
        if not lesson_learned_content or not lesson_learned_content.strip():
            raise CoordinationError("lesson_learned_content must be non-empty")
        existing = self.get_node(node_id)
        if existing is None:
            raise CoordinationError(f"coord node {node_id!r} not found")
        if existing.status == CoordStatus.ARCHIVED:
            raise CoordinationError(f"coord node {node_id!r} is already Archived")
        lesson_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        lesson_provenance = {
            "source": "coordination_archive",
            "archived_coord_node_id": node_id,
            "archived_by": acting_agent,
            "from_board": existing.board.value,
        }
        coord_provenance = _provenance_for(existing)
        coord_provenance["status"] = CoordStatus.ARCHIVED.value
        coord_provenance["archived_lesson_id"] = lesson_id
        with self._conn() as conn:
            # 1. Write the Lesson Learned lattice node.
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.5, 0.7, 0, NULL, ?, ?, NULL, NULL, ?)",
                (lesson_id, LESSON_LEARNED_NODE_TYPE, acting_agent,
                 lesson_learned_content.strip(), now, now,
                 json.dumps(lesson_provenance, sort_keys=True)),
            )
            # 2. Mark the coord node Archived and link the lesson.
            conn.execute(
                "UPDATE nodes SET provenance = ?, updated_at = ? WHERE id = ? AND type = ?",
                (json.dumps(coord_provenance, sort_keys=True), now, node_id,
                 COORDINATION_NODE_TYPE),
            )
        # Cross-reference: archive ties coord node to lesson node.
        self._log_references(acting_agent, [lesson_id], source_node_id=node_id)
        return self.get_node(node_id)

    # ─── Cross-reference instrumentation ────────────────────────────────────

    def _log_references(
        self,
        source_agent: str,
        referenced_node_ids: list[str],
        *,
        source_node_id: str | None = None,
    ) -> None:
        """Record cross-references in the coord_references table.

        Phase-1 substrate: capture every read/write as a separate row so
        Phase-2 can back-compute weight from the observed reference pattern.
        source_node_id is the coord node being acted on (None for plain reads,
        set when one coord node references another via lattice_ref or archive).
        """
        if not referenced_node_ids:
            return
        now = datetime.now().isoformat()
        with self._conn() as conn:
            for ref_id in referenced_node_ids:
                conn.execute(
                    "INSERT INTO coord_references "
                    "(id, source_node_id, referenced_node_id, source_agent, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), source_node_id or ref_id, ref_id, source_agent, now),
                )

    def reference_count(self, node_id: str) -> int:
        """Count how many times this node has been referenced — the raw signal
        Phase-2 weight scoring will back-compute on."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM coord_references WHERE referenced_node_id = ?",
                (node_id,),
            ).fetchone()
        return int(row[0])


# ─── Row mapping helpers ────────────────────────────────────────────────────

def _row_to_coord_node(row: sqlite3.Row) -> CoordinationNode:
    provenance = json.loads(row["provenance"] or "{}")
    return CoordinationNode(
        id=row["id"],
        board=CoordBoard(provenance.get("board", CoordBoard.SIGNAL.value)),
        status=CoordStatus(provenance.get("status", CoordStatus.OPEN.value)),
        owner=provenance.get("owner", row["agent"]),
        content=row["content"],
        lattice_ref=provenance.get("lattice_ref"),
        archived_lesson_id=provenance.get("archived_lesson_id"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _provenance_for(node: CoordinationNode) -> dict:
    return {
        "board": node.board.value,
        "status": node.status.value,
        "owner": node.owner,
        "lattice_ref": node.lattice_ref,
        "archived_lesson_id": node.archived_lesson_id,
    }
