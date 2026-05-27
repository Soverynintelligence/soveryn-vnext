"""Tests for the Phase 1 platform package skeleton."""

from importlib import import_module


def test_platform_package_imports():
    modules = [
        "soveryn.platform",
        "soveryn.platform.lattice",
        "soveryn.platform.tools",
        "soveryn.platform.inference",
        "soveryn.platform.bus",
        "soveryn.platform.supervisor",
        "soveryn.platform.telemetry",
        "soveryn.platform.repair",
    ]

    for module_name in modules:
        module = import_module(module_name)
        assert module.__doc__

def test_inference_compatibility_shims_reexport_platform_objects():
    platform_client = import_module("soveryn.platform.inference.llama_server_client")
    compat_client = import_module("soveryn.inference.llama_server_client")
    assert compat_client.ChatRequest is platform_client.ChatRequest
    assert compat_client.chat is platform_client.chat
    assert compat_client.embed is platform_client.embed

    platform_routing = import_module("soveryn.platform.inference.routing")
    compat_routing = import_module("soveryn.inference.routing")
    assert compat_routing.RoutingError is platform_routing.RoutingError
    assert compat_routing.route_for_agent is platform_routing.route_for_agent

    platform_health = import_module("soveryn.platform.inference.health")
    compat_health = import_module("soveryn.inference.health")
    assert compat_health.HealthResult is platform_health.HealthResult
    assert compat_health.check_llama_server is platform_health.check_llama_server
