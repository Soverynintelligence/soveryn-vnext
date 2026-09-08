"""CLI: python -m soveryn.platform.gcal authorize|status"""
from __future__ import annotations

import argparse
import json
import sys

from soveryn.platform.gcal.client import gcal_status
from soveryn.platform.gcal.config import load_config
from soveryn.platform.gcal.oauth import GcalAuthError, run_authorize_flow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.platform.gcal",
        description="Google Calendar for CWG / Eve",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_auth = sub.add_parser("authorize", help="OAuth — open browser once")
    p_auth.add_argument("--no-browser", action="store_true")
    sub.add_parser("status", help="Show config / auth state")
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "status":
        print(json.dumps(gcal_status(cfg=cfg), indent=2))
        return 0
    if args.cmd == "authorize":
        try:
            path = run_authorize_flow(cfg, open_browser=not args.no_browser)
        except GcalAuthError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(path)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
