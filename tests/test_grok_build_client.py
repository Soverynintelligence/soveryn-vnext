"""Unit tests for Messages Grok Build backend (no live grok spawn)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from soveryn.config.runtime import ModelServer, MODEL_ROOT
from soveryn.platform.inference.grok_build_client import (
    format_messages_for_prompt,
    grok_chat,
    grok_chat_stream,
    run_grok_prompt,
    _parse_grok_json,
)
from soveryn.platform.inference.llama_server_client import (
    ChatMessage,
    ChatRequest,
    LlamaServerError,
    LlamaServerTimeout,
)


def _server() -> ModelServer:
    return ModelServer(
        name="grok_build",
        port=5099,
        model_path=MODEL_ROOT / ".grok_build_external",
        model_alias="grok-build",
        skip_preflight=True,
    )


def test_parse_grok_json_plain_object():
    raw = json.dumps({"text": "pong", "stopReason": "end_turn"})
    assert _parse_grok_json(raw) == "pong"


def test_parse_grok_json_falls_back_to_text():
    assert _parse_grok_json("just text") == "just text"


def test_format_messages_includes_roles():
    req = ChatRequest(
        messages=(
            ChatMessage(role="system", content="Be brief."),
            ChatMessage(role="user", content="list files"),
        ),
        model="grok-build",
    )
    prompt = format_messages_for_prompt(req)
    assert "[system]" in prompt
    assert "Be brief." in prompt
    assert "[user]" in prompt
    assert "list files" in prompt


def test_run_grok_prompt_success(monkeypatch, tmp_path):
    bin_path = tmp_path / "grok"
    bin_path.write_text("#!/bin/sh\n", encoding="utf-8")
    bin_path.chmod(0o755)
    work = tmp_path / "cwd"
    work.mkdir()

    completed = MagicMock()
    completed.returncode = 0
    completed.stdout = json.dumps({"text": "done"})
    completed.stderr = ""
    runner = MagicMock(return_value=completed)
    monkeypatch.setattr(
        "soveryn.platform.inference.grok_build_client.subprocess.run",
        runner,
    )

    out = run_grok_prompt("hi", cwd=work, bin_path=bin_path, timeout=30)
    assert out == "done"
    cmd = runner.call_args.args[0]
    assert cmd[0] == str(bin_path)
    assert "-p" in cmd
    assert "--permission-mode" in cmd
    assert "acceptEdits" in cmd


def test_run_grok_prompt_timeout(monkeypatch, tmp_path):
    bin_path = tmp_path / "grok"
    bin_path.write_text("x", encoding="utf-8")
    work = tmp_path / "cwd"
    work.mkdir()

    import subprocess as sp

    def boom(*_a, **_k):
        raise sp.TimeoutExpired(cmd="grok", timeout=1)

    monkeypatch.setattr(
        "soveryn.platform.inference.grok_build_client.subprocess.run",
        boom,
    )
    with pytest.raises(LlamaServerTimeout):
        run_grok_prompt("hi", cwd=work, bin_path=bin_path, timeout=1)


def test_run_grok_prompt_missing_binary(tmp_path):
    with pytest.raises(LlamaServerError) as ei:
        run_grok_prompt("hi", cwd=tmp_path, bin_path=tmp_path / "missing")
    assert ei.value.status_code == 503


def test_grok_chat_and_stream(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "soveryn.platform.inference.grok_build_client.run_grok_prompt",
        lambda *_a, **_k: "hello from grok",
    )
    req = ChatRequest(
        messages=(ChatMessage(role="user", content="hi"),),
        model="grok-build",
    )
    resp = grok_chat(req, _server(), timeout=10)
    assert resp.content == "hello from grok"
    assert resp.finish_reason == "stop"

    chunks = list(grok_chat_stream(req, _server(), timeout=10))
    assert len(chunks) == 1
    assert chunks[0].delta == "hello from grok"
    assert chunks[0].finish_reason == "stop"
