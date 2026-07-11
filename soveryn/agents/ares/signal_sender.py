"""Outbound-only Signal sender for Ares alerts."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class SignalConfig:
    bot_number: str
    user_number: str
    signal_cli_bin: str
    hourly_cap: int = 6
    daily_cap: int = 30
    quiet_start_hour: int = 23
    quiet_end_hour: int = 7


@dataclass(frozen=True)
class SignalSendResult:
    sent: bool
    reason: str


class RateLimiter:
    """Rolling hourly/daily send cap tracker."""

    def __init__(self) -> None:
        self._sent_at: list[datetime] = []

    def under_cap(self, now: datetime, *, hourly_cap: int, daily_cap: int) -> bool:
        self._prune(now)
        hour_count = sum(1 for sent_at in self._sent_at if (now - sent_at).total_seconds() < 3600)
        day_count = sum(1 for sent_at in self._sent_at if (now - sent_at).total_seconds() < 86400)
        return hour_count < hourly_cap and day_count < daily_cap

    def record(self, now: datetime) -> None:
        self._sent_at.append(now)
        self._prune(now)

    def _prune(self, now: datetime) -> None:
        self._sent_at = [
            sent_at for sent_at in self._sent_at
            if (now - sent_at).total_seconds() < 86400
        ]


class SignalCliProvider:
    """signal-cli subprocess transport."""

    def __init__(self, *, bot_number: str, binary: str) -> None:
        self.bot_number = bot_number
        self.binary = binary

    def send(self, message: str, recipient: str) -> bool:
        if not message.strip() or not recipient.strip():
            return False
        # signal-cli allows only ONE process per account. The signal-bridge
        # holds the account for up to 30s per `receive --timeout 30` poll, so
        # a naive send here collides ("Config file is in use by another
        # instance"). Serialize through the SAME cross-process fcntl.flock the
        # bridge uses (lazy import avoids any module-load coupling); the lock
        # blocks until the bridge's receive releases, then the send runs with
        # exclusive access.
        from soveryn.agents.signal_bridge.client import _signal_cli_lock
        try:
            with _signal_cli_lock():
                result = subprocess.run(
                    [self.binary, "-a", self.bot_number, "send", "-m", message, recipient],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0


class SignalSender:
    """Ares Signal sender with quiet-hours/rate-cap enforcement."""

    def __init__(
        self,
        *,
        config: SignalConfig | None = None,
        provider=None,
        limiter: RateLimiter | None = None,
        clock: Callable[[], datetime] | None = None,
        binary_exists: Callable[[str], bool] | None = None,
    ) -> None:
        self.config = config or config_from_env()
        self.provider = provider or SignalCliProvider(
            bot_number=self.config.bot_number,
            binary=self.config.signal_cli_bin,
        )
        self.limiter = limiter or RateLimiter()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.binary_exists = binary_exists or _binary_exists

    def is_configured(self) -> bool:
        return (
            bool(self.config.bot_number.strip())
            and bool(self.config.user_number.strip())
            and self.binary_exists(self.config.signal_cli_bin)
        )

    def send(
        self,
        message: str,
        recipient: str | None = None,
        *,
        priority: bool = False,
    ) -> SignalSendResult:
        if not message.strip():
            return SignalSendResult(False, "empty-message")
        if not self.is_configured():
            return SignalSendResult(False, "not-configured")

        now = self.clock()
        if not priority and _in_quiet_hours(
            now,
            start_hour=self.config.quiet_start_hour,
            end_hour=self.config.quiet_end_hour,
        ):
            return SignalSendResult(False, "quiet-hours")
        if not priority and not self.limiter.under_cap(
            now,
            hourly_cap=self.config.hourly_cap,
            daily_cap=self.config.daily_cap,
        ):
            return SignalSendResult(False, "rate-capped")

        target = recipient or self.config.user_number
        if not target.strip():
            return SignalSendResult(False, "not-configured")
        if not self.provider.send(message, target):
            return SignalSendResult(False, "provider-failed")
        self.limiter.record(now)
        return SignalSendResult(True, "sent")


def config_from_env(env: dict[str, str] | None = None) -> SignalConfig:
    env = env or os.environ
    return SignalConfig(
        bot_number=env.get("SIGNAL_BOT_NUMBER", ""),
        user_number=env.get("SIGNAL_USER_NUMBER", ""),
        signal_cli_bin=env.get("SIGNAL_CLI_BIN", "/usr/local/bin/signal-cli"),
        hourly_cap=int(env.get("SIGNAL_HOURLY_CAP", "6")),
        daily_cap=int(env.get("SIGNAL_DAILY_CAP", "30")),
        quiet_start_hour=int(env.get("SIGNAL_QUIET_START_HOUR", "23")),
        quiet_end_hour=int(env.get("SIGNAL_QUIET_END_HOUR", "7")),
    )


_DEFAULT_LIMITER = RateLimiter()


def is_configured() -> bool:
    return SignalSender(limiter=_DEFAULT_LIMITER).is_configured()


def send(message: str, recipient: str | None = None, *, priority: bool = False) -> SignalSendResult:
    return SignalSender(limiter=_DEFAULT_LIMITER).send(message, recipient, priority=priority)


def _binary_exists(path: str) -> bool:
    candidate = Path(path)
    return candidate.is_file() and os.access(candidate, os.X_OK)


def _in_quiet_hours(now: datetime, *, start_hour: int, end_hour: int) -> bool:
    hour = now.hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour
