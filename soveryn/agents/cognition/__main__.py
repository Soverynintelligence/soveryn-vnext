"""Entry point so `python -m soveryn.agents.cognition` starts the cycle daemon.

Mirrors dream/heartbeat/representation. Gated off by default — see runner.py.
"""

from soveryn.agents.cognition.runner import _main

if __name__ == "__main__":
    raise SystemExit(_main())
