"""SOVERYN vNext — CLI launcher.

Tiny. Binds Flask via create_app() with a safe default config.
Run: `python -m soveryn.app [--host HOST] [--port PORT]`

Defaults:
  host = 127.0.0.1   (never reads from env; --host overrides)
  port = EnvConfig.app_port  (default 5001; --port overrides)

Safeguards:
  - Refuses to bind :5000 (that's production).
  - No auto-reload, no debug.
  - No side effects beyond create_app() + app.run().

Real binding lives here so the create_app factory stays pure for tests
and embedding. The Flask dev server is fine for side-by-side validation
on localhost; a production WSGI server (gunicorn/uwsgi) would be a
later commit if/when we need it.
"""

from __future__ import annotations
import os
import logging
import argparse
import sys

from flask import Flask

from soveryn.app.startup import create_app
from soveryn.config.loader import EnvConfig, load_env_config
from soveryn.config.runtime import ACTIVE_AGENTS


PRODUCTION_PORT = 5000
DEFAULT_HOST = "127.0.0.1"


class LauncherError(Exception):
    """Raised when the launcher refuses to start (e.g. port collision with prod)."""


def _resolve_launch_config(
    env: EnvConfig,
    host_override: str | None,
    port_override: int | None,
) -> tuple[str, int]:
    """Resolve final (host, port). Host defaults to 127.0.0.1; port defaults to env.app_port.

    Raises LauncherError if the resolved port equals PRODUCTION_PORT.
    """
    host = host_override if host_override else DEFAULT_HOST
    port = port_override if port_override is not None else env.app_port
    if port == PRODUCTION_PORT:
        raise LauncherError(
            f"refusing to bind port {PRODUCTION_PORT}: that's production SOVERYN. "
            f"vNext default is {env.app_port}; pass --port to override."
        )
    return host, port


def _configure_logging() -> None:
    """Send the app's Python logging to stdout so systemd captures it.

    Added 2026-07-22. Before this the app configured NO root handler, so every
    ``logging.getLogger(__name__)`` call across the codebase emitted into the
    void — 120 journal lines over 9 days, zero from Python. The delegation
    engine and Scotty runner logged their failures faithfully and nobody could
    read them, which is what made the Scotty 8/8 empty-diff failures take 6
    weeks to diagnose. For a project whose thesis is that the audit log is
    ground truth, silent logging is a first-class bug.

    Level is env-overridable via SOVERYN_LOG_LEVEL (default INFO). Idempotent:
    force=True so a re-entrant call (tests, reload) doesn't stack handlers.
    """
    level_name = os.environ.get("SOVERYN_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        force=True,
    )


def _build_startup_line(host: str, port: int, env: EnvConfig, agent_names: list[str]) -> str:
    """One-line summary printed before app.run."""
    return (
        f"[soveryn] vNext serving on http://{host}:{port} "
        f"— agents=[{','.join(sorted(agent_names))}] "
        f"— conv={env.conversations_db} "
        f"— lattice={env.lattice_db}"
    )


def main(argv: list[str] | None = None, *, app_factory=create_app, runner=None) -> int:
    """CLI entry. argv defaults to sys.argv[1:].

    `app_factory` and `runner` are injected for tests — never patch
    `app.run` globally; pass a fake runner instead.

    LauncherError is allowed to propagate to the caller so tests can catch it.
    In __main__ context, the shell sees exit code 1 from the exception handler below.
    """
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.app",
        description="SOVERYN vNext — start the Flask app on a safe local port.",
    )
    parser.add_argument("--host", default=None,
                        help=f"bind host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=None,
                        help="bind port (default: EnvConfig.app_port = 5001)")
    args = parser.parse_args(argv)

    _configure_logging()

    env = load_env_config()
    host, port = _resolve_launch_config(env, args.host, args.port)

    app = app_factory(env=env)
    agent_names = list(app.extensions["soveryn"]["agent_loops"].keys())

    print(_build_startup_line(host, port, env, agent_names), flush=True)

    if runner is None:
        runner = _default_runner
    runner(app, host=host, port=port)
    return 0


def _default_runner(app: Flask, *, host: str, port: int) -> None:
    """Default runner: Flask's dev server with debug + reloader OFF."""
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LauncherError as e:
        print(str(e), file=sys.stderr, flush=True)
        sys.exit(1)
