"""Tests for soveryn.app.preflight — report aggregation, ok/fail/deferred semantics.

All check_* functions are mocked. No real network or process calls.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from soveryn.config import runtime
from soveryn.config.loader import EnvConfig, load_env_config
from soveryn.inference.health import HealthResult
from soveryn.app.preflight import PreflightReport, run_preflight


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_env() -> EnvConfig:
    return load_env_config(env={})


def _ok(name: str, kind: str = "model_server") -> HealthResult:
    return HealthResult(name, kind, "ok", 5.0, "fine")


def _fail(name: str, kind: str = "model_server") -> HealthResult:
    return HealthResult(name, kind, "fail", 5.0, "refused")


def _deferred(name: str) -> HealthResult:
    return HealthResult(name, "runtime_service", "deferred", 0.0, "in-process thread")


# ─── PreflightReport.ok ───────────────────────────────────────────────────────

def test_preflight_ok_when_all_ok():
    results = (_ok("a"), _ok("b"), _ok("c"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.ok is True


def test_preflight_ok_when_mix_of_ok_and_deferred():
    results = (_ok("a"), _deferred("b"), _ok("c"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.ok is True


def test_preflight_ok_is_false_on_single_fail():
    results = (_ok("a"), _fail("b"), _ok("c"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.ok is False


def test_preflight_ok_is_false_even_with_deferred_alongside_fail():
    results = (_ok("a"), _fail("b"), _deferred("c"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.ok is False


def test_preflight_ok_with_all_deferred():
    """All deferred = no failures = ok."""
    results = (_deferred("a"), _deferred("b"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.ok is True


def test_preflight_ok_with_empty_results():
    report = PreflightReport(env=_make_env(), results=())
    assert report.ok is True


# ─── PreflightReport.failures ─────────────────────────────────────────────────

def test_failures_returns_only_fails():
    results = (_ok("a"), _fail("b"), _deferred("c"), _fail("d"))
    report = PreflightReport(env=_make_env(), results=results)
    assert len(report.failures) == 2
    assert all(r.status == "fail" for r in report.failures)
    assert {r.name for r in report.failures} == {"b", "d"}


def test_failures_empty_when_all_ok():
    results = (_ok("a"), _ok("b"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.failures == ()


def test_failures_does_not_include_deferred():
    results = (_deferred("a"), _deferred("b"))
    report = PreflightReport(env=_make_env(), results=results)
    assert report.failures == ()


# ─── format_text() ────────────────────────────────────────────────────────────

def test_format_text_ok_contains_preflight_ok():
    results = (_ok("aetheria_primary"), _ok("embeddings"))
    report = PreflightReport(env=_make_env(), results=results)
    text = report.format_text()
    assert "PREFLIGHT OK" in text


def test_format_text_fail_contains_preflight_failed():
    results = (_ok("aetheria_primary"), _fail("embeddings"))
    report = PreflightReport(env=_make_env(), results=results)
    text = report.format_text()
    assert "PREFLIGHT FAILED" in text


def test_format_text_includes_all_result_names():
    results = (_ok("aetheria_primary"), _fail("embeddings"), _deferred("heartbeat"))
    report = PreflightReport(env=_make_env(), results=results)
    text = report.format_text()
    assert "aetheria_primary" in text
    assert "embeddings" in text
    assert "heartbeat" in text


def test_format_text_includes_app_port():
    report = PreflightReport(env=_make_env(), results=())
    text = report.format_text()
    assert "app_port=" in text


def test_format_text_includes_timeout():
    report = PreflightReport(env=_make_env(), results=())
    text = report.format_text()
    assert "health_timeout=" in text


def test_format_text_shows_failure_names_in_summary():
    results = (_fail("bad_server"), _ok("good_server"))
    report = PreflightReport(env=_make_env(), results=results)
    text = report.format_text()
    # The failed server name must appear in the PREFLIGHT FAILED section
    assert "bad_server" in text


# ─── run_preflight() ──────────────────────────────────────────────────────────

def _patch_all_checks(model_results=None, service_results=None, runtime_results=None):
    """Helper that patches all three check_* functions."""
    n_models = len(runtime.MODEL_SERVERS)
    n_services = len(runtime.SERVICE_ENDPOINTS)
    n_runtimes = len(runtime.RUNTIME_SERVICES)

    model_r = model_results or [_ok(s.name, "model_server") for s in runtime.MODEL_SERVERS]
    svc_r = service_results or [_ok(e.name, "service_endpoint") for e in runtime.SERVICE_ENDPOINTS]
    rt_r = runtime_results or [_ok(r.name, "runtime_service") for r in runtime.RUNTIME_SERVICES]

    return (
        patch("soveryn.app.preflight.check_llama_server", side_effect=model_r),
        patch("soveryn.app.preflight.check_service_endpoint", side_effect=svc_r),
        patch("soveryn.app.preflight.check_runtime_service", side_effect=rt_r),
    )


def test_run_preflight_returns_preflight_report():
    patches = _patch_all_checks()
    with patches[0], patches[1], patches[2]:
        report = run_preflight()
    assert isinstance(report, PreflightReport)


def test_run_preflight_does_not_call_sys_exit():
    """The core contract: run_preflight is a pure function, not a CLI."""
    import sys
    patches = _patch_all_checks(
        model_results=[_fail(s.name, "model_server") for s in runtime.MODEL_SERVERS],
    )
    with patches[0], patches[1], patches[2], \
         patch.object(sys, "exit") as mock_exit:
        run_preflight()
    mock_exit.assert_not_called()


def test_run_preflight_result_count_equals_all_tiers():
    """Results must include one entry per MODEL_SERVER + SERVICE_ENDPOINT + RUNTIME_SERVICE."""
    expected = (
        len(runtime.MODEL_SERVERS)
        + len(runtime.SERVICE_ENDPOINTS)
        + len(runtime.RUNTIME_SERVICES)
    )
    patches = _patch_all_checks()
    with patches[0], patches[1], patches[2]:
        report = run_preflight()
    assert len(report.results) == expected


def test_run_preflight_uses_injected_env():
    env = load_env_config(env={"SOVERYN_APP_PORT": "9999"})
    patches = _patch_all_checks()
    with patches[0], patches[1], patches[2]:
        report = run_preflight(env=env)
    assert report.env.app_port == 9999


def test_run_preflight_passes_timeout_to_checks():
    """When timeout= is given, it should be forwarded to all check_* calls."""
    mock_results = [_ok(s.name) for s in runtime.MODEL_SERVERS]
    svc_results = [_ok(e.name) for e in runtime.SERVICE_ENDPOINTS]
    rt_results = [_ok(r.name) for r in runtime.RUNTIME_SERVICES]

    with patch("soveryn.app.preflight.check_llama_server", side_effect=mock_results) as p1, \
         patch("soveryn.app.preflight.check_service_endpoint", side_effect=svc_results) as p2, \
         patch("soveryn.app.preflight.check_runtime_service", side_effect=rt_results) as p3:
        run_preflight(timeout=0.5)

    for call in p1.call_args_list:
        assert call.kwargs.get("timeout") == 0.5 or call.args[1] == 0.5
    for call in p2.call_args_list:
        assert call.kwargs.get("timeout") == 0.5 or call.args[1] == 0.5
    for call in p3.call_args_list:
        assert call.kwargs.get("timeout") == 0.5 or call.args[1] == 0.5


def test_run_preflight_ok_all_checks_pass():
    patches = _patch_all_checks()
    with patches[0], patches[1], patches[2]:
        report = run_preflight()
    assert report.ok is True


def test_run_preflight_not_ok_when_one_model_fails():
    model_r = [_fail(runtime.MODEL_SERVERS[0].name, "model_server")] + [
        _ok(s.name, "model_server") for s in runtime.MODEL_SERVERS[1:]
    ]
    patches = _patch_all_checks(model_results=model_r)
    with patches[0], patches[1], patches[2]:
        report = run_preflight()
    assert report.ok is False
    assert len(report.failures) == 1


# ─── PreflightReport is frozen ────────────────────────────────────────────────

def test_preflight_report_is_frozen():
    report = PreflightReport(env=_make_env(), results=())
    with pytest.raises((AttributeError, TypeError)):
        report.results = (_ok("x"),)  # type: ignore[misc]
