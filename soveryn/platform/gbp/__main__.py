"""CLI: python -m soveryn.platform.gbp authorize|status"""
from __future__ import annotations

import argparse
import json
import sys

from soveryn.platform.gbp.client import gbp_status
from soveryn.platform.gbp.config import load_config
from soveryn.platform.gbp.oauth import GbpAuthError, run_authorize_flow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.platform.gbp",
        description="Google Business Profile for CWG / Eve",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_auth = sub.add_parser("authorize", help="OAuth — open browser once")
    p_auth.add_argument("--no-browser", action="store_true")
    sub.add_parser("status", help="Show config / auth state")
    args = parser.parse_args(argv)
    cfg = load_config()
    if args.cmd == "status":
        print(json.dumps(gbp_status(cfg=cfg), indent=2))
        print(
            json.dumps(
                {
                    "configured": cfg.configured,
                    "authorized": cfg.authorized,
                    "redirect_uri": cfg.redirect_uri,
                    "token_path": str(cfg.token_path),
                    "location": cfg.location or None,
                    "cta_url": cfg.cta_url,
                },
                indent=2,
            )
        )
        return 0
    if args.cmd == "authorize":
        try:
            path = run_authorize_flow(cfg, open_browser=not args.no_browser)
        except GbpAuthError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(path)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
