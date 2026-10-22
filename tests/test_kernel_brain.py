"""Kernel brain resolve + verified health check (deepseek / unknown / endpoint)."""

from __future__ import annotations

import logging
import urllib.error
from unittest.mock import patch

from soveryn.config import runtime
from soveryn.inference.health import (
    check_kernel_brain,
    format_kernel_brain_health_block,
    kernel_brain_health_report,
)
from soveryn.platform.surfaces.registry import kernel_build_surface


class _FakeHTTPResponse:
    def __init__(self, status: int = 200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_resolve_deepseek_gives_spark2_8888(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    assert runtime.resolve_kernel_brain() == "deepseek"
    server = runtime._kernel_server()
    assert server.name == "kernel_build"
    assert server.host == "10.10.10.2"
    assert server.port == 8888
    assert server.model_alias == "DeepSeek-V4.1-Flash-1017"
    rec = runtime.describe_kernel_brain()
    assert rec["brain"] == "deepseek"
    assert rec["base_url"] == "http://10.10.10.2:8888"
    assert rec["port"] == 8888
    assert rec["alias"] == "DeepSeek-V4.1-Flash-1017"


def test_unknown_kernel_brain_warns_and_falls_back_to_flash(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "kernel_brain"
    path.write_text("not-a-real-brain\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", path)
    monkeypatch.delenv("SOVERYN_KERNEL_BRAIN", raising=False)
    with caplog.at_level(logging.WARNING, logger="soveryn.config.runtime"):
        assert runtime.resolve_kernel_brain() == "flash"
    assert "not-a-real-brain" in caplog.text
    assert "unknown kernel brain" in caplog.text
    assert "falling back to flash" in caplog.text


def test_unknown_env_brain_warns_then_uses_known_file(
    tmp_path, monkeypatch, caplog
):
    path = tmp_path / "kernel_brain"
    path.write_text("deepseek\n", encoding="utf-8")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", path)
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "mystery")
    with caplog.at_level(logging.WARNING, logger="soveryn.config.runtime"):
        assert runtime.resolve_kernel_brain() == "deepseek"
    assert "mystery" in caplog.text
    assert "SOVERYN_KERNEL_BRAIN" in caplog.text


def test_check_kernel_brain_uses_resolved_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    seen: list[str] = []

    def fake_urlopen(url, timeout=None):
        seen.append(url if isinstance(url, str) else str(url))
        return _FakeHTTPResponse(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = check_kernel_brain(timeout=1.0)
    assert result.status == "ok"
    assert result.name == "kernel_build"
    assert seen
    assert all("10.10.10.2:8888" in u for u in seen)
    assert all("8080" not in u for u in seen)
    assert seen[0] == "http://10.10.10.2:8888/health"


def test_check_kernel_brain_falls_back_to_v1_models(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    seen: list[str] = []

    def fake_urlopen(url, timeout=None):
        seen.append(url)
        if str(url).endswith("/health"):
            raise urllib.error.URLError("no /health")
        return _FakeHTTPResponse(200)

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        result = check_kernel_brain(timeout=1.0)
    assert result.status == "ok"
    assert seen == [
        "http://10.10.10.2:8888/health",
        "http://10.10.10.2:8888/v1/models",
    ]
    assert all("8080" not in u for u in seen)


def test_kernel_brain_health_report_and_prompt_block(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(200)):
        report = kernel_brain_health_report(timeout=1.0)
        block = format_kernel_brain_health_block(timeout=1.0)
    assert report["brain"] == "deepseek"
    assert report["base_url"] == "http://10.10.10.2:8888"
    assert report["port"] == 8888
    assert report["status"] == "ok"
    assert report["probed"] is True
    assert "10.10.10.2:8888" in block
    assert "deepseek" in block
    assert "8080" in block  # named only as a port that must not be invented
    assert "do not invent" in block.lower()
    assert "verified probe" in block.lower()


def test_kernel_build_surface_uses_resolved_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    surface = kernel_build_surface()
    assert surface.name == "kernel-build"
    assert surface.target == "http://10.10.10.2:8888/health"
    assert "8080" not in surface.target
    assert "10.10.10.2:8888" in surface.notes


def test_assemble_run_prompt_includes_verified_probe(tmp_path, monkeypatch):
    from soveryn.automations.memory import assemble_run_prompt
    from soveryn.automations.registry import AutomationSpec, Delivery

    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(200)):
        prompt = assemble_run_prompt(
            AutomationSpec(
                id="daily_planner",
                title="Daily Planner",
                category="productivity",
                agent="aetheria",
                cron="30 8 * * *",
                prompt="Build today's plan.",
                delivery=Delivery(channel="signal", target="jon"),
            )
        )
    assert "http://10.10.10.2:8888" in prompt
    assert "verified probe" in prompt.lower()
    assert "Build today's plan." in prompt
    # The forbidden guess may be named only as something not to invent.
    assert "127.0.0.1:8080 has never been a house brain" in prompt


def test_bench_flash_status_uses_resolved_brain(tmp_path, monkeypatch):
    from soveryn.app.services import bench_flash

    monkeypatch.setenv("SOVERYN_KERNEL_BRAIN", "deepseek")
    monkeypatch.setattr(runtime, "_KERNEL_BRAIN_FILE", tmp_path / "missing")
    seen: list[str] = []

    def fake_http(url, *, timeout=5.0):
        seen.append(url)
        return {"data": [{"id": "DeepSeek-V4.1-Flash-1017"}]}

    monkeypatch.setattr(bench_flash, "_http_json", fake_http)
    st = bench_flash.get_status()
    d = st.as_dict()
    assert d["brain"] == "deepseek"
    assert d["alias"] == "DeepSeek-V4.1-Flash-1017"
    assert d["router"] == "http://10.10.10.2:8888"
    assert d["state"] == "warm"
    assert seen == ["http://10.10.10.2:8888/v1/models"]
    assert all("8080" not in u for u in seen)
