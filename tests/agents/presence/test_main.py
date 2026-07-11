"""Tests for the presence daemon launcher (soveryn/agents/presence/__main__.py).

Mirrors tests/test_ares_launcher.py in spirit: parse_args is pure argparse
plumbing (fast, no I/O); build_daemon is exercised with every real I/O
dependency (XClient.from_env, AgentLoop, ConversationStore path,
PresenceConfig.default's on-disk paths, SignalSender) monkeypatched to a
fake, so the test never touches the network, a model server, or Jon's real
home-directory data files.
"""

from __future__ import annotations

import signal

import pytest

import soveryn.agents.presence.__main__ as launch
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.daemon import PresenceDaemonSurface
from soveryn.agents.presence.pending_store import PendingStore


def test_parse_args_defaults():
    args = launch.parse_args([])
    assert args == launch.LauncherArgs()
    assert args.dry_run is False
    assert args.interval_seconds == launch.DEFAULT_INTERVAL_SECONDS
    assert args.iterations is None


def test_parse_args_dry_run_flag():
    args = launch.parse_args(["--iterations", "1", "--dry-run"])
    assert args.dry_run is True
    assert args.iterations == 1


def test_parse_args_interval_seconds_override():
    args = launch.parse_args(["--interval-seconds", "12.5"])
    assert args == launch.LauncherArgs(interval_seconds=12.5)


def test_parse_args_rejects_nonpositive_interval_seconds():
    for value in ["0", "-1", "-3.5"]:
        with pytest.raises(SystemExit):
            launch.parse_args(["--interval-seconds", value])


def test_parse_args_rejects_nonpositive_iterations():
    for value in ["0", "-2"]:
        with pytest.raises(SystemExit):
            launch.parse_args(["--iterations", value])


# ─── build_daemon ───────────────────────────────────────────────────────────


class FakeXClient:
    @classmethod
    def from_env(cls, http=None):
        return cls()


class FakeAgentLoop:
    def __init__(self, agent_name, conv_store, **kwargs):
        self.agent_name = agent_name
        self.conv_store = conv_store
        self.kwargs = kwargs

    def process_message(self, session_id, message):  # pragma: no cover - unused in build test
        raise AssertionError("build_daemon must not invoke process_message")


class FakeEnvConfig:
    def __init__(self, tmp_path):
        self.conversations_db = tmp_path / "conversations.db"
        self.pinned_memory_path = tmp_path / "pinned_memory.md"


@pytest.fixture
def patched_build(monkeypatch, tmp_path):
    """Monkeypatch every real I/O dependency build_daemon touches."""
    monkeypatch.setattr(launch, "XClient", FakeXClient)
    monkeypatch.setattr(launch, "AgentLoop", FakeAgentLoop)
    monkeypatch.setattr(launch, "load_env_config", lambda: FakeEnvConfig(tmp_path))

    fake_cfg = PresenceConfig(
        niche_terms=("sovereign AI",),
        own_handle="Soveryn_AI",
        score_threshold=2.0,
        max_drafts_per_scan=3,
        poll_interval_seconds=300.0,
        db_path=tmp_path / "candidates.db",
        signal_log_path=tmp_path / "signal_log.db",
        pending_db_path=tmp_path / "pending.db",
    )
    monkeypatch.setattr(PresenceConfig, "default", classmethod(lambda cls: fake_cfg))

    sent: list[str] = []

    class FakeSignalSender:
        def __init__(self, *a, **kw):
            pass

        def send(self, message, recipient=None, *, priority=False):
            sent.append(message)
            from soveryn.agents.ares.signal_sender import SignalSendResult
            return SignalSendResult(True, "sent")

    monkeypatch.setattr(launch, "SignalSender", FakeSignalSender)
    return sent


def test_build_daemon_returns_presence_daemon_surface(patched_build):
    daemon = launch.build_daemon(launch.LauncherArgs())
    assert isinstance(daemon, PresenceDaemonSurface)
    assert isinstance(daemon.x_client, FakeXClient)
    assert isinstance(daemon.pending_store, PendingStore)


def test_build_daemon_real_send_uses_signal_sender(patched_build):
    sent = patched_build
    daemon = launch.build_daemon(launch.LauncherArgs(dry_run=False))
    daemon.send_fn("hello jon")
    assert sent == ["hello jon"]


def test_build_daemon_dry_run_does_not_touch_signal(patched_build, capsys):
    sent = patched_build
    daemon = launch.build_daemon(launch.LauncherArgs(dry_run=True))
    daemon.send_fn("hello jon")
    assert sent == []
    out = capsys.readouterr().out
    assert "hello jon" in out


def test_install_signal_handlers_wires_sigterm_and_sigint(monkeypatch):
    calls: list[tuple[int, object]] = []

    def fake_signal(signum, handler):
        calls.append((signum, handler))
        return None

    monkeypatch.setattr(launch.signal, "signal", fake_signal)
    shutdown = launch._ShutdownRequest()

    launch._install_signal_handlers(shutdown)

    assert calls == [
        (signal.SIGTERM, shutdown.request),
        (signal.SIGINT, shutdown.request),
    ]


