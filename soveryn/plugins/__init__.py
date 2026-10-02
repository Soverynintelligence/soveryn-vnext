"""SOVERYN plugin loader (API v1).

External packages register via ``soveryn.plugins`` entry points. The in-tree
CWG adapter (``builtin_cwg``) is the default source for PondWright / CWG
social tools until the private ``soveryn-cwg`` package is installed and
allowlisted. See ``loader.py`` for ``SOVERYN_PLUGINS`` semantics.
"""
from __future__ import annotations

from soveryn.plugins.api import PLUGIN_API, PluginBase, SoverynPlugin, Worker
from soveryn.plugins.loader import (
    ensure_loaded,
    iter_chat_image_hooks,
    plugin_board_rows,
    reset_plugins,
    start_background_workers,
)

__all__ = [
    "PLUGIN_API",
    "PluginBase",
    "SoverynPlugin",
    "Worker",
    "ensure_loaded",
    "iter_chat_image_hooks",
    "plugin_board_rows",
    "reset_plugins",
    "start_background_workers",
]
