"""Entry point so `python -m soveryn.agents.dream` starts the daemon."""

from soveryn.agents.dream.daemon import _main

if __name__ == "__main__":
    raise SystemExit(_main())
