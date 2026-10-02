"""Shared pytest fixtures for the SOVERYN vNext test suite."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse
from soveryn.memory.conversation_store import ConversationStore


def _block_live_webpush(*args, **kwargs):
    """Stand-in for pywebpush.webpush — never opens a socket."""
    raise RuntimeError("webpush network send blocked during tests")


@pytest.fixture(scope="session", autouse=True)
def _session_block_live_webpush_and_signal_lock(tmp_path_factory):
    """Process-wide guard so leftover daemon threads cannot hit live endpoints
    or the house signal-cli flock between tests.

    Function-scoped fixtures below overlay per-test temp paths on top of these.
    We do not install a global socket blocker — that breaks tests that talk to
    localhost / the router. pywebpush.webpush is the only Web Push hop.
    """
    import pywebpush
    from soveryn.agents.signal_bridge import client as client_mod

    root = tmp_path_factory.mktemp("session-isolation")
    prev_db = os.environ.get("SOVERYN_WEBPUSH_DB")
    prev_vapid = os.environ.get("SOVERYN_VAPID_KEYS_PATH")
    prev_lead = os.environ.get("SOVERYN_LEAD_WATCH_STATE")
    os.environ["SOVERYN_WEBPUSH_DB"] = str(root / "webpush.db")
    os.environ["SOVERYN_VAPID_KEYS_PATH"] = str(root / "vapid_keys.json")
    os.environ["SOVERYN_LEAD_WATCH_STATE"] = str(root / "lead_watch.json")

    orig_webpush = pywebpush.webpush
    pywebpush.webpush = _block_live_webpush
    orig_lock = client_mod._SIGNAL_CLI_LOCK_PATH
    client_mod._SIGNAL_CLI_LOCK_PATH = root / "signal-cli.lock"
    try:
        yield
    finally:
        pywebpush.webpush = orig_webpush
        client_mod._SIGNAL_CLI_LOCK_PATH = orig_lock
        _restore_env("SOVERYN_WEBPUSH_DB", prev_db)
        _restore_env("SOVERYN_VAPID_KEYS_PATH", prev_vapid)
        _restore_env("SOVERYN_LEAD_WATCH_STATE", prev_lead)


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


@dataclass
class WebPushNetworkGuard:
    """Records intercepted pywebpush.webpush calls for the current test."""

    calls: list[dict] = field(default_factory=list)


@pytest.fixture(autouse=True)
def webpush_network_guard(tmp_path, monkeypatch):
    """Per-test temp data root + recording stub for the Web Push send.

    ApprovalBroker.request, lead_watch, notify_needs_you / notify_pondwright_lead
    / notify_lead all funnel into pywebpush.webpush. Without this, a default
    pytest run on a machine with a live ``data/memory/webpush.db`` will send
    real pushes (rejected 400 VapidPkHashMismatch on Jon's tower).
    """
    data_root = tmp_path / "isolated-data-root"
    data_root.mkdir()
    monkeypatch.setenv("SOVERYN_WEBPUSH_DB", str(data_root / "memory" / "webpush.db"))
    monkeypatch.setenv(
        "SOVERYN_VAPID_KEYS_PATH", str(data_root / "memory" / "vapid_keys.json")
    )
    monkeypatch.setenv(
        "SOVERYN_LEAD_WATCH_STATE",
        str(data_root / "memory" / "pondwright_lead_watch.json"),
    )

    guard = WebPushNetworkGuard()

    def _record_and_block(*args, **kwargs):
        guard.calls.append({"args": args, "kwargs": kwargs})
        raise RuntimeError("webpush network send blocked during tests")

    import pywebpush

    monkeypatch.setattr(pywebpush, "webpush", _record_and_block)
    yield guard


@pytest.fixture(autouse=True)
def _isolate_signal_cli_lock_and_limiter(tmp_path, monkeypatch):
    """Keep signal-cli's process flock and Ares' module limiter off shared state.

    ``SignalCliProvider.send`` acquires ``_SIGNAL_CLI_LOCK_PATH`` (import-time
    ``Path.home()/.../.soveryn-serialize.lock``). Tests that call send_once
    without redirecting that path, leftover threads, or a live signal-bridge
    daemon on the tower all serialize on the same file. The Ares provider test
    also used to patch ``subprocess.run`` on the shared stdlib module, so a
    concurrent ``subprocess.run`` from another test's daemon thread polluted
    its call log. Lock path is isolated here; the provider test patches a
    private subprocess stand-in.
    """
    from soveryn.agents.ares import signal_sender as sender_mod
    from soveryn.agents.ares.signal_sender import RateLimiter
    from soveryn.agents.signal_bridge import client as client_mod

    monkeypatch.setattr(
        client_mod, "_SIGNAL_CLI_LOCK_PATH", tmp_path / "signal-cli.lock"
    )
    sender_mod._DEFAULT_LIMITER = RateLimiter()
    yield
    sender_mod._DEFAULT_LIMITER = RateLimiter()


@pytest.fixture(autouse=True)
def _isolate_acttruth_and_skills(tmp_path, monkeypatch):
    """AgentLoop unit tests must not ingest the live house ActTruth ledger
    or on-disk skill index — that leaked extra system messages and made
    prelude-count assertions fail outside this machine."""
    iso = tmp_path / ".acttruth-test"
    monkeypatch.setenv("ACTTRUTH_DIR", str(iso))
    from soveryn.platform.acttruth.hooks import reset_acttruth_cache
    from soveryn.platform.acttruth.paths import set_default_root

    set_default_root(iso)
    reset_acttruth_cache()
    from soveryn.agents.skills import get_skill_index as _real_index

    def _index(agent, skills_dir=None):
        if skills_dir is None:
            return ""
        return _real_index(agent, skills_dir=skills_dir)

    monkeypatch.setattr("soveryn.agents.loop.get_skill_index", _index)
    monkeypatch.setattr("soveryn.agents.skills.get_skill_index", _index)


@pytest.fixture
def fake_chat():
    return lambda req, server, timeout=60: ChatResponse(
        content="ok", finish_reason="stop", tool_calls=None, usage=None, raw={})


@pytest.fixture
def app_state(tmp_path, fake_chat):
    conv = ConversationStore(tmp_path / "conv.db")
    loops = {n: AgentLoop(n, conv, chat_fn=fake_chat) for n in ACTIVE_AGENTS}
    app = create_app(conv_store=conv, agent_loops=loops)
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    return app.test_client()
