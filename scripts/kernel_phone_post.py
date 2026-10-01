#!/usr/bin/env python3
"""Post Kernel CLI status/receipt into Messages (/messages/kernel).

Usage:
  kernel status | python scripts/kernel_phone_post.py --action status
  python scripts/kernel_phone_post.py --action receipts --run-id <id> --body "..."
  python -m soveryn…  (or):
  python scripts/kernel_phone_post.py --from-status

Requires soveryn-vnext :5001 up. Localhost only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "http://127.0.0.1:5001/api/internal/kernel_cli_receipt"
ROOT = Path(__file__).resolve().parents[1]


def _post(payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        API,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--action", default="receipt", help="status|receipts|report|receipt")
    ap.add_argument("--run-id", default="")
    ap.add_argument("--summary", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--finish-reason", default="")
    ap.add_argument("--ok", choices=("true", "false", ""), default="")
    ap.add_argument(
        "--from-status",
        action="store_true",
        help="Run `kernel status` and post the HUD to Messages",
    )
    ap.add_argument(
        "--verdict",
        action="append",
        default=[],
        help="Repeatable PASS/FAIL claim lines",
    )
    args = ap.parse_args()

    body = args.body
    if not body and not sys.stdin.isatty():
        body = sys.stdin.read()

    ok = None
    if args.ok == "true":
        ok = True
    elif args.ok == "false":
        ok = False

    run_id = args.run_id
    action = args.action
    finish_reason = args.finish_reason
    verdict = list(args.verdict)

    if args.from_status:
        action = "status"
        launcher = ROOT / "scripts" / "soveryn-pi"
        home_kernel = Path.home() / "bin" / "kernel"
        bin_path = str(home_kernel if home_kernel.is_file() else launcher)
        proc = subprocess.run(
            [bin_path, "status"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(ROOT),
        )
        body = ((proc.stdout or "") + (proc.stderr or "")).strip()
        ok = proc.returncode == 0 and "READY" in body
        verdict = [
            f"[{'PASS' if ok else 'FAIL'}] kernel status: exit={proc.returncode}"
        ]
        finish_reason = "stop" if ok else "status_not_ready"

    if not body and not verdict:
        print("need --body, stdin, --verdict, or --from-status", file=sys.stderr)
        return 2

    payload = {
        "action": action,
        "body": body,
        "summary": args.summary or action,
        "run_id": run_id,
        "finish_reason": finish_reason,
        "verdict": verdict,
    }
    if ok is not None:
        payload["ok"] = ok

    try:
        out = _post(payload)
    except urllib.error.URLError as exc:
        print(f"FAIL post: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
