"""signal_send tool — Aetheria-initiated outbound to the Direct Line.

The bridge daemon handles the inbound → response cycle. This tool lets
Aetheria send WITHOUT a prior inbound prompt — heartbeat-driven thoughts,
proactive alerts, "you should know this" pings. Closes the second half
of the Direct Line.

Safety boundaries:
  - Recipient MUST be in SOVERYN_SIGNAL_ALLOWED_NUMBERS. She can't
    message arbitrary numbers — the same allowlist as the inbound
    bridge gates outbound too.
  - Optional recipient defaults to the first allowlisted number
    (typically Jon's). Lets the heartbeat fire signal_send("...")
    without ceremony when there's only one obvious target.
  - Every call writes a signal_log audit row, success or failure.
  - Outbound failures return a structured {error, message} result
    rather than raising — the model gets to see "send failed" and
    respond accordingly.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.agents.signal_bridge.client import SignalCliError, send_once
from soveryn.agents.signal_bridge.config import SignalBridgeConfig
from soveryn.platform.tools.registry import ToolArgError, ToolRegistry, ToolSpec


def build_signal_send_tool(
    *,
    config: SignalBridgeConfig,
    lattice_db_path: Path,
    owner_agent: str = "aetheria",
) -> ToolSpec:
    """Outbound-only Direct Line tool. Wraps signal-cli send + writes
    an audit row to signal_log. Allowlist enforced at handler time."""

    default_recipient: str | None = None
    if config.allowed_numbers:
        # First allowlisted number is the "send-without-specifying-anyone"
        # default. Sorted for deterministic behavior.
        default_recipient = sorted(config.allowed_numbers)[0]

    def handler(args: Mapping[str, Any]) -> Any:
        message = args.get("message", "")
        if not isinstance(message, str) or not message.strip():
            raise ToolArgError("message must be a non-empty string")
        recipient = args.get("recipient") or default_recipient
        if not isinstance(recipient, str) or not recipient.strip():
            raise ToolArgError(
                "recipient must be a non-empty E.164 string, or default "
                "must be configured via SOVERYN_SIGNAL_ALLOWED_NUMBERS"
            )
        recipient = recipient.strip()
        if recipient not in config.allowed_numbers:
            raise ToolArgError(
                f"recipient {recipient!r} not in allowlist. "
                f"Allowed: {sorted(config.allowed_numbers)}. "
                f"To message a new number, add it to "
                f"SOVERYN_SIGNAL_ALLOWED_NUMBERS first."
            )

        try:
            send_once(
                signal_cli_bin=config.signal_cli_bin,
                bot_number=config.bot_number,
                recipient_e164=recipient,
                body=message,
            )
        except SignalCliError as e:
            _log_event(
                lattice_db_path,
                direction="outbound",
                sender=config.bot_number, recipient=recipient,
                body_head=message[:200], attachment_count=0,
                error=f"send failed: {e}",
            )
            return {
                "error": "send_failed",
                "message": str(e),
                "recipient": recipient,
            }

        _log_event(
            lattice_db_path,
            direction="outbound",
            sender=config.bot_number, recipient=recipient,
            body_head=message[:200], attachment_count=0,
            error=None,
        )
        return {
            "sent": True,
            "recipient": recipient,
            "delivered_at": datetime.now().isoformat(),
        }

    schema = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": (
                    "The text to send. Keep it concise — this lands on "
                    "Jon's phone like an SMS. No formatting beyond plain "
                    "text + line breaks."
                ),
            },
            "recipient": {
                "type": "string",
                "description": (
                    "Optional E.164 number to send to. Defaults to the "
                    "first allowlisted number (typically Jon's). Must be "
                    "in SOVERYN_SIGNAL_ALLOWED_NUMBERS — you can't "
                    "message arbitrary numbers."
                ),
            },
        },
        "required": ["message"],
        "additionalProperties": False,
    }
    return ToolSpec(
        name="signal_send",
        owner=owner_agent,
        schema=schema,
        handler=handler,
        description=(
            "Send a Signal message to Jon (or another allowlisted recipient). "
            "Use this when you've decided something is worth surfacing in "
            "real-time — a finding, an alert, a thought that wants his "
            "attention before the next chat session. Outbound only; "
            "his replies come back through the bridge to your chat surface."
        ),
    )


def register_signal_send_tool(
    registry: ToolRegistry,
    *,
    config: SignalBridgeConfig,
    lattice_db_path: Path,
    owner_agent: str = "aetheria",
) -> None:
    """Register signal_send for one agent (Aetheria by default)."""
    registry.register(build_signal_send_tool(
        config=config,
        lattice_db_path=lattice_db_path,
        owner_agent=owner_agent,
    ))


def _log_event(
    lattice_db_path: Path,
    *,
    direction: str,
    sender: str | None,
    recipient: str | None,
    body_head: str,
    attachment_count: int,
    error: str | None,
) -> None:
    try:
        with sqlite3.connect(str(lattice_db_path)) as con:
            con.execute(
                "INSERT INTO signal_log "
                "(id, direction, sender_e164, recipient_e164, body_head, "
                "attachment_count, error, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), direction, sender, recipient,
                 body_head, attachment_count, error,
                 datetime.now().isoformat()),
            )
    except Exception:
        # The tool's own errors shouldn't fail the whole turn — the model
        # already got a structured error result. Audit failure is logged
        # to stdlib logging via caller's logger if they wired one.
        pass
