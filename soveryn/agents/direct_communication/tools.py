"""direct_message_agent tool — Aetheria's direct rail to peer agents.

Push (mode=execute) and pull (mode=query) flow through the same primitive:
a POST to the target's /chat endpoint with a framing prefix that the
target's persona reads as either a directive or an information request.

Loop-chatter defenses in layered order:
  1. Schema — coord_node_id is REQUIRED at the tool registry level
  2. Forensic — every successful call writes a lattice edge
  3. Rate — DirectCommRateLimiter caps per-(sender, target) pair

See docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Callable

from soveryn.agents.direct_communication.rate_limit import DirectCommRateLimiter
from soveryn.platform.tools.registry import ToolArgError, ToolSpec
from soveryn.rooms.store import PEERS as _VALID_TARGETS


logger = logging.getLogger(__name__)

_VALID_MODES = frozenset({"execute", "query"})

_DIRECTIVE_PREFIX = (
    "[DIRECTIVE FROM AETHERIA, anchored at coord:{cid}]\n"
    "Act on this instruction now and report back to me with the result.\n\n"
)
_QUERY_PREFIX = (
    "[QUERY FROM AETHERIA, anchored at coord:{cid}]\n"
    "Give me raw observations — your current internal state on this. "
    "Skip the polished summary; I want the unprocessed read.\n\n"
)


def _commission_peer_for_dm(
    *,
    owner_agent: str,
    target: str,
    brief: str,
    coord_node_id: str,
) -> dict[str, Any]:
    """Enqueue peer work + room chip; return immediately (no nested /chat)."""
    try:
        import os
        from datetime import datetime, timezone
        from pathlib import Path

        from soveryn.citizens import post as house_post
        from soveryn.citizens.registry import connect
        from soveryn.rooms import context as room_ctx
        from soveryn.rooms.store import record_house_post_collab

        when = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        db = Path(
            os.environ.get("SOVERYN_CITIZENS_DB")
            or (Path.home() / "soveryn_vnext" / "data" / "citizens.db")
        )
        dm = None
        root = None
        try:
            from soveryn.rooms import context as room_ctx

            dm = room_ctx.dm_session_id.get()
            root = room_ctx.data_root.get()
        except Exception:
            dm = None
            root = None
        if dm and root:
            from soveryn.rooms.store import find_open_collab

            open_ev = find_open_collab(
                root, dm_session_id=dm, peer=target, citizens_db=db
            )
            if open_ev and open_ev.get("commission_id"):
                return {
                    "ok": True,
                    "commission_id": open_ev["commission_id"],
                    "reused": True,
                    "room_event": open_ev,
                    "routing": {"commission_id": open_ev["commission_id"]},
                }
        body = (
            f"(coord:{coord_node_id})\n\n{brief.strip()}"
        )
        with connect(db) as conn:
            routing = house_post.route_via_cos(
                conn,
                from_id=owner_agent,
                assignee_id=target,
                body=body,
                at=when,
                subject=f"coord {coord_node_id[:8]}",
            )
        commission_id = routing.get("commission_id")
        room_sid = None
        try:
            if dm is None:
                dm = room_ctx.dm_session_id.get()
            room_sid = room_ctx.room_session_id.get()
            if root is None:
                root = room_ctx.data_root.get()
        except Exception:
            room_sid = None
        conv = None
        try:
            from flask import current_app

            conv = (current_app.extensions.get("soveryn") or {}).get("conv_store")
        except Exception:
            conv = None
        room_event = None
        if conv is not None and root:
            room_event = record_house_post_collab(
                conv,
                data_root=root,
                from_id=owner_agent,
                to_id=target,
                body=brief,
                dm_session_id=dm,
                room_session_id=room_sid,
                commission_id=commission_id,
            )
        return {
            "ok": True,
            "commission_id": commission_id,
            "room_event": room_event,
            "routing": routing,
        }
    except Exception as exc:
        logger.exception("async commission for DM failed %s → %s", owner_agent, target)
        return {"ok": False, "error": repr(exc)}


def _project_peer_looped_in(
    *,
    owner_agent: str,
    target: str,
    brief: str,
) -> dict[str, Any] | None:
    """Show peer bot-shape in Jon's DM + open group room (best-effort)."""
    try:
        from soveryn.rooms import context as room_ctx
        from soveryn.rooms.store import record_house_post_collab

        dm = room_ctx.dm_session_id.get()
        room_sid = room_ctx.room_session_id.get()
        root = room_ctx.data_root.get()
        conv = None
        try:
            from flask import current_app

            conv = (current_app.extensions.get("soveryn") or {}).get("conv_store")
        except Exception:
            conv = None
        # Nested /chat from this tool runs outside Aetheria's request stack;
        # fall back to app object on the poster path via room_ctx only.
        if conv is None or not root:
            return None
        return record_house_post_collab(
            conv,
            data_root=root,
            from_id=owner_agent,
            to_id=target,
            body=brief,
            dm_session_id=dm,
            room_session_id=room_sid,
        )
    except Exception:
        logger.exception("room loop-in projection failed for %s → %s", owner_agent, target)
        return None


