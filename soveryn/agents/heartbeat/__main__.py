"""Entry point for `python -m soveryn.agents.heartbeat`."""

from soveryn.agents.heartbeat.daemon import _main


if __name__ == "__main__":
    raise SystemExit(_main())