def test_run_passes_control_knobs_and_stop_callback():
    captured: dict[str, object] = {}
    signal_state: dict[str, launch._ShutdownRequest] = {}

    class FakeDaemon:
        def run_forever(self, *, interval_seconds, iterations, stop_requested):
            captured["interval_seconds"] = interval_seconds
            captured["iterations"] = iterations
            captured["stop_requested_before"] = stop_requested()
            signal_state["shutdown"].request(signal.SIGTERM, None)
            captured["stop_requested_after"] = stop_requested()

    def daemon_factory(args):
        captured["args"] = args
        return FakeDaemon()

    def signal_installer(shutdown):
        signal_state["shutdown"] = shutdown

    rc = launch.run(
        launch.LauncherArgs(dry_run=True, interval_seconds=7.5, iterations=3),
        daemon_factory=daemon_factory,
        signal_installer=signal_installer,
    )

    assert rc == 0
    assert captured["args"] == launch.LauncherArgs(dry_run=True, interval_seconds=7.5, iterations=3)
    assert captured["interval_seconds"] == 7.5
    assert captured["iterations"] == 3
    assert captured["stop_requested_before"] is False
    assert captured["stop_requested_after"] is True


def test_main_parses_argv_and_returns_zero():
    captured: dict[str, object] = {}

    class FakeDaemon:
        def run_forever(self, *, interval_seconds, iterations, stop_requested):
            captured["interval_seconds"] = interval_seconds
            captured["iterations"] = iterations
            captured["stop_requested"] = stop_requested()

    def daemon_factory(args):
        captured["args"] = args
        return FakeDaemon()

    rc = launch.main(
        ["--dry-run", "--interval-seconds", "5", "--iterations", "2"],
        daemon_factory=daemon_factory,
        signal_installer=lambda shutdown: None,
    )

    assert rc == 0
    assert captured["args"] == launch.LauncherArgs(dry_run=True, interval_seconds=5.0, iterations=2)
    assert captured["interval_seconds"] == 5.0
    assert captured["iterations"] == 2
    assert captured["stop_requested"] is False


# ─── inbound reply seam ─────────────────────────────────────────────────────


from soveryn.agents.presence.drafting import Draft
from soveryn.agents.presence.publisher import PublishResult


class _StubXClient:
    def create_tweet(self, text):
        return "posted-1"


class _FailingXClient:
    def create_tweet(self, text):
        from soveryn.agents.presence.x_client import XClientError
        raise XClientError("X API 500: server error")


def _make_daemon(tmp_path, x_client):
    from soveryn.agents.presence.candidate_store import CandidateStore
    from soveryn.agents.presence.pending_store import PendingStore
    from soveryn.agents.presence.signal_log import SignalLog

    store = CandidateStore(tmp_path / "cand.db")
    signal_log = SignalLog(tmp_path / "sig.db")
    pending_store = PendingStore(tmp_path / "pending.db")
    sent: list[str] = []
    daemon = PresenceDaemonSurface(
        cfg=PresenceConfig(
            niche_terms=(), own_handle="Soveryn_AI", score_threshold=2.0,
            max_drafts_per_scan=3, poll_interval_seconds=300.0,
            db_path=tmp_path / "cand.db", signal_log_path=tmp_path / "sig.db",
            pending_db_path=tmp_path / "pending.db",
        ),
        x_client=x_client,
        store=store,
        draft_fn=lambda prompt: "unused",
        send_fn=sent.append,
        signal_log=signal_log,
        pending_store=pending_store,
    )
    draft = Draft(
        candidate_tweet_id="tid1", kind="topic",
        text="a post", based_on="(none stated)", in_reply_to=None,
    )
    pending_store.put_draft("tid1", draft)
    return daemon, sent


def test_handle_inbound_reply_resolves_pending_draft(tmp_path):
    from soveryn.agents.presence.inbound import handle_inbound_reply

    daemon, sent = _make_daemon(tmp_path, _StubXClient())
    handled = handle_inbound_reply(daemon, "tid1 y")

    assert handled is True
    assert daemon.pending_store.get_draft("tid1") is None


def test_handle_inbound_reply_ignores_unmatched_text(tmp_path):
    from soveryn.agents.presence.inbound import handle_inbound_reply

    daemon, sent = _make_daemon(tmp_path, _StubXClient())
    handled = handle_inbound_reply(daemon, "just chatting, not a draft reply")

    assert handled is False
    assert daemon.pending_store.get_draft("tid1") is not None
    assert sent == []


def test_handle_inbound_reply_surfaces_publish_failure(tmp_path):
    from soveryn.agents.presence.inbound import handle_inbound_reply

    daemon, sent = _make_daemon(tmp_path, _FailingXClient())
    handled = handle_inbound_reply(daemon, "tid1 y")

    assert handled is True
    assert len(sent) == 1
    assert "tid1" in sent[0]
    assert "FAILED" in sent[0]
