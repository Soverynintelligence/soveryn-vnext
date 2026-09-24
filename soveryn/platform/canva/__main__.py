"""CLI: python -m soveryn.platform.canva authorize|status"""
from __future__ import annotations

import argparse
import json
import sys

from soveryn.platform.canva.config import load_config
from soveryn.platform.canva.oauth import CanvaAuthError, run_authorize_flow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.platform.canva",
        description="Canva Connect for SOVERYN / Eve marketing",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_auth = sub.add_parser("authorize", help="PKCE OAuth — open browser once")
    p_auth.add_argument(
        "--no-browser",
        action="store_true",
        help="Print URL only; do not open browser",
    )

    sub.add_parser("status", help="Show config / auth state")

    args = parser.parse_args(argv)
    cfg = load_config()

    if args.cmd == "status":
        cid = cfg.client_id
        fingerprint = None
        warnings: list[str] = []
        if cid:
            fingerprint = {
                "len": len(cid),
                "prefix": cid[:5],
                "suffix": cid[-4:],
                "starts_with_OC": cid.startswith("OC"),
            }
            if not cid.startswith("OC"):
                warnings.append(
                    "Client IDs from Canva Developer Portal usually start "
                    "with 'OC' (e.g. OC-…). Double-check you copied Client ID, "
                    "not the secret."
                )
            if " " in cid or "\n" in cid:
                warnings.append("Client ID contains whitespace — re-copy it.")
        else:
            warnings.append(
                "SOVERYN_CANVA_CLIENT_ID is not set in this shell. Export it "
                "(and the secret), then re-run status / authorize."
            )
        print(
            json.dumps(
                {
                    "configured": cfg.configured,
                    "authorized": cfg.authorized,
                    "client_id_set": bool(cfg.client_id),
                    "client_id_fingerprint": fingerprint,
                    "redirect_uri": cfg.redirect_uri,
                    "token_path": str(cfg.token_path),
                    "media_dir": str(cfg.media_dir),
                    "brand_templates": cfg.brand_templates,
                    "scopes": list(cfg.scopes),
                    "warnings": warnings,
                },
                indent=2,
            )
        )
        return 0

    if args.cmd == "authorize":
        try:
            path = run_authorize_flow(
                cfg, open_browser=not args.no_browser
            )
        except CanvaAuthError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"ok: {path}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
