"""Entry point so the daemon can run as `python -m soveryn.agents.vett.patrol`."""

from soveryn.agents.vett.patrol.daemon import _main


if __name__ == "__main__":
    raise SystemExit(_main())
