"""Tool factories for the four coordination board operations.

These are shared across agents. Per-agent registration determines who can do
what — read is granted to all three; create/update_status/archive go to
Aetheria and Scotty per the locked spec. Vett posts Signal nodes via create
(her primary write surface for unverified leads).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

from soveryn.platform.coordination.events import CoordEvent, CoordEventKind
from soveryn.platform.coordination.store import CoordinationStore
from soveryn.platform.coordination.types import (
    CoordBoard,
    CoordStatus,
    CoordinationError,
    CoordinationNode,
)
from soveryn.platform.tools.registry import ToolArgError, ToolSpec


# ─── Rendering helpers ──────────────────────────────────────────────────────

def _node_to_dict(node: CoordinationNode) -> dict:
    return {
        "id": node.id,
        "board": node.board.value,
        "status": node.status.value,
        "owner": node.owner,
        "content": node.content,
        "lattice_ref": node.lattice_ref,
        "archived_lesson_id": node.archived_lesson_id,
        "created_at": node.created_at,
        "updated_at": node.updated_at,
    }


# ─── Read tool: list coordination nodes ─────────────────────────────────────

def build_read_coord_nodes_tool(
    *,
    store: CoordinationStore,
    owner_agent: str,
) -> ToolSpec:
    """Read tool. Granted to all three agents. The reading agent is recorded
    in coord_references for Phase-2 weight back-computation."""

    def handler(args: Mapping[str, Any]) -> Any:
        board_arg = args.get("board")
        status_arg = args.get("status")
        include_archived = bool(args.get("include_archived", False))
        try:
            board = CoordBoard(board_arg) if board_arg else None
        except ValueError:
            raise ToolArgError(
                f"invalid board {board_arg!r}; must be one of "
                f"{[b.value for b in CoordBoard]}"
            )
        try:
            status = CoordStatus(status_arg) if status_arg else None
        except ValueError:
            raise ToolArgError(
                f"invalid status {status_arg!r}; must be one of "
                f"{[s.value for s in CoordStatus]}"
            )
        nodes = store.list_nodes(
            board=board,
            status=status,
            include_archived=include_archived,
            reading_agent=owner_agent,
        )
        # Phase B: enrich Blueprint nodes with blocked_by — list of non-Archived
        # Friction node ids that have this Blueprint in their provenance.blocks.
        # Surfaces the block state to agents reading the boards so they don't
        # try to Ready a node and get a CoordinationError.
        rendered = []
        for n in nodes:
            d = _node_to_dict(n)
            if n.board == CoordBoard.BLUEPRINT:
                blockers = store.blueprint_blockers(n.id)
                d["blocked_by"] = [b.id for b in blockers]
            rendered.append(d)
        return {"nodes": rendered, "count": len(rendered)}

    return ToolSpec(
        name="read_coordination_nodes",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "enum": [b.value for b in CoordBoard],
                    "description": "Filter to one board. Omit for all boards.",
                },
                "status": {
                    "type": "string",
                    "enum": [s.value for s in CoordStatus],
                    "description": "Filter to one status. Omit for all non-archived.",
                },
                "include_archived": {
                    "type": "boolean",
                    "description": "By default Archived nodes are excluded from board view. "
                                   "Set true for audit reads.",
                },
            },
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "List Coordination Board nodes filtered by board (Signal | Blueprint | "
            "Friction) and/or status (Open | Refining | Ready | Archived). "
            "Archived nodes are hidden from board view unless include_archived=true."
        ),
    )


# ─── Create tool: post a coord node ─────────────────────────────────────────

def build_create_coord_node_tool(
    *,
    store: CoordinationStore,
    owner_agent: str,
) -> ToolSpec:
    """Create a Coordination Board node in the Open state. Vett uses this for
    Signal posts; Aetheria for refined Blueprint or Friction; Scotty for
    execution Blueprints he's spec'd."""

    def handler(args: Mapping[str, Any]) -> Any:
        board_arg = args.get("board")
        try:
            board = CoordBoard(board_arg)
        except ValueError:
            raise ToolArgError(
                f"invalid board {board_arg!r}; must be one of "
                f"{[b.value for b in CoordBoard]}"
            )
        content = args.get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise ToolArgError("content must be a non-empty string")
        lattice_ref = args.get("lattice_ref")
        if lattice_ref is not None and not isinstance(lattice_ref, str):
            raise ToolArgError("lattice_ref must be a string or omitted")
        try:
            node = store.create_node(
                board=board,
                owner=owner_agent,
                content=content,
                lattice_ref=lattice_ref or None,
            )
        except CoordinationError as e:
            raise ToolArgError(str(e))
        return {"created": _node_to_dict(node)}

    return ToolSpec(
        name="create_coordination_node",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "board": {
                    "type": "string",
                    "enum": [b.value for b in CoordBoard],
                    "description": "Which board this node lives on.",
                },
                "content": {
                    "type": "string",
                    "description": "The lead, plan, or contradiction. Must be non-empty.",
                },
                "lattice_ref": {
                    "type": "string",
                    "description": "Optional: lattice node id this coord node references "
                                   "(e.g. the memory thesis being refined into a Blueprint).",
                },
            },
            "required": ["board", "content"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Post a new Coordination Board node. Starts in Open status; you can "
            "transition it via update_coordination_status. Pass lattice_ref to "
            "link this coord node back to an existing lattice memory."
        ),
    )


# ─── Update status tool ─────────────────────────────────────────────────────

def build_update_coord_status_tool(
    *,
    store: CoordinationStore,
    owner_agent: str,
) -> ToolSpec:
    """Transition a coord node through the lifecycle. Archive is NOT done via
    this tool — that requires a Lesson Learned payload, so it has its own tool."""

    def handler(args: Mapping[str, Any]) -> Any:
        node_id = args.get("node_id", "")
        if not isinstance(node_id, str) or not node_id:
            raise ToolArgError("node_id must be a non-empty string")
        new_status_arg = args.get("new_status")
        try:
            new_status = CoordStatus(new_status_arg)
        except ValueError:
            raise ToolArgError(
                f"invalid new_status {new_status_arg!r}; must be one of "
                f"{[s.value for s in CoordStatus if s != CoordStatus.ARCHIVED]} "
                f"(use archive_coordination_node for Archived)"
            )
        if new_status == CoordStatus.ARCHIVED:
            raise ToolArgError(
                "use archive_coordination_node(node_id, lesson_learned_content) "
                "to archive; this tool transitions through Open/Refining/Ready only"
            )
        try:
            node = store.update_status(node_id, new_status, acting_agent=owner_agent)
        except CoordinationError as e:
            raise ToolArgError(str(e))
        return {"updated": _node_to_dict(node)}

    return ToolSpec(
        name="update_coordination_status",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "ID of the coord node to transition.",
                },
                "new_status": {
                    "type": "string",
                    "enum": [
                        CoordStatus.OPEN.value,
                        CoordStatus.REFINING.value,
                        CoordStatus.READY.value,
                    ],
                    "description": "Target status. Open->Refining->Ready only via this tool; "
                                   "Archived requires archive_coordination_node.",
                },
            },
            "required": ["node_id", "new_status"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Move a coordination node through the Open -> Refining -> Ready lifecycle. "
            "Invalid transitions (e.g. backwards or skipping states) are rejected. "
            "Archive has its own tool because it requires a Lesson Learned payload."
        ),
    )


# ─── Archive tool ───────────────────────────────────────────────────────────

def build_archive_coord_node_tool(
    *,
    store: CoordinationStore,
    owner_agent: str,
) -> ToolSpec:
    """Archive a coord node AND write the paired Lesson Learned lattice node.
    Spec rule: archive vanishes from board view, BUT the resolution becomes
    permanent recallable memory via the Lesson Learned link."""

    def handler(args: Mapping[str, Any]) -> Any:
        node_id = args.get("node_id", "")
        if not isinstance(node_id, str) or not node_id:
            raise ToolArgError("node_id must be a non-empty string")
        lesson = args.get("lesson_learned_content", "")
        if not isinstance(lesson, str) or not lesson.strip():
            raise ToolArgError(
                "lesson_learned_content must be a non-empty string — archiving "
                "without a lesson means losing the resolution"
            )
        try:
            node = store.archive_node(
                node_id,
                lesson_learned_content=lesson,
                acting_agent=owner_agent,
            )
        except CoordinationError as e:
            raise ToolArgError(str(e))
        return {
            "archived": _node_to_dict(node),
            "lesson_learned_id": node.archived_lesson_id,
        }

    return ToolSpec(
        name="archive_coordination_node",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "node_id": {
                    "type": "string",
                    "description": "ID of the coord node to archive.",
                },
                "lesson_learned_content": {
                    "type": "string",
                    "description": "The resolution captured as permanent memory. "
                                   "Required — archive without a lesson loses what was learned.",
                },
            },
            "required": ["node_id", "lesson_learned_content"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Archive a coordination node and write a Lesson Learned lattice "
            "memory in one operation. Coord node is marked Archived (hidden from "
            "board view) and the lesson becomes a recallable lattice node tagged "
            "with the originating coord node id."
        ),
    )


# ─── Promote tool ───────────────────────────────────────────────────────────

def build_promote_coord_node_tool(
    *,
    store: CoordinationStore,
    owner_agent: str,
) -> ToolSpec:
    """Promote a Signal (or any non-Archived coord node) into a Blueprint or
    Friction. One transaction: target created with lattice_ref=source, source
    archived with Lesson Learned describing the promotion. Collapses the
    canonical Signal -> Blueprint pipeline into a single call."""

    def handler(args: Mapping[str, Any]) -> Any:
        source_id = args.get("source_node_id", "")
        if not isinstance(source_id, str) or not source_id:
            raise ToolArgError("source_node_id must be a non-empty string")
        target_arg = args.get("target_board")
        try:
            target_board = CoordBoard(target_arg)
        except ValueError:
            raise ToolArgError(
                f"invalid target_board {target_arg!r}; must be one of "
                f"{[b.value for b in CoordBoard if b != CoordBoard.SIGNAL]} "
                f"(Signal cannot be a promote target)"
            )
        if target_board == CoordBoard.SIGNAL:
            raise ToolArgError(
                "target_board cannot be Signal — Signal is the source side of "
                "the promote pipeline, not a destination"
            )
        new_content = args.get("new_content", "")
        if not isinstance(new_content, str) or not new_content.strip():
            raise ToolArgError("new_content must be a non-empty string")
        lesson = args.get("lesson_learned_content")
        if lesson is not None and not isinstance(lesson, str):
            raise ToolArgError("lesson_learned_content must be a string or omitted")
        target_owner_arg = args.get("target_owner")
        if target_owner_arg is not None and not isinstance(target_owner_arg, str):
            raise ToolArgError("target_owner must be a string or omitted")
        # Canonicalize at the write-path so the persisted owner field is
        # always lowercase / no-dots. Aetheria's stylization ("V.E.T.T."
        # for Vett) collapsed dispatch silently before 2026-06-04; we now
        # normalize before storage so future Blueprints are clean from the
        # start, and the routing layer's own leniency catches anything
        # legacy that slipped through.
        from soveryn.platform.coordination.routing import normalize_agent_name
        normalized_target_owner = normalize_agent_name(target_owner_arg)
        try:
            source, target = store.promote_node(
                source_id,
                target_board=target_board,
                new_content=new_content,
                acting_agent=owner_agent,
                lesson_learned_content=lesson,
                target_owner=normalized_target_owner,
            )
        except CoordinationError as e:
            raise ToolArgError(str(e))
        return {
            "promoted_source": _node_to_dict(source),
            "created_target": _node_to_dict(target),
            "lesson_learned_id": source.archived_lesson_id,
        }

    return ToolSpec(
        name="promote_coordination_node",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "source_node_id": {
                    "type": "string",
                    "description": "ID of the source coord node (typically a Signal) to promote. "
                                   "Must not already be Archived.",
                },
                "target_board": {
                    "type": "string",
                    "enum": [CoordBoard.BLUEPRINT.value, CoordBoard.FRICTION.value],
                    "description": "Destination board. Signal is not a valid target.",
                },
                "new_content": {
                    "type": "string",
                    "description": "Content of the new Blueprint or Friction node — the *plan* or "
                                   "*contradiction*, not a copy of the source. Required.",
                },
                "lesson_learned_content": {
                    "type": "string",
                    "description": "Optional override of the auto-generated archive lesson. "
                                   "Default: 'Promoted to {target_board} {new_id}'.",
                },
                "target_owner": {
                    "type": "string",
                    "description": "Optional owner for the new Blueprint/Friction. Defaults "
                                   "to the agent doing the promote. Set this when you're "
                                   "assigning the work to a different agent (e.g. Aetheria "
                                   "promoting a Signal to a Blueprint that Vett or Scotty "
                                   "should pick up). The webhook router uses this to wake "
                                   "the owner.",
                },
            },
            "required": ["source_node_id", "target_board", "new_content"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Promote a coordination node from one board to another (typically Signal -> "
            "Blueprint). Atomic: the new target node is created on target_board with "
            "lattice_ref linking back to the source, and the source is archived with a "
            "Lesson Learned describing the promotion. Use this instead of separate "
            "create + archive calls when refining a Signal into an actionable Blueprint."
        ),
    )


# ─── Friction block tool (Phase B) ──────────────────────────────────────────

def build_add_friction_block_tool(
    *,
    store: CoordinationStore,
    owner_agent: str,
) -> ToolSpec:
    """Declare that a Friction node blocks a Blueprint from reaching Ready.

    Per Aetheria's spec: Friction acts as a structural blocker on linked
    Blueprint nodes until resolved. Archiving the Friction is the canonical
    unblock action — there's no separate remove_block tool by design (use the
    archive flow with a resolution lesson). Idempotent: re-adding the same
    block pair is a no-op.
    """

    def handler(args: Mapping[str, Any]) -> Any:
        friction_id = args.get("friction_node_id", "")
        blueprint_id = args.get("blueprint_node_id", "")
        if not isinstance(friction_id, str) or not friction_id:
            raise ToolArgError("friction_node_id must be a non-empty string")
        if not isinstance(blueprint_id, str) or not blueprint_id:
            raise ToolArgError("blueprint_node_id must be a non-empty string")
        try:
            friction = store.add_block(friction_id, blueprint_id, acting_agent=owner_agent)
        except CoordinationError as e:
            raise ToolArgError(str(e))
        return {
            "friction": _node_to_dict(friction),
            "blocks": list(store.get_blocks(friction_id)),
        }

    return ToolSpec(
        name="add_friction_block",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "friction_node_id": {
                    "type": "string",
                    "description": "ID of the Friction node declaring the block. "
                                   "Must be on Friction board, non-Archived.",
                },
                "blueprint_node_id": {
                    "type": "string",
                    "description": "ID of the Blueprint being blocked. Must be on "
                                   "Blueprint board.",
                },
            },
            "required": ["friction_node_id", "blueprint_node_id"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Declare that a Friction node blocks a Blueprint from reaching Ready "
            "status. The block holds until the Friction is Archived with a "
            "resolution lesson. Idempotent — re-adding the same pair is a no-op. "
            "Any agent can declare a block; resolution flows through Aetheria's "
            "arbitration role per the persona layer."
        ),
    )


# ─── Request direction tool (DAC Delta 2) ───────────────────────────────────

def build_request_direction_tool(
    *,
    store: CoordinationStore,
    event_bus,  # InMemoryEventBus (or any EventBus impl)
    owner_agent: str,
) -> ToolSpec:
    """Peer agent (Vett or Scotty) pings Aetheria for a judgment call on
    direction. Emits a NEEDS_DIRECTION CoordEvent — the webhook router
    auto-invokes Aetheria with the brief rendered into her prompt.

    Spec: docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md
    """

    def handler(args: Mapping[str, Any]) -> Any:
        node_id = args.get("node_id")
        context_summary = args.get("context_summary")
        options_considered = args.get("options_considered")

        if not isinstance(node_id, str) or not node_id.strip():
            raise ToolArgError("node_id must be a non-empty string")
        if not isinstance(context_summary, str) or not context_summary.strip():
            raise ToolArgError(
                "context_summary must be a non-empty string"
            )
        if (not isinstance(options_considered, list)
            or len(options_considered) == 0
            or not all(isinstance(o, str) for o in options_considered)):
            raise ToolArgError(
                "options_considered must be a non-empty list of strings — "
                "if you have no options, you have a panic, not a direction "
                "question. Spell out at least one path you've considered."
            )

        node = store.get_node(node_id.strip())
        if node is None:
            return {"error": "unknown_node", "node_id": node_id}

        event = CoordEvent(
            id=str(uuid.uuid4()),
            kind=CoordEventKind.NEEDS_DIRECTION,
            node_id=node_id.strip(),
            actor_agent=owner_agent,
            timestamp=datetime.now().isoformat(),
            payload={
                "context_summary": context_summary.strip(),
                "options_considered": list(options_considered),
                "requester_agent": owner_agent,
            },
        )
        event_bus.emit(event)
        return {
            "needs_direction_event_id": event.id,
            "node_id": node_id.strip(),
            "requester": owner_agent,
        }

    schema = {
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": (
                    "The Coord node this request is anchored to."
                ),
            },
            "context_summary": {
                "type": "string",
                "description": (
                    "Brief description of what you're stuck on. Aetheria "
                    "needs enough context to make a real call without "
                    "having to investigate from scratch."
                ),
            },
            "options_considered": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "The paths you've considered. At least one — if you "
                    "have no options, this isn't a direction request, "
                    "it's a panic."
                ),
            },
        },
        "required": ["node_id", "context_summary", "options_considered"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="request_direction",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Ping Aetheria for a judgment call on direction. Use this when "
            "you've hit a wall that needs a decision on what to do next — "
            "not a technical fix you can solve, but a strategic call. "
            "Lay out the brief and the options you've considered."
        ),
    )


# ─── Bulk registration ──────────────────────────────────────────────────────

def register_coord_tools(
    registry,
    *,
    coord_store: CoordinationStore,
    owner_agent: str,
    grant_write: bool = True,
) -> None:
    """Register the coord tools for one agent.

    grant_write=False registers only the read tool — useful when an agent
    needs visibility into the boards but isn't a write principal. Vett gets
    full grant_write=True because she's the Signal-poster; Aetheria gets full
    grant_write because she refines and arbitrates; Scotty gets full grant_write
    because he Blueprints execution.
    """
    registry.register(build_read_coord_nodes_tool(store=coord_store, owner_agent=owner_agent))
    if grant_write:
        registry.register(build_create_coord_node_tool(store=coord_store, owner_agent=owner_agent))
        registry.register(build_update_coord_status_tool(store=coord_store, owner_agent=owner_agent))
        registry.register(build_archive_coord_node_tool(store=coord_store, owner_agent=owner_agent))
        registry.register(build_promote_coord_node_tool(store=coord_store, owner_agent=owner_agent))
        registry.register(build_add_friction_block_tool(store=coord_store, owner_agent=owner_agent))
