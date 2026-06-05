"""signal-cli subprocess client — receive + send wrappers.

We use the one-shot subprocess pattern (not the persistent --json-rpc
daemon mode) for v1 simplicity. Each poll cycle runs `signal-cli
receive --json-output` to drain pending messages; each outbound runs
`signal-cli send`. The JSON-output mode gives us a structured envelope
to parse without scraping signal-cli's prose log lines.

If receive latency turns out to matter (typical poll < 2s should be
fine for a chat-style direct line), this is the seam to migrate to
`signal-cli daemon --socket` with the dbus or socket transport.

The receive output is JSON-Lines: one JSON envelope per delivered
message, with `envelope.source`, `envelope.dataMessage.message`,
`envelope.dataMessage.attachments`, etc.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


class SignalCliError(RuntimeError):
    """Raised when signal-cli exits non-zero or emits unparseable output."""


@dataclass(frozen=True)
class InboundMessage:
    source_e164: str
    timestamp_ms: int
    body: str
    attachment_paths: tuple[str, ...]


def parse_envelopes(raw_stdout: str) -> tuple[InboundMessage, ...]:
    """Parse signal-cli --json-output stdout into typed inbound messages.

    Drops envelopes that aren't text dataMessages (read receipts, typing
    indicators, sync messages from linked devices, etc.). Non-strict on
    individual line errors — one bad line shouldn't drop a batch.
    """
    out: list[InboundMessage] = []
    for line in raw_stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        envelope = obj.get("envelope") if isinstance(obj, dict) else None
        if not isinstance(envelope, dict):
            continue
        data_msg = envelope.get("dataMessage")
        if not isinstance(data_msg, dict):
            continue
        body = data_msg.get("message")
        if not isinstance(body, str):
            # Attachments-only messages have empty body; we still want to
            # surface them so Aetheria can see the image.
            body = ""
        source = envelope.get("source") or envelope.get("sourceNumber")
        if not isinstance(source, str) or not source.strip():
            continue
        ts = envelope.get("timestamp")
        try:
            ts_int = int(ts) if ts is not None else 0
        except (TypeError, ValueError):
            ts_int = 0
        attachments = data_msg.get("attachments") or []
        attachment_paths: list[str] = []
        if isinstance(attachments, list):
            for a in attachments:
                if isinstance(a, dict):
                    # signal-cli writes attachments to
                    # ~/.local/share/signal-cli/attachments/<filename>.
                    # The JSON gives us the filename in `id` (canonical).
                    fname = a.get("id") or a.get("filename") or ""
                    if isinstance(fname, str) and fname.strip():
                        attachment_paths.append(fname.strip())
        out.append(InboundMessage(
            source_e164=source.strip(),
            timestamp_ms=ts_int,
            body=body,
            attachment_paths=tuple(attachment_paths),
        ))
    return tuple(out)


def receive_once(
    *, signal_cli_bin: str, bot_number: str, timeout_seconds: float = 30.0,
) -> tuple[InboundMessage, ...]:
    """Drain pending messages from the server. Blocks up to timeout."""
    result = subprocess.run(
        [signal_cli_bin, "-a", bot_number, "--output", "json", "receive"],
        capture_output=True, text=True, timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise SignalCliError(
            f"signal-cli receive failed (rc={result.returncode}): "
            f"{result.stderr.strip()[:500]}"
        )
    return parse_envelopes(result.stdout)


def send_once(
    *, signal_cli_bin: str, bot_number: str, recipient_e164: str,
    body: str, attachments: tuple[str, ...] = (),
    timeout_seconds: float = 30.0,
) -> None:
    """Send `body` from bot to recipient. Raises SignalCliError on failure.

    attachments — optional tuple of local file paths. Each becomes a
    `--attachment <path>` flag on signal-cli send. Long-form flag is used
    to avoid ambiguity with the top-level `-a/--account` flag.
    """
    args = [signal_cli_bin, "-a", bot_number, "send", "-m", body]
    for path in attachments:
        args.extend(["--attachment", path])
    args.append(recipient_e164)
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise SignalCliError(
            f"signal-cli send to {recipient_e164!r} failed "
            f"(rc={result.returncode}): {result.stderr.strip()[:500]}"
        )
