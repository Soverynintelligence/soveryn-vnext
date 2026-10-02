"""SOVERYN core must boot and chat when CWG/ledger modules are absent."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from flask import Flask

from soveryn.agents.loop import AgentLoop
from soveryn.app.startup import create_app
from soveryn.config.runtime import ACTIVE_AGENTS
from soveryn.inference.llama_server_client import ChatResponse, StreamChunk
from soveryn.memory.conversation_store import ConversationStore
from soveryn.memory.lattice import LatticeStore
from tests.helpers.hermetic import isolate_data_root

_CWG_MODULES = (
    "soveryn.platform.pondwright.lead_watch",
    "soveryn.platform.ledgers.tools",
    "soveryn.platform.ledgers.auto",
)


class _FakeChat:
    def __init__(self, *, content="hello back"):
        self.calls: list[dict] = []
        self.content = content

    def __call__(self, request, server, timeout=60.0):
        self.calls.append({"request": request, "server": server})
        return ChatResponse(
            content=self.content,
            finish_reason="stop",
            tool_calls=None,
            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            raw={},
        )


class _StreamFn:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, request, server, timeout=120.0):
        self.calls.append({"request": request, "server": server})

        def _g():
            yield StreamChunk(delta="ok", finish_reason=None, tool_calls_delta=None, usage=None, raw={})
            yield StreamChunk(delta="", finish_reason="stop", tool_calls_delta=None, usage=None, raw={})

        return _g()


@pytest.fixture(autouse=True)
def _hermetic_data_root(tmp_path, monkeypatch):
    isolate_data_root(tmp_path, monkeypatch)


@pytest.fixture
def fake_souls_dir(tmp_path) -> Path:
    souls_dir = tmp_path / "souls"
    souls_dir.mkdir()
    for agent in ACTIVE_AGENTS:
        (souls_dir / f"{agent}.md").write_text(f"# {agent}\n", encoding="utf-8")
    return souls_dir


@pytest.fixture
def fake_pinned(tmp_path) -> Path:
    pinned = tmp_path / "pinned.md"
    pinned.write_text("# Pinned relationship substrate\n", encoding="utf-8")
    return pinned


@pytest.fixture
def recall_lattice_path(tmp_path) -> Path:
    store = LatticeStore(tmp_path / "recall_lattice.db")
    store.write_node(
        "aetheria",
        "core-without-cwg fixture memory",
        provenance={
            "cls": "witnessed",
            "source": "test",
            "confidence": 0.9,
            "temporal_context": "fixture",
            "generator": "test",
        },
    )
    return tmp_path / "recall_lattice.db"


def test_core_without_cwg_lookups_stay_under_tmp_path(tmp_path):
    from soveryn.agents.personas import persona_override_path
    from soveryn.config.loader import load_env_config

    tmp = tmp_path.resolve()
    cfg = load_env_config()
    assert cfg.data_root.resolve().is_relative_to(tmp)
    assert cfg.skills_dir.resolve().is_relative_to(tmp)
    assert persona_override_path("eve").resolve().is_relative_to(tmp)


def _hide_cwg_modules(monkeypatch) -> None:
    for name in _CWG_MODULES:
        monkeypatch.setitem(sys.modules, name, None)


def _disable_non_lead_workers(monkeypatch) -> None:
    """Keep lead-watch default-ON (import is hidden). Skip other daemons."""
    original_init = Flask.__init__

    def _init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.config["SOVERYN_START_MESSENGER_WORKER"] = False
        self.config["SOVERYN_START_DELEGATION_WORKER"] = False
        self.config["SOVERYN_START_CITIZENS_WORKER"] = False

    monkeypatch.setattr(Flask, "__init__", _init)


def _configure_env(monkeypatch, *, tmp_path, fake_souls_dir, fake_pinned, recall_lattice_path) -> None:
    monkeypatch.setenv("SOVERYN_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setenv("SOVERYN_SOULS_DIR", str(fake_souls_dir))
    monkeypatch.setenv("SOVERYN_PINNED_MEMORY_PATH", str(fake_pinned))
    monkeypatch.setenv("SOVERYN_RECALL_LATTICE_DB", str(recall_lattice_path))
    monkeypatch.setenv("SOVERYN_LATTICE_DB", str(recall_lattice_path))


def _apply_plugin_boot_mode(mode: str, monkeypatch) -> None:
    """SOVERYN_PLUGINS / builtin-failure cases the step-2a boot test must survive."""
    from soveryn.plugins.loader import reset_plugins

    if mode == "unset":
        monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)
    elif mode == "cwg_external_missing":
        monkeypatch.setenv("SOVERYN_PLUGINS", "cwg")
        monkeypatch.setattr(
            "soveryn.plugins.loader._external_entry_points",
            lambda: [],
        )
    elif mode == "register_raises":
        monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)

        def _boom(self, ctx, connector_id, owner):
            raise RuntimeError("register boom")

        monkeypatch.setattr(
            "soveryn.plugins.builtin_cwg.BuiltinCwgPlugin.register",
            _boom,
        )
    elif mode == "fragments_raises":
        monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)

        def _boom(self, agent):
            raise RuntimeError("fragments boom")

        monkeypatch.setattr(
            "soveryn.plugins.builtin_cwg.BuiltinCwgPlugin.prompt_fragments",
            _boom,
        )
    elif mode == "workers_raises":
        monkeypatch.delenv("SOVERYN_PLUGINS", raising=False)

        def _boom(self, app):
            raise RuntimeError("workers boom")

        monkeypatch.setattr(
            "soveryn.plugins.builtin_cwg.BuiltinCwgPlugin.background_workers",
            _boom,
        )
    else:
        raise AssertionError(f"unknown plugin boot mode {mode!r}")
    reset_plugins()


def _post(client, path, body):
    return client.post(path, data=json.dumps(body), content_type="application/json")


@pytest.mark.parametrize(
    "plugin_boot_mode",
    ("unset", "cwg_external_missing", "register_raises", "workers_raises", "fragments_raises"),
)
def test_create_app_and_chat_survive_missing_cwg(
    tmp_path,
    monkeypatch,
    fake_souls_dir,
    fake_pinned,
    recall_lattice_path,
    plugin_boot_mode,
):
    """create_app succeeds and image chat turns do not 500 when CWG is gone."""
    _apply_plugin_boot_mode(plugin_boot_mode, monkeypatch)
    _hide_cwg_modules(monkeypatch)
    _disable_non_lead_workers(monkeypatch)
    _configure_env(
        monkeypatch,
        tmp_path=tmp_path,
        fake_souls_dir=fake_souls_dir,
        fake_pinned=fake_pinned,
        recall_lattice_path=recall_lattice_path,
    )

    conv = ConversationStore(tmp_path / "conv.db")
    app = create_app(conv_store=conv)
    assert app is not None

    fake_chat = _FakeChat()
    stream = _StreamFn()
    loops = {
        name: AgentLoop(name, conv, chat_fn=fake_chat, stream_fn=stream)
        for name in ACTIVE_AGENTS
    }
    app.extensions["soveryn"]["agent_loops"] = loops
    app.config["SOVERYN_REQUIRE_LOCALHOST"] = False
    client = app.test_client()

    img = "data:image/jpeg;base64,AAAA"
    create = _post(client, "/sessions", {"agent": "aetheria"})
    assert create.status_code == 201
    sid = json.loads(create.data)["session_id"]

    chat = _post(
        client,
        "/chat",
        {
            "agent": "aetheria",
            "session_id": sid,
            "message": "what's this?",
            "attachments": [img],
        },
    )
    assert chat.status_code == 200, chat.data

    stream_create = _post(client, "/sessions", {"agent": "aetheria"})
    assert stream_create.status_code == 201
    stream_sid = json.loads(stream_create.data)["session_id"]
    streamed = _post(
        client,
        "/chat_stream",
        {
            "agent": "aetheria",
            "session_id": stream_sid,
            "message": "what's this?",
            "attachments": [img],
        },
    )
    assert streamed.status_code == 200, streamed.data


def test_chat_receipt_hook_swallows_import_and_raise(monkeypatch):
    """Missing or raising apply_chat_receipt must return the original message."""
    from soveryn.app.routes.chat import ChatReceiptHook

    monkeypatch.setitem(sys.modules, "soveryn.platform.ledgers.auto", None)
    assert ChatReceiptHook.apply("keep me", ("data:image/jpeg;base64,AAAA",)) == "keep me"

    class _Boom:
        @staticmethod
        def apply_chat_receipt(message, images):
            raise RuntimeError("ledger boom")

    monkeypatch.setitem(sys.modules, "soveryn.platform.ledgers.auto", _Boom)
    assert ChatReceiptHook.apply("keep me", ("data:image/jpeg;base64,AAAA",)) == "keep me"
