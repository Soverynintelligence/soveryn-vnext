"""Signal bridge config — env-loaded, frozen.

Loaded once at daemon startup. SOVERYN_SIGNAL_ALLOWED_NUMBERS is a
comma-separated E.164 list; senders not on the list are silently dropped
(with an audit row in signal_log).
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SignalBridgeConfig:
    bot_number: str                       # e.g. "+19102489392"
    allowed_numbers: frozenset[str]       # senders the bridge will route
    signal_cli_bin: str                   # absolute path to signal-cli
    vnext_base: str                       # vnext HTTP base for /chat
    chat_timeout_seconds: int             # /chat timeout per inbound
    enabled: bool                         # kill switch
    poll_interval_seconds: float          # daemon sleep between receive cycles
    outbound_max_retries: int             # retries on transient signal-cli send errors
    outbound_initial_backoff_seconds: float

    @classmethod
    def from_env(cls, env: dict | None = None) -> "SignalBridgeConfig":
        env = env if env is not None else os.environ
        bot_number = env.get("SOVERYN_SIGNAL_BOT_NUMBER", "").strip()
        allowed_raw = env.get("SOVERYN_SIGNAL_ALLOWED_NUMBERS", "")
        allowed = frozenset(
            n.strip() for n in allowed_raw.split(",") if n.strip()
        )
        return cls(
            bot_number=bot_number,
            allowed_numbers=allowed,
            signal_cli_bin=env.get("SOVERYN_SIGNAL_CLI_BIN", "/usr/local/bin/signal-cli"),
            vnext_base=env.get("SOVERYN_SIGNAL_VNEXT_BASE", "http://127.0.0.1:5001"),
            chat_timeout_seconds=int(env.get("SOVERYN_SIGNAL_CHAT_TIMEOUT", "240")),
            enabled=_parse_bool(env.get("SOVERYN_SIGNAL_BRIDGE_ENABLED", "true")),
            poll_interval_seconds=float(env.get("SOVERYN_SIGNAL_POLL_INTERVAL", "2.0")),
            outbound_max_retries=int(env.get("SOVERYN_SIGNAL_OUTBOUND_MAX_RETRIES", "3")),
            outbound_initial_backoff_seconds=float(
                env.get("SOVERYN_SIGNAL_OUTBOUND_BACKOFF", "2.0")
            ),
        )


def _parse_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}
