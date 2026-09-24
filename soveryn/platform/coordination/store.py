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

from soveryn.platform.coordination.events import (
    CoordEvent,
    CoordEventKind,
    EventBus,
    NullEventBus,
    get_active_chain,
)
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
    """SQLite-backed coordination store. Path-injected; no module state.

    event_bus is optional — when None (the default), mutations don't emit
    CoordEvents. Callers that want webhook-driven triggering pass an
    InMemoryEventBus (typically via startup.py wiring).
    """

    def __init__(
        self,
        db_path: Path,
        timeout_seconds: float = DEFAULT_CONNECTION_TIMEOUT_SECONDS,
        *,
        event_bus: EventBus | None = None,
        embed_fn=None,
    ) -> None:
        self.db_path = Path(db_path)
        self.timeout_seconds = timeout_seconds
        self.event_bus: EventBus = event_bus or NullEventBus()
        # Optional embedder. When set (prod wires nomic-embed), coordination
        # nodes are embedded on write so they're recallable by every agent's
        # semantic recall. None in tests → nodes written unembedded (no HTTP).
        # Best-effort: an embed failure never blocks the write.
        self._embed_fn = embed_fn

    def _maybe_embed(self, text: str) -> str | None:
        """Embed `text` to a JSON vector string, or None (no embedder / empty /
        failure). Best-effort — coordination writes must never fail on embed."""
        return self._maybe_embed_pair(text)[0]

    def _maybe_embed_pair(self, text: str) -> tuple[str | None, bytes | None]:
        """As `_maybe_embed`, but also the float32 blob recall scores from.

        Writing only the JSON leaves the row on the slow decode path; writing
        only the blob makes it invisible to anything still reading the text
        column. Both, or neither.
        """
        if self._embed_fn is None or not text:
            return None, None
        try:
            vector = tuple(self._embed_fn(text[:8000]))
            from soveryn.platform.lattice.legacy import _encode_embedding_blob
            return json.dumps(list(vector)), _encode_embedding_blob(vector)
        except Exception:
            return None, None

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
        notify: bool = True,
    ) -> CoordinationNode:
        """Create a new Coordination Node in the Open state.

        notify=True (default) emits NODE_CREATED so the webhook router can
        route the item to its destination agent(s) — the agent-driven path.
        notify=False skips emission entirely: the node is persisted and
        visible on the board, but no event is logged and no agent is
        triggered. Used by Mission Control's human "park quietly" path so
        Jon can stage a spec without auto-dispatching anyone.
        """
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
        embedding_json = self._maybe_embed(content.strip())
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.3, 0.5, 0, NULL, ?, ?, ?, NULL, ?)",
                (node_id, COORDINATION_NODE_TYPE, owner, content.strip(),
                 now, now, embedding_json, json.dumps(provenance, sort_keys=True)),
            )
        # If this node references an existing lattice node, log that as the
        # initial cross-reference so the source<->target link enters the table
        # from creation time.
        if lattice_ref:
            self._log_references(owner, [lattice_ref], source_node_id=node_id)
        created = CoordinationNode(
            id=node_id, board=board, status=CoordStatus.OPEN, owner=owner,
            content=content.strip(), lattice_ref=lattice_ref,
            archived_lesson_id=None, created_at=now, updated_at=now,
        )
        if notify:
            self._emit(
                kind=CoordEventKind.NODE_CREATED,
                node_id=node_id,
                actor_agent=owner,
                payload={
                    "board": board.value,
                    "owner": owner,
                    "lattice_ref": lattice_ref,
                    "content_head": content.strip()[:200],
                },
            )
        return created

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
        self._emit(
            kind=CoordEventKind.STATUS_CHANGED,
            node_id=node_id,
            actor_agent=acting_agent,
            payload={
                "board": existing.board.value,
                "old_status": existing.status.value,
                "new_status": new_status.value,
            },
        )
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
        self._emit(
            kind=CoordEventKind.BLOCK_ADDED,
            node_id=friction_node_id,
            actor_agent=acting_agent,
            payload={"blocks_blueprint_id": blueprint_node_id},
        )
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
        target_owner: str | None = None,
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

        # If the promoter assigns a different owner (e.g. Aetheria promoting
        # a Signal to a Blueprint that Vett or Scotty should pick up),
        # honour it. Default keeps the prior behaviour where the actor owns
        # what they promote.
        effective_owner = (
            target_owner.strip() if isinstance(target_owner, str) and target_owner.strip()
            else acting_agent
        )
        target_provenance = {
            "board": target_board.value,
            "status": CoordStatus.OPEN.value,
            "owner": effective_owner,
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

        target_text = new_content.strip()
        target_json, target_blob = self._maybe_embed_pair(target_text)
        lesson_json, lesson_blob = self._maybe_embed_pair(effective_lesson)
        with self._conn() as conn:
            # 1. Create the target coord node on the destination board.
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, embedding_f32, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.3, 0.5, 0, NULL, ?, ?, ?, ?, NULL, ?)",
                (target_id, COORDINATION_NODE_TYPE, acting_agent,
                 target_text, now, now, target_json, target_blob,
                 json.dumps(target_provenance, sort_keys=True)),
            )
            # 2. Write the Lesson Learned lattice node tying source -> target.
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, embedding_f32, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.5, 0.7, 0, NULL, ?, ?, ?, ?, NULL, ?)",
                (lesson_id, LESSON_LEARNED_NODE_TYPE, acting_agent,
                 effective_lesson, now, now, lesson_json, lesson_blob,
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
        self._emit(
            kind=CoordEventKind.PROMOTED,
            node_id=target_id,
            actor_agent=acting_agent,
            payload={
                "source_node_id": source_node_id,
                "source_board": existing.board.value,
                "target_board": target_board.value,
                "target_owner": effective_owner,
                "lesson_id": lesson_id,
                "content_head": new_content.strip()[:200],
            },
        )
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
        lesson_text = lesson_learned_content.strip()
        embedding_json, embedding_blob = self._maybe_embed_pair(lesson_text)
        with self._conn() as conn:
            # 1. Write the Lesson Learned lattice node.
            conn.execute(
                "INSERT INTO nodes (id, type, layer, agent, content, "
                "intensity, salience, access_count, tags, created_at, "
                "updated_at, embedding, embedding_f32, intent, provenance) "
                "VALUES (?, ?, 'lattice', ?, ?, 0.5, 0.7, 0, NULL, ?, ?, ?, ?, NULL, ?)",
                (lesson_id, LESSON_LEARNED_NODE_TYPE, acting_agent,
                 lesson_text, now, now, embedding_json, embedding_blob,
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
        self._emit(
            kind=CoordEventKind.ARCHIVED,
            node_id=node_id,
            actor_agent=acting_agent,
            payload={
                "board": existing.board.value,
                "lesson_id": lesson_id,
                "lesson_content_head": lesson_learned_content.strip()[:200],
            },
        )
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

    # ─── Event emission (Phase E) ───────────────────────────────────────────

    def _emit(
        self,
        *,
        kind: CoordEventKind,
        node_id: str,
        actor_agent: str,
        payload: dict,
        bus=None,
    ) -> "CoordEvent":
        """Construct a CoordEvent + log it to coord_event_log + push to the
        event bus. Called after the relevant DB write has committed. Returns
        the constructed event so callers can surface its id.

        Chain depth + parent_event_id are pulled from the thread-local set
        by the dispatcher when an agent is running under a webhook
        invocation. Outside webhook context, chain_depth=0 and
        parent_event_id=None (user-triggered actions).

        `bus` overrides the store's own event bus for this emission — used by
        the request_direction tool, which carries its own bus handle but must
        still land in the coord_event_log ledger (its events were silently
        unlogged before 2026-06-19: it built an event and emitted to its bus
        directly, bypassing this method, so NEEDS_DIRECTION never appeared in
        the delivery ledger and a peer could never tell if it was received).
        """
        chain = get_active_chain()
        chain_depth = (chain.chain_depth + 1) if chain else 0
        parent_id = chain.parent_event_id if chain else None
        event = CoordEvent.new(
            kind=kind, node_id=node_id, actor_agent=actor_agent, payload=payload,
            chain_depth=chain_depth, parent_event_id=parent_id,
        )
        # Persist to the audit log first so even bus failures don't lose the event.
        try:
            with self._conn() as conn:
                conn.execute(
                    "INSERT INTO coord_event_log "
                    "(id, kind, node_id, actor_agent, chain_depth, parent_event_id, "
                    "payload_json, triggered_agents, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                    (event.id, event.kind.value, event.node_id, event.actor_agent,
                     event.chain_depth, event.parent_event_id,
                     json.dumps(event.payload, sort_keys=True), event.timestamp),
                )
        except Exception:
            # Audit failure shouldn't fail the mutation. The state change
            # already committed; just log and continue.
            import logging
            logging.getLogger(__name__).warning(
                "failed to log coord event %s for node %s", event.id, node_id,
                exc_info=True,
            )
        # Bus emission is best-effort.
        target_bus = bus if bus is not None else self.event_bus
        try:
            target_bus.emit(event)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "event bus failed to accept event %s", event.id, exc_info=True,
            )
        return event

    def delivery_states_for_actor(self, actor: str) -> dict[str, str]:
        """Map node_id → a short delivery-state label for events THIS actor
        emitted, read off coord_event_log. The perspective-mirror of the
        sender-side dispatch states: it answers "did my message to the hub
        actually get there?" — the truth a peer otherwise can't see.

        State comes from `triggered_agents`, which the coord worker fills in
        after routing: NULL/empty = sent but not yet delivered; a plain agent
        list = received by them; an `=ERROR:` marker = delivery failed. Newest
        event per node wins.
        """
        states: dict[str, str] = {}
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT node_id, triggered_agents FROM coord_event_log "
                "WHERE actor_agent = ? ORDER BY created_at DESC",
                (actor,),
            ).fetchall()
        for row in rows:
            node_id = row["node_id"]
            if node_id in states:
                continue  # newest already recorded
            states[node_id] = _delivery_label(row["triggered_agents"])
        return states


