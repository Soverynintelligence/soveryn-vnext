"""Entry point for the router watchdog timer: one tick per invocation."""
from soveryn.platform.watchdog.router_watchdog import run_once

if __name__ == "__main__":
    result = run_once()
    print(f"router-watchdog: dead={result['dead']} action={result['action']}")
