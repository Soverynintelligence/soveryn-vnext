"""Entry point so `python -m soveryn.agents.signal_bridge` starts the daemon."""

from soveryn.agents.signal_bridge.daemon import _main

if __name__ == "__main__":
    raise SystemExit(_main())
