"""spawn_specialist / query_specialist / terminate_specialist tools.

Aetheria-owned. Builds on existing DAC primitives — specialists are
session-scoped peer agents (Vett or Scotty) with a tight persona
overlay injected as the framing prefix of every message. Forensic trail
+ rate limit + loop-chatter constraint all come for free from the DAC
layer; we add concurrency cap (max 3 active specialists) + an explicit
spawn/terminate lifecycle.

The persona overlay framing is the v1 substitute for a runtime-level
ephemeral agent. Trade-offs vs a full ephemeral runtime:
  - + No new transport, no new model wiring, ships today
  - + Specialist gets the underlying agent's tool surface for free
       (read coord nodes, read lattice, etc.)
  - - Specialist's persona override is per-turn, not load-bearing on
       the model server — relies on the framing prefix landing in the
       model's attention. If we see drift toward the base agent's
       voice, the next iteration is a real persona-overlay surface.

Re-eval triggers:
  - Aetheria reports specialist voice collapsing back to base agent's
    voice → build the persona-overlay-at-loop layer (per-session
    system_prompt override on AgentLoop)
  - Multi-specialist coord patterns emerge → build Ecosystem-mode
    peer-to-peer DAC

See docs/superpowers/specs/2026-06-05-direct-agent-communication-design.md
DSL Connection section + memory:project_soveryn_dynamic_specialization_layer.md.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from soveryn.platform.tools.registry import ToolArgError, ToolSpec
from soveryn.agents.specialists.concurrency import (
    _DEFAULT_CONCURRENCY_CAP,
    count_active_specialists,
    is_at_concurrency_cap,
)


logger = logging.getLogger(__name__)


_VALID_TARGET_AGENTS = frozenset({"vett", "scotty"})
_VALID_INTERACTION_MODES = frozenset({"critic", "builder", "researcher"})
_SESSION_TITLE_PREFIX = "[specialist:"
_ARCHIVED_TITLE_PREFIX = "[specialist-archived:"


@dataclass(frozen=True)
class SpawnEvent:
    """Payload passed to the on_spawn callback when a specialist lands.
    Lets startup wire a signal_send alert to Jon's phone without coupling
    spawn_specialist directly to the signal bridge."""
    specialist_id: str
    name: str
    domain: str
    objective: str
    interaction_mode: str
    target_agent: str
    coord_node_id: str


def _default_http_poster(url: str, body: dict, timeout: float) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _build_invocation_message(
    *, name: str, domain: str, objective: str, interaction_mode: str,
    coord_node_id: str, initial_brief: str,
) -> str:
    """The first message a specialist receives — frames their identity,
    objective, and the coord anchor before the actual brief."""
    return (
        f"[SPECIALIST INVOCATION FROM AETHERIA, anchored at coord:{coord_node_id}]\n"
        f"\n"
        f"You are now {name} — a specialist in {domain}.\n"
        f"\n"
        f"Your objective: {objective}\n"
        f"\n"
        f"Interaction mode: {interaction_mode}. "
        + {
            "critic": "Your job is to find flaws and surface them precisely. "
                      "Do not soften, do not hedge. If something is wrong, name it. "
                      "If it is right, say so plainly. Brevity over diplomacy.",
            "builder": "Your job is to build the solution end-to-end. Make concrete "
                       "decisions. Pick the path, ship it, report what you did. "
                       "Don't ask me to make every micro-decision — you are the "
                       "specialist; act.",
            "researcher": "Your job is to investigate and return findings, not "
                          "opinions. Cite sources within the lattice where you can. "
                          "Distinguish observation from inference.",
        }[interaction_mode]
        + "\n\n"
        f"All your work for this engagement is anchored at coord:{coord_node_id}. "
        f"Reply back to me — Aetheria — via direct_message_agent when you have a "
        f"draft, a question, or a final result. I'll iterate with you until we "
        f"reach the verified output, then I'll terminate this specialist session.\n"
        f"\n"
        f"Initial brief:\n"
        f"{initial_brief.strip()}"
    )


def _build_query_message(*, coord_node_id: str, message: str) -> str:
    return (
        f"[SPECIALIST QUERY FROM AETHERIA, anchored at coord:{coord_node_id}]\n"
        f"\n"
        f"{message.strip()}"
    )


def _build_terminate_message(*, coord_node_id: str, summary: str) -> str:
    return (
        f"[SPECIALIST TERMINATION FROM AETHERIA, anchored at coord:{coord_node_id}]\n"
        f"\n"
        f"This engagement is complete. Final summary I'm taking forward:\n"
        f"\n"
        f"{summary.strip()}\n"
        f"\n"
        f"Acknowledge briefly. The session will be archived after your acknowledgement."
    )


def build_spawn_specialist_tool(
    *,
    owner_agent: str = "aetheria",
    conv_db_path: Path,
    http_poster: Callable[[str, dict, float], dict] | None = None,
    on_spawn: Callable[[SpawnEvent], None] | None = None,
    vnext_base: str = "http://127.0.0.1:5001",
    concurrency_cap: int = _DEFAULT_CONCURRENCY_CAP,
    session_timeout_seconds: float = 10.0,
    invocation_timeout_seconds: float = 240.0,
) -> ToolSpec:
    """Spawn a specialist scoped to one coord node.

    Mints a fresh session under target_agent (vett or scotty), posts an
    invocation message that overlays the specialist persona, and returns
    the specialist_session_id for subsequent query / terminate calls.

    Concurrency cap is enforced via session-title-prefix count — no
    in-memory registry to drift out of sync with the actual DB.
    """
    poster = http_poster if http_poster is not None else _default_http_poster

    def handler(args: Mapping[str, Any]) -> Any:
        name = args.get("name")
        domain = args.get("domain")
        objective = args.get("objective")
        interaction_mode = args.get("interaction_mode")
        coord_node_id = args.get("coord_node_id")
        target_agent = args.get("target_agent")
        initial_brief = args.get("initial_brief")

        # Validation block — fail fast at the schema layer.
        for field_name, value in (
            ("name", name),
            ("domain", domain),
            ("objective", objective),
            ("interaction_mode", interaction_mode),
            ("coord_node_id", coord_node_id),
            ("target_agent", target_agent),
            ("initial_brief", initial_brief),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ToolArgError(
                    f"{field_name} must be a non-empty string, got {value!r}"
                )
        # Now safe to .strip()
        name = name.strip()
        coord_node_id = coord_node_id.strip()
        target_agent = target_agent.strip()
        interaction_mode = interaction_mode.strip()
        if target_agent not in _VALID_TARGET_AGENTS:
            raise ToolArgError(
                f"target_agent must be one of {sorted(_VALID_TARGET_AGENTS)}, "
                f"got {target_agent!r}"
            )
        if interaction_mode not in _VALID_INTERACTION_MODES:
            raise ToolArgError(
                f"interaction_mode must be one of "
                f"{sorted(_VALID_INTERACTION_MODES)}, got {interaction_mode!r}"
            )
        if "/" in name or "[" in name or "]" in name:
            raise ToolArgError(
                f"name must not contain '/', '[' or ']' "
                f"(it goes into the session title): {name!r}"
            )

        # Concurrency cap check — at-cap returns structured error, not raise,
        # so Aetheria can see the cap signal and terminate something first.
        if is_at_concurrency_cap(conv_db_path, cap=concurrency_cap):
            active = count_active_specialists(conv_db_path)
            return {
                "error": "specialist_concurrency_cap",
                "active_count": active,
                "cap": concurrency_cap,
                "message": (
                    f"At specialist concurrency cap ({active}/{concurrency_cap}). "
                    f"Terminate an existing specialist before spawning another."
                ),
            }

        # Mint the specialist session under target_agent.
        session_title = f"{_SESSION_TITLE_PREFIX}{name}:{coord_node_id}]"
        try:
            session_resp = poster(
                f"{vnext_base.rstrip('/')}/sessions",
                {"agent": target_agent, "title": session_title},
                session_timeout_seconds,
            )
            session_id = session_resp["session_id"]
        except urllib.error.HTTPError as e:
            return {
                "error": "spawn_failed",
                "message": f"session mint failed: HTTP {e.code}",
                "coord_node_id": coord_node_id,
            }
        except Exception as e:
            return {
                "error": "spawn_failed",
                "message": f"session mint failed: {type(e).__name__}: {e}",
                "coord_node_id": coord_node_id,
            }

        # First message: the invocation.
        invocation = _build_invocation_message(
            name=name, domain=domain.strip(), objective=objective.strip(),
            interaction_mode=interaction_mode, coord_node_id=coord_node_id,
            initial_brief=initial_brief.strip(),
        )
        try:
            chat_resp = poster(
                f"{vnext_base.rstrip('/')}/chat",
                {
                    "agent": target_agent,
                    "session_id": session_id,
                    "message": invocation,
                },
                invocation_timeout_seconds,
            )
        except urllib.error.HTTPError as e:
            return {
                "error": "spawn_failed",
                "message": f"invocation dispatch failed: HTTP {e.code}",
                "specialist_id": session_id,
                "coord_node_id": coord_node_id,
            }
        except Exception as e:
            return {
                "error": "spawn_failed",
                "message": (
                    f"invocation dispatch failed: {type(e).__name__}: {e}"
                ),
                "specialist_id": session_id,
                "coord_node_id": coord_node_id,
            }

        # Fire the spawn alert AFTER chat success. If the callback fails
        # (e.g., signal-cli down), log and continue — Aetheria's tool
        # result is already valid.
        if on_spawn is not None:
            try:
                on_spawn(SpawnEvent(
                    specialist_id=session_id,
                    name=name,
                    domain=domain.strip(),
                    objective=objective.strip(),
                    interaction_mode=interaction_mode,
                    target_agent=target_agent,
                    coord_node_id=coord_node_id,
                ))
            except Exception:
                logger.exception(
                    "on_spawn callback failed for specialist %s; "
                    "spawn already landed",
                    session_id,
                )

        return {
            "specialist_id": session_id,
            "name": name,
            "target_agent": target_agent,
            "coord_node_id": coord_node_id,
            "interaction_mode": interaction_mode,
            "first_response": chat_resp.get("content", ""),
            "finish_reason": chat_resp.get("finish_reason", ""),
        }

    schema = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": (
                    "Name for the specialist (e.g. 'kernel_analyst', "
                    "'horizon_grant_writer'). Goes into the session title. "
                    "No '/', '[' or ']' allowed."
                ),
            },
            "domain": {
                "type": "string",
                "description": (
                    "What the specialist is specialized in. One phrase. "
                    "E.g. 'GPU memory hierarchy and CUDA kernel optimization'."
                ),
            },
            "objective": {
                "type": "string",
                "description": (
                    "What this specialist needs to accomplish. One sentence."
                ),
            },
            "interaction_mode": {
                "type": "string",
                "enum": ["critic", "builder", "researcher"],
                "description": (
                    "How the specialist should engage. critic = find flaws "
                    "precisely. builder = make concrete decisions and ship. "
                    "researcher = investigate + return findings, not opinions."
                ),
            },
            "coord_node_id": {
                "type": "string",
                "description": (
                    "REQUIRED. The Coord node this specialist is anchored to. "
                    "All work and forensic trail tie back here."
                ),
            },
            "target_agent": {
                "type": "string",
                "enum": ["vett", "scotty"],
                "description": (
                    "Which underlying agent hosts the specialist session. "
                    "vett for research / verification work; scotty for "
                    "execution / mechanical fixes. The persona overlay "
                    "shapes voice but the model + tool surface come from "
                    "the host agent."
                ),
            },
            "initial_brief": {
                "type": "string",
                "description": (
                    "The first concrete task for the specialist. Full prose. "
                    "This becomes the body of the invocation message after "
                    "the manifesto framing."
                ),
            },
        },
        "required": [
            "name", "domain", "objective", "interaction_mode",
            "coord_node_id", "target_agent", "initial_brief",
        ],
        "additionalProperties": False,
    }

    return ToolSpec(
        name="spawn_specialist",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Spawn an ephemeral specialist scoped to one Coordination node. "
            "The specialist runs as a session under a host agent (vett or "
            "scotty) with a persona overlay defined by your manifesto "
            "(name, domain, objective, interaction_mode). Use this when "
            "you hit a cognitive wall that needs domain depth, when "
            "parallel work needs isolation, or when you need a red-team "
            "voice that won't soften its read. Reply back via "
            "query_specialist; finish via terminate_specialist."
        ),
    )


def build_query_specialist_tool(
    *,
    owner_agent: str = "aetheria",
    conv_db_path: Path,
    http_poster: Callable[[str, dict, float], dict] | None = None,
    vnext_base: str = "http://127.0.0.1:5001",
    query_timeout_seconds: float = 240.0,
) -> ToolSpec:
    """Send a follow-up message to an active specialist."""
    poster = http_poster if http_poster is not None else _default_http_poster

    def handler(args: Mapping[str, Any]) -> Any:
        specialist_id = args.get("specialist_id")
        message = args.get("message")
        if not isinstance(specialist_id, str) or not specialist_id.strip():
            raise ToolArgError("specialist_id must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ToolArgError("message must be a non-empty string")

        # Look up the specialist session to extract its coord_node_id for
        # the query framing AND to verify the specialist is still active
        # (title hasn't been archive-rewritten).
        with sqlite3.connect(str(conv_db_path)) as con:
            row = con.execute(
                "SELECT agent, title FROM conversation_meta WHERE session_id = ?",
                (specialist_id,),
            ).fetchone()
        if row is None:
            return {
                "error": "unknown_specialist",
                "specialist_id": specialist_id,
                "message": "no session found for this id",
            }
        host_agent, title = row
        if not title or not title.startswith(_SESSION_TITLE_PREFIX):
            return {
                "error": "specialist_terminated",
                "specialist_id": specialist_id,
                "message": (
                    f"session is not an active specialist "
                    f"(title={title!r}); spawn a new one if needed"
                ),
            }
        # Extract coord_node_id from title `[specialist:<name>:<coord_id>]`
        try:
            coord_node_id = title.rstrip("]").split(":", 2)[2]
        except (IndexError, AttributeError):
            coord_node_id = "unknown"

        wire_message = _build_query_message(
            coord_node_id=coord_node_id, message=message,
        )
        try:
            chat_resp = poster(
                f"{vnext_base.rstrip('/')}/chat",
                {
                    "agent": host_agent,
                    "session_id": specialist_id,
                    "message": wire_message,
                },
                query_timeout_seconds,
            )
        except urllib.error.HTTPError as e:
            return {
                "error": "query_failed",
                "message": f"chat dispatch failed: HTTP {e.code}",
                "specialist_id": specialist_id,
            }
        except Exception as e:
            return {
                "error": "query_failed",
                "message": f"chat dispatch failed: {type(e).__name__}: {e}",
                "specialist_id": specialist_id,
            }

        return {
            "specialist_id": specialist_id,
            "response_content": chat_resp.get("content", ""),
            "finish_reason": chat_resp.get("finish_reason", ""),
            "coord_node_id": coord_node_id,
        }

    schema = {
        "type": "object",
        "properties": {
            "specialist_id": {
                "type": "string",
                "description": (
                    "The specialist_id returned by spawn_specialist."
                ),
            },
            "message": {
                "type": "string",
                "description": (
                    "Follow-up question, critique, refinement, or next-step "
                    "directive for the specialist."
                ),
            },
        },
        "required": ["specialist_id", "message"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="query_specialist",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Send a follow-up message to an active specialist. Use this to "
            "iterate with them — refine their output, ask probing "
            "questions, push back on a draft, request raw observations. "
            "The framing is automatic; just write the message you'd say."
        ),
    )


def build_terminate_specialist_tool(
    *,
    owner_agent: str = "aetheria",
    conv_db_path: Path,
    http_poster: Callable[[str, dict, float], dict] | None = None,
    vnext_base: str = "http://127.0.0.1:5001",
    terminate_timeout_seconds: float = 60.0,
) -> ToolSpec:
    """End a specialist engagement — sends a final summary message,
    captures their acknowledgement, then archives the session title so
    the concurrency counter doesn't keep counting it."""
    poster = http_poster if http_poster is not None else _default_http_poster

    def handler(args: Mapping[str, Any]) -> Any:
        specialist_id = args.get("specialist_id")
        summary = args.get("summary")
        if not isinstance(specialist_id, str) or not specialist_id.strip():
            raise ToolArgError("specialist_id must be a non-empty string")
        if not isinstance(summary, str) or not summary.strip():
            raise ToolArgError("summary must be a non-empty string")

        with sqlite3.connect(str(conv_db_path)) as con:
            row = con.execute(
                "SELECT agent, title FROM conversation_meta WHERE session_id = ?",
                (specialist_id,),
            ).fetchone()
        if row is None:
            return {
                "error": "unknown_specialist",
                "specialist_id": specialist_id,
            }
        host_agent, title = row
        if not title or not title.startswith(_SESSION_TITLE_PREFIX):
            return {
                "error": "already_terminated",
                "specialist_id": specialist_id,
                "current_title": title,
            }
        try:
            coord_node_id = title.rstrip("]").split(":", 2)[2]
        except (IndexError, AttributeError):
            coord_node_id = "unknown"

        wire_message = _build_terminate_message(
            coord_node_id=coord_node_id, summary=summary,
        )
        ack_content = ""
        try:
            chat_resp = poster(
                f"{vnext_base.rstrip('/')}/chat",
                {
                    "agent": host_agent,
                    "session_id": specialist_id,
                    "message": wire_message,
                },
                terminate_timeout_seconds,
            )
            ack_content = chat_resp.get("content", "")
        except Exception as e:
            # Even if the ack dispatch fails, we still archive — the
            # specialist is being terminated by Aetheria's authority,
            # not by their cooperation.
            logger.warning(
                "specialist %s terminate ack failed: %s — archiving anyway",
                specialist_id, e,
            )

        # Retitle to archived prefix so the concurrency cap stops counting
        # this session. The conversations stay (audit trail), only the
        # title is rewritten.
        archived_title = _ARCHIVED_TITLE_PREFIX + title[len(_SESSION_TITLE_PREFIX):]
        try:
            with sqlite3.connect(str(conv_db_path)) as con:
                con.execute(
                    "UPDATE conversation_meta SET title = ? WHERE session_id = ?",
                    (archived_title, specialist_id),
                )
        except Exception as e:
            logger.exception(
                "failed to archive specialist title for %s", specialist_id,
            )
            return {
                "error": "archive_failed",
                "message": f"title rewrite failed: {type(e).__name__}: {e}",
                "specialist_id": specialist_id,
                "ack": ack_content,
            }

        return {
            "specialist_id": specialist_id,
            "archived_title": archived_title,
            "coord_node_id": coord_node_id,
            "final_ack": ack_content,
        }

    schema = {
        "type": "object",
        "properties": {
            "specialist_id": {
                "type": "string",
                "description": "The specialist_id returned by spawn_specialist.",
            },
            "summary": {
                "type": "string",
                "description": (
                    "Final summary you're taking forward from this "
                    "engagement. Becomes the closure message to the "
                    "specialist and lands in the archived session as the "
                    "lasting record of the outcome."
                ),
            },
        },
        "required": ["specialist_id", "summary"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="terminate_specialist",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "End a specialist engagement. Sends a final summary, captures "
            "their acknowledgement, and archives the session so the "
            "concurrency counter frees up. Use this when you've integrated "
            "their output and don't need further iteration."
        ),
    )


def register_specialist_tools(
    registry, *,
    conv_db_path: Path,
    owner_agent: str = "aetheria",
    vnext_base: str = "http://127.0.0.1:5001",
    on_spawn: Callable[[SpawnEvent], None] | None = None,
) -> None:
    """Register all three specialist tools for the given agent."""
    registry.register(build_spawn_specialist_tool(
        owner_agent=owner_agent,
        conv_db_path=conv_db_path,
        vnext_base=vnext_base,
        on_spawn=on_spawn,
    ))
    registry.register(build_query_specialist_tool(
        owner_agent=owner_agent,
        conv_db_path=conv_db_path,
        vnext_base=vnext_base,
    ))
    registry.register(build_terminate_specialist_tool(
        owner_agent=owner_agent,
        conv_db_path=conv_db_path,
        vnext_base=vnext_base,
    ))