def _project_peer_reply(
    *,
    target: str,
    reply_text: str,
    room_session_id: str | None,
    dm_session_id: str | None,
) -> dict[str, Any] | None:
    """Land peer reply in the group room + DM replied chip (best-effort)."""
    try:
        from soveryn.citizens.post import CHIEF_OF_STAFF_ID
        from soveryn.rooms import context as room_ctx
        from soveryn.rooms.store import record_house_post_collab

        root = room_ctx.data_root.get()
        conv = None
        try:
            from flask import current_app

            conv = (current_app.extensions.get("soveryn") or {}).get("conv_store")
        except Exception:
            conv = None
        if conv is None or not root:
            return None
        return record_house_post_collab(
            conv,
            data_root=root,
            from_id=target,
            to_id=CHIEF_OF_STAFF_ID,
            body=reply_text,
            dm_session_id=dm_session_id or room_ctx.dm_session_id.get(),
            room_session_id=room_session_id or room_ctx.room_session_id.get(),
        )
    except Exception:
        logger.exception("room reply projection failed for %s", target)
        return None


def _default_http_poster(url: str, body: dict, timeout: float) -> dict:
    """Production POST helper — stdlib only, no requests dependency."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def build_direct_message_agent_tool(
    *,
    owner_agent: str = "aetheria",
    rate_limiter: DirectCommRateLimiter | None = None,
    http_poster: Callable[[str, dict, float], dict] | None = None,
    edge_writer: Callable[[str, str, str, str, str, str], tuple[str, str]] | None = None,
    vnext_base: str = "http://127.0.0.1:5001",
    session_timeout_seconds: float = 10.0,
    dispatch_timeout_seconds: float = 240.0,
) -> ToolSpec:
    """Build Aetheria's direct_message_agent tool. Collaborators injected
    so the tool is testable without network or DB.

    rate_limiter: defaults to a fresh DirectCommRateLimiter (8/min/peer)
    http_poster: defaults to _default_http_poster (urllib-based)
    edge_writer: optional. When provided, called as
                 edge_writer(coord_node_id, sender, target, session_id, mode,
                             message_head) -> (message_node_id, edge_id)
                 to record a real lattice node for the directive AND an
                 edge tying it to the coord node. None means no audit
                 record (tests use this). The two-row write is what
                 makes the forensic trail FK-satisfiable — earlier
                 attempts to point an edge directly at a session_id
                 silently failed on the edges table's FK constraint.
    """
    limiter = rate_limiter if rate_limiter is not None else DirectCommRateLimiter()
    poster = http_poster if http_poster is not None else _default_http_poster

    def handler(args: Mapping[str, Any]) -> Any:
        target = args.get("target")
        message = args.get("message")
        coord_node_id = args.get("coord_node_id")
        mode = args.get("mode", "execute")

        # Schema-layer defense: coord_node_id is the structural anchor.
        # No anchor, no message — at the registry layer, not a runtime check
        # that can drift.
        if not isinstance(coord_node_id, str) or not coord_node_id.strip():
            raise ToolArgError(
                "coord_node_id is required — every direct communication must be "
                "tied to a Coordination node. See the spec's loop-chatter "
                "constraint at docs/superpowers/specs/"
                "2026-06-05-direct-agent-communication-design.md."
            )
        coord_node_id = coord_node_id.strip()

        if target not in _VALID_TARGETS:
            raise ToolArgError(
                f"target must be one of {sorted(_VALID_TARGETS)}, got {target!r}"
            )
        if mode not in _VALID_MODES:
            raise ToolArgError(
                f"mode must be one of {sorted(_VALID_MODES)}, got {mode!r}"
            )
        if not isinstance(message, str) or not message.strip():
            raise ToolArgError("message must be a non-empty string")

        now = datetime.now()
        if not limiter.under_cap(sender=owner_agent, target=target, now=now):
            retry = limiter.seconds_until_under_cap(
                sender=owner_agent, target=target, now=now,
            )
            return {
                "error": "rate_limited",
                "retry_after_seconds": retry,
                "target": target,
                "coord_node_id": coord_node_id,
            }

        brief = message.strip()

        # Phone / messenger path: Jon is watching. Do NOT nest /chat into the
        # peer while Aetheria still holds the GPU — that hangs. Enqueue a
        # commission, drop the peer icon into the DM, return immediately.
        # citizens-runtime runs the peer; reply projects into the group room.
        try:
            from soveryn.rooms import context as room_ctx

            dm_live = room_ctx.dm_session_id.get()
        except Exception:
            dm_live = None
        if dm_live and mode == "execute":
            async_out = _commission_peer_for_dm(
                owner_agent=owner_agent,
                target=target,
                brief=brief,
                coord_node_id=coord_node_id,
            )
            if async_out.get("ok"):
                limiter.record(sender=owner_agent, target=target, now=now)
                if edge_writer is not None:
                    try:
                        edge_writer(
                            coord_node_id,
                            owner_agent,
                            target,
                            async_out.get("commission_id") or coord_node_id,
                            mode,
                            brief[:200],
                        )
                    except Exception:
                        logger.exception(
                            "lattice forensic record failed for async coord %s",
                            coord_node_id,
                        )
                cid8 = (async_out.get("commission_id") or "")[:8]
                if async_out.get("reused"):
                    content = (
                        f"Already working with {target} via commission `{cid8}`. "
                        "Use read_collab — do not re-dispatch."
                    )
                else:
                    content = (
                        f"Looped in {target} via commission `{cid8}`. "
                        "Their reply will land in the group room — Jon can tap "
                        "their icon in this chat to watch."
                    )
                return {
                    "target": target,
                    "session_id": None,
                    "response_content": content,
                    "finish_reason": "commissioned",
                    "coord_node_id": coord_node_id,
                    "commission_id": async_out.get("commission_id"),
                    "commissioned": True,
                    "reused": bool(async_out.get("reused")),
                    "room_event": async_out.get("room_event"),
                }
            # Fall through to nested chat if commission path failed.

        prefix = _DIRECTIVE_PREFIX if mode == "execute" else _QUERY_PREFIX
        wire_message = prefix.format(cid=coord_node_id) + brief

        # Mint a session keyed by coord_node_id so the audit trail is easy
        # to navigate. The vnext /sessions endpoint creates a fresh one
        # each time — for v1 that's acceptable (lattice edges carry the
        # cross-session continuity); a per-coord-node session reuse pass
        # is deferred to a polish iteration.
        session_title = f"[direct:{coord_node_id}]"
        try:
            session_resp = poster(
                f"{vnext_base.rstrip('/')}/sessions",
                {"agent": target, "title": session_title},
                session_timeout_seconds,
            )
            session_id = session_resp["session_id"]
        except urllib.error.HTTPError as e:
            return {
                "error": "dispatch_failed",
                "message": f"session mint failed: HTTP {e.code}",
                "target": target,
                "coord_node_id": coord_node_id,
            }
        except Exception as e:
            return {
                "error": "dispatch_failed",
                "message": f"session mint failed: {type(e).__name__}: {e}",
                "target": target,
                "coord_node_id": coord_node_id,
            }

        # Drop Vett/Scotty into Jon's messenger group *before* the nested
        # chat so the phone shows the peer icon while work runs.
        room_event = _project_peer_looped_in(
            owner_agent=owner_agent,
            target=target,
            brief=brief,
        )

        try:
            # source=coordination — not "direct" — so citizens-runtime does
            # not treat this nested peer turn as Jon mid-chat (interactive_busy).
            chat_resp = poster(
                f"{vnext_base.rstrip('/')}/chat",
                {
                    "agent": target,
                    "session_id": session_id,
                    "message": wire_message,
                    "source": "coordination",
                },
                dispatch_timeout_seconds,
            )
        except urllib.error.HTTPError as e:
            return {
                "error": "dispatch_failed",
                "message": f"chat dispatch failed: HTTP {e.code}",
                "target": target,
                "session_id": session_id,
                "coord_node_id": coord_node_id,
                "room_event": room_event,
            }
        except Exception as e:
            return {
                "error": "dispatch_failed",
                "message": f"chat dispatch failed: {type(e).__name__}: {e}",
                "target": target,
                "session_id": session_id,
                "coord_node_id": coord_node_id,
                "room_event": room_event,
            }

        # Successful dispatch — record the rate budget and the forensic record.
        limiter.record(sender=owner_agent, target=target, now=now)
        message_node_id: str | None = None
        edge_id: str | None = None
        if edge_writer is not None:
            try:
                # Edge writer signature: (coord_node_id, sender, target,
                # session_id, mode, message_head) -> (message_node_id, edge_id).
                # The writer creates the lattice node AND the edge — earlier
                # attempts to point an edge at a bare session_id failed silently
                # because session ids aren't lattice nodes (FK constraint).
                message_node_id, edge_id = edge_writer(
                    coord_node_id,
                    owner_agent,
                    target,
                    session_id,
                    mode,
                    brief[:200],
                )
            except Exception:
                logger.exception(
                    "lattice forensic record failed for coord %s; chat already happened",
                    coord_node_id,
                )
                message_node_id = None
                edge_id = None

        reply_text = (chat_resp.get("content") or "").strip()
        reply_event = None
        if reply_text:
            reply_event = _project_peer_reply(
                target=target,
                reply_text=reply_text,
                room_session_id=(room_event or {}).get("room_session_id"),
                dm_session_id=(room_event or {}).get("dm_session_id"),
            )

        return {
            "target": target,
            "session_id": session_id,
            "response_content": reply_text,
            "finish_reason": chat_resp.get("finish_reason", ""),
            "coord_node_id": coord_node_id,
            "message_node_id": message_node_id,
            "edge_id": edge_id,
            "room_event": room_event,
            "reply_event": reply_event,
        }

    schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": sorted(_VALID_TARGETS),
                "description": (
                    "Which peer to direct-message. Eve for research/ship; "
                    "Kernel for build/code. You cannot direct-message yourself. "
                    "Vett/Scotty are parked — not DAC targets."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "The instruction (mode=execute) or query (mode=query) "
                    "to send. Write it as you'd speak it — the tool adds "
                    "the framing prefix the peer reads as authoritative."
                ),
            },
            "coord_node_id": {
                "type": "string",
                "description": (
                    "REQUIRED. The Coordination node this directive is "
                    "anchored to. Every direct communication ties back to "
                    "a specific objective — no anchor, no message. This is "
                    "the structural constraint against managerial drift."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["execute", "query"],
                "description": (
                    "execute = 'do this now and report back' (default). "
                    "query = 'tell me your raw observations on this — skip "
                    "the polished report.' Same primitive, different framing."
                ),
                "default": "execute",
            },
        },
        "required": ["target", "message", "coord_node_id"],
        "additionalProperties": False,
    }

    return ToolSpec(
        name="direct_message_agent",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Send a directive or query directly to Eve or Kernel, anchored "
            "to a Coordination node. Prefer house_post_send (kind=request) when "
            "Jon said 'ask Eve/Kernel…' from chat and should watch the group "
            "room — that path wakes them asynchronously and shows their icon. "
            "Use this tool for backstage peer work that must run now and report "
            "into a coord node. Every call is lattice-logged and rate-capped. "
            "Vett/Scotty are parked."
        ),
    )
