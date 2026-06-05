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


logger = logging.getLogger(__name__)


_VALID_TARGETS = frozenset({"vett", "scotty"})
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

        prefix = _DIRECTIVE_PREFIX if mode == "execute" else _QUERY_PREFIX
        wire_message = prefix.format(cid=coord_node_id) + message.strip()

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

        try:
            chat_resp = poster(
                f"{vnext_base.rstrip('/')}/chat",
                {"agent": target, "session_id": session_id, "message": wire_message},
                dispatch_timeout_seconds,
            )
        except urllib.error.HTTPError as e:
            return {
                "error": "dispatch_failed",
                "message": f"chat dispatch failed: HTTP {e.code}",
                "target": target,
                "session_id": session_id,
                "coord_node_id": coord_node_id,
            }
        except Exception as e:
            return {
                "error": "dispatch_failed",
                "message": f"chat dispatch failed: {type(e).__name__}: {e}",
                "target": target,
                "session_id": session_id,
                "coord_node_id": coord_node_id,
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
                    message.strip()[:200],
                )
            except Exception:
                logger.exception(
                    "lattice forensic record failed for coord %s; chat already happened",
                    coord_node_id,
                )
                message_node_id = None
                edge_id = None

        return {
            "target": target,
            "session_id": session_id,
            "response_content": chat_resp.get("content", ""),
            "finish_reason": chat_resp.get("finish_reason", ""),
            "coord_node_id": coord_node_id,
            "message_node_id": message_node_id,
            "edge_id": edge_id,
        }

    schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "enum": ["vett", "scotty"],
                "description": (
                    "Which peer agent to direct-message. Vett for research / "
                    "verification work; Scotty for execution / mechanical fixes. "
                    "You cannot direct-message yourself."
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
            "Send a directive or query directly to Vett or Scotty, anchored "
            "to a specific Coordination node. Use this when you need a peer "
            "to act or report without waiting for a heartbeat round-trip. "
            "Every call is forensically logged (lattice edge) and rate-capped."
        ),
    )
