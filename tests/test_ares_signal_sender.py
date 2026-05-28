"""Tests for Ares outbound Signal sender."""

from __future__ import annotations

from datetime import datetime, timezone

from soveryn.agents.ares.signal_sender import (
    RateLimiter,
    SignalConfig,
    SignalCliProvider,
    SignalSendResult,
    SignalSender,
)


class FakeProvider:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, str]] = []

    def send(self, message: str, recipient: str) -> bool:
        self.calls.append((message, recipient))
        return self.ok


def _config(**overrides) -> SignalConfig:
    values = {
        "bot_number": "+15550000001",
        "user_number": "+15550000002",
        "signal_cli_bin": "/tmp/signal-cli",
        "hourly_cap": 6,
        "daily_cap": 30,
        "quiet_start_hour": 23,
        "quiet_end_hour": 7,
    }
    values.update(overrides)
    return SignalConfig(**values)


def _sender(
    *,
    provider: FakeProvider | None = None,
    limiter: RateLimiter | None = None,
    now: datetime | None = None,
    config: SignalConfig | None = None,
) -> SignalSender:
    return SignalSender(
        config=config or _config(),
        provider=provider or FakeProvider(),
        limiter=limiter or RateLimiter(),
        clock=lambda: now or datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
        binary_exists=lambda path: True,
    )


def test_nonpriority_send_during_normal_hours_under_cap_sends():
    provider = FakeProvider()
    sender = _sender(provider=provider)

    result = sender.send("Ares warning", priority=False)

    assert result == SignalSendResult(sent=True, reason="sent")
    assert provider.calls == [("Ares warning", "+15550000002")]


def test_nonpriority_send_over_hourly_cap_is_suppressed():
    provider = FakeProvider()
    limiter = RateLimiter()
    now = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
    for _ in range(6):
        limiter.record(now)
    sender = _sender(provider=provider, limiter=limiter, now=now)

    result = sender.send("Ares warning", priority=False)

    assert result == SignalSendResult(sent=False, reason="rate-capped")
    assert provider.calls == []


def test_nonpriority_send_over_daily_cap_is_suppressed():
    provider = FakeProvider()
    limiter = RateLimiter()
    now = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
    config = _config(hourly_cap=100, daily_cap=30)
    for _ in range(30):
        limiter.record(now)
    sender = _sender(provider=provider, limiter=limiter, now=now, config=config)

    result = sender.send("Ares warning", priority=False)

    assert result == SignalSendResult(sent=False, reason="rate-capped")
    assert provider.calls == []


def test_nonpriority_send_during_quiet_hours_is_suppressed():
    provider = FakeProvider()
    sender = _sender(
        provider=provider,
        now=datetime(2026, 5, 29, 23, 30, tzinfo=timezone.utc),
    )

    result = sender.send("Ares warning", priority=False)

    assert result == SignalSendResult(sent=False, reason="quiet-hours")
    assert provider.calls == []


def test_priority_send_bypasses_caps_and_quiet_hours():
    provider = FakeProvider()
    limiter = RateLimiter()
    now = datetime(2026, 5, 29, 23, 30, tzinfo=timezone.utc)
    for _ in range(30):
        limiter.record(now)
    sender = _sender(provider=provider, limiter=limiter, now=now)

    result = sender.send("Ares emergency", priority=True)

    assert result == SignalSendResult(sent=True, reason="sent")
    assert provider.calls == [("Ares emergency", "+15550000002")]


def test_unconfigured_sender_does_not_send():
    provider = FakeProvider()
    sender = _sender(provider=provider, config=_config(bot_number=""))

    result = sender.send("Ares warning")

    assert result == SignalSendResult(sent=False, reason="not-configured")
    assert provider.calls == []


def test_is_configured_reflects_numbers_and_binary():
    sender = SignalSender(
        config=_config(),
        provider=FakeProvider(),
        limiter=RateLimiter(),
        binary_exists=lambda path: path == "/tmp/signal-cli",
    )
    missing_binary = SignalSender(
        config=_config(),
        provider=FakeProvider(),
        limiter=RateLimiter(),
        binary_exists=lambda path: False,
    )
    missing_number = SignalSender(
        config=_config(user_number=""),
        provider=FakeProvider(),
        limiter=RateLimiter(),
        binary_exists=lambda path: True,
    )

    assert sender.is_configured() is True
    assert missing_binary.is_configured() is False
    assert missing_number.is_configured() is False


def test_provider_failure_returns_failed_result():
    provider = FakeProvider(ok=False)
    sender = _sender(provider=provider)

    result = sender.send("Ares warning")

    assert result == SignalSendResult(sent=False, reason="provider-failed")
    assert provider.calls == [("Ares warning", "+15550000002")]


def test_signal_cli_provider_uses_expected_send_command(monkeypatch):
    calls = []

    class Completed:
        returncode = 0

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Completed()

    monkeypatch.setattr("soveryn.agents.ares.signal_sender.subprocess.run", fake_run)
    provider = SignalCliProvider(bot_number="+15550000001", binary="/usr/bin/signal-cli")

    assert provider.send("Ares warning", "+15550000002") is True
    assert calls == [(
        ["/usr/bin/signal-cli", "-a", "+15550000001", "send", "-m", "Ares warning", "+15550000002"],
        {"capture_output": True, "text": True, "timeout": 20},
    )]


def test_signal_cli_provider_returns_false_on_nonzero_exit(monkeypatch):
    class Completed:
        returncode = 1

    monkeypatch.setattr(
        "soveryn.agents.ares.signal_sender.subprocess.run",
        lambda cmd, **kwargs: Completed(),
    )
    provider = SignalCliProvider(bot_number="+15550000001", binary="/usr/bin/signal-cli")

    assert provider.send("Ares warning", "+15550000002") is False
