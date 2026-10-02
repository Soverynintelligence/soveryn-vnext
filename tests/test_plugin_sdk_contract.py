"""Pin the plugin SDK facade names so external CWG code has a frozen import surface."""
from __future__ import annotations

import inspect

from soveryn.plugins import sdk

_REQUIRED = {
    "ALLOWED_IMAGE_MIME_PREFIXES",
    "DEFAULT_ALLOWED_ROOTS",
    "DEFAULT_DATA_ROOT",
    "ExtractResult",
    "SignalBridgeConfig",
    "SignalCliError",
    "ToolArgError",
    "ToolRegistry",
    "ToolSpec",
    "current_turn_images",
    "data_root",
    "extract_pdf_path",
    "notify_lead",
    "notify_needs_you",
    "notify_pondwright_lead",
    "parse_current_index",
    "pick_current",
    "repo_root",
    "resolve_allowed",
    "send_once",
}


def test_sdk_all_contains_required_names():
    exported = set(sdk.__all__)
    missing = _REQUIRED - exported
    assert not missing, missing


def test_sdk_path_helpers_and_notify_signatures():
    assert inspect.signature(sdk.data_root).parameters == {}
    assert inspect.signature(sdk.repo_root).parameters == {}
    params = inspect.signature(sdk.notify_lead).parameters
    assert "title" in params
    assert sdk.data_root().name == "data"
