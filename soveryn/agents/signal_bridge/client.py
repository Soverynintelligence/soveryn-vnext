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

import contextlib
import fcntl
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


class SignalCliError(RuntimeError):
    """Raised when signal-cli exits non-zero or emits unparseable output."""


@dataclass(frozen=True)
class InboundMessage:
    source_e164: str
    timestamp_ms: int
    body: str
    # signal-cli's `id` field for each attachment — a bare filename, NOT
    # an absolute path. Resolve via `resolve_attachment_id()` below before
    # reading bytes. Field was named `attachment_paths` until 2026-06-05;
    # the rename happened after a production bug (T8) where the consumer
    # assumed paths and silently failed read_bytes() in CWD.
    attachment_ids: tuple[str, ...]


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
        attachment_ids: list[str] = []
        if isinstance(attachments, list):
            for a in attachments:
                if isinstance(a, dict):
                    # signal-cli writes attachments to
                    # ~/.local/share/signal-cli/attachments/<id>. The JSON
                    # gives us the bare filename in `id` (canonical). Use
                    # resolve_attachment_id() below to get an absolute path.
                    fname = a.get("id") or a.get("filename") or ""
                    if isinstance(fname, str) and fname.strip():
                        attachment_ids.append(fname.strip())
        out.append(InboundMessage(
            source_e164=source.strip(),
            timestamp_ms=ts_int,
            body=body,
            attachment_ids=tuple(attachment_ids),
        ))
    return tuple(out)


# Default signal-cli attachment directory. Exposed so the daemon (and
# tests) share the same resolver — keeps the misnomer-fix quarantined.
DEFAULT_SIGNAL_CLI_ATTACHMENTS_DIR = Path.home() / ".local/share/signal-cli/attachments"


def resolve_attachment_id(
    attachment_id: str,
    *,
    attachments_dir: Path | None = None,
) -> Path:
    """Resolve a signal-cli attachment id (bare filename) to an absolute path.

    Defense against a hypothetical signal-cli id containing path separators
    (today they're random-looking opaque strings; the producer doesn't
    document the format): reject ids that traverse out of the attachments
    directory. Re-eval trigger: signal-cli's id format ever becomes
    documented as hierarchical.

    `attachments_dir=None` resolves at call time against the module-level
    DEFAULT_SIGNAL_CLI_ATTACHMENTS_DIR so tests can monkeypatch the default.
    """
    if attachments_dir is None:
        attachments_dir = DEFAULT_SIGNAL_CLI_ATTACHMENTS_DIR
    p = Path(attachment_id)
    if ".." in p.parts:
        raise ValueError(
            f"attachment id contains traversal segment: {attachment_id!r}"
        )
    if p.is_absolute():
        return p
    return attachments_dir / p


# signal-cli holds a write-lock on its data dir while a subprocess is in
# flight. The bridge daemon's receive loop and the signal_send tool can
# race for that lock and one will fail with a "config file locked" error.
# Serialize at the Python level: any signal-cli invocation acquires the
# same file lock first. The lock file lives next to signal-cli's own
# data so it survives across daemon restarts but is scoped to this user.
_SIGNAL_CLI_LOCK_PATH = Path.home() / ".local/share/signal-cli/.soveryn-serialize.lock"


@contextlib.contextmanager
def _signal_cli_lock() -> Iterator[None]:
    """Block until exclusive access to signal-cli is held, then yield.

    Uses fcntl.flock — process-level POSIX advisory lock. Both the bridge
    daemon's receive_once and the signal_send tool's send_once acquire
    this before invoking signal-cli, so they can never collide on
    signal-cli's own config-dir lock. The lock is released on context
    exit even if the subprocess raises.
    """
    _SIGNAL_CLI_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd = open(_SIGNAL_CLI_LOCK_PATH, "w")
    try:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        fd.close()


def receive_once(
    *, signal_cli_bin: str, bot_number: str, timeout_seconds: float = 30.0,
) -> tuple[InboundMessage, ...]:
    """Drain pending messages from the server. Blocks up to timeout."""
    cli_timeout = max(1, int(timeout_seconds))
    with _signal_cli_lock():
        result = subprocess.run(
            [
                signal_cli_bin, "-a", bot_number, "--output", "json",
                "receive", "--timeout", str(cli_timeout),
                "--max-messages", "10",
            ],
            capture_output=True, text=True, timeout=cli_timeout + 10,
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
    # `--attachment` is argparse nargs='*' — without an explicit `--`
    # terminator the trailing recipient gets gobbled as another attachment
    # value and signal-cli fails with "no recipients given." Only emit the
    # `--` when attachments are present so the non-attachment argv stays
    # byte-identical to the pre-change shape.
    if attachments:
        args.append("--")
    args.append(recipient_e164)
    with _signal_cli_lock():
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout_seconds,
        )
    if result.returncode != 0:
        raise SignalCliError(
            f"signal-cli send to {recipient_e164!r} failed "
            f"(rc={result.returncode}): {result.stderr.strip()[:500]}"
        )
