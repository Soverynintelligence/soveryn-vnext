"""_configure_logging must install a root handler so the app's logging reaches
stdout (and thus systemd/journald).

Regression guard for the 2026-07-22 finding: the app previously configured NO
root handler, so every logger.getLogger(__name__) call emitted into the void and
the delegation/Scotty failures were invisible for 6 weeks.
"""
from __future__ import annotations

import io
import logging

from soveryn.app.__main__ import _configure_logging


def test_installs_a_root_handler():
    root = logging.getLogger()
    _configure_logging()
    assert root.handlers, "no root handler installed — app logs would go nowhere"


def test_emitted_record_reaches_a_stream(monkeypatch):
    _configure_logging()
    buf = io.StringIO()
    # attach a capture handler at the configured level and emit
    h = logging.StreamHandler(buf)
    logging.getLogger().addHandler(h)
    try:
        logging.getLogger("soveryn.test").info("delegation heartbeat")
    finally:
        logging.getLogger().removeHandler(h)
    assert "delegation heartbeat" in buf.getvalue()


def test_level_env_override(monkeypatch):
    monkeypatch.setenv("SOVERYN_LOG_LEVEL", "WARNING")
    _configure_logging()
    assert logging.getLogger().level == logging.WARNING
    # restore to INFO for other tests
    monkeypatch.setenv("SOVERYN_LOG_LEVEL", "INFO")
    _configure_logging()