# ─── Delivery-state labelling ───────────────────────────────────────────────

def _delivery_label(triggered_agents: str | None) -> str:
    """Turn a coord_event_log `triggered_agents` value into a short label.

    NULL/empty   → the worker hasn't routed/delivered it yet.
    `=ERROR:`    → routing reached the agent but the invocation failed.
    plain list   → received by those agents.
    """
    raw = (triggered_agents or "").strip()
    if not raw:
        return "sent, not yet received"
    if "ERROR" in raw:
        # e.g. "scotty=ERROR:AgentLoopError" — name the agent, drop the trace.
        who = raw.split("=", 1)[0].strip() or "peer"
        return f"sent to {who}, delivery failed"
    # e.g. "aetheria" or "aetheria,scotty"
    who = ", ".join(part.split("=", 1)[0].strip() for part in raw.split(",") if part.strip())
    return f"sent to {who}, received"


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
        # cls + source are both required by _provenance_from_payload; without
        # them the entry parses to None and is unassertable regardless of how
        # specific the rest of this payload is. The agent moved this node on a
        # board — that is a witnessed act, and the board is the citation.
        "cls": "witnessed",
        "source": f"coordination:{node.board.value}",
        "board": node.board.value,
        "status": node.status.value,
        "owner": node.owner,
        "lattice_ref": node.lattice_ref,
        "archived_lesson_id": node.archived_lesson_id,
    }
