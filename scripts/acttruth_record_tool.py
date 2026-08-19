#!/usr/bin/env python3
"""Record one ActTruth tool audit event (used by OpenCode Kernel plugin).

Usage:
  echo '{"tool":"bash","args":{"command":"ls"},"ok":true,"result":"..."}' \\
    | scripts/acttruth_record_tool.py

  scripts/acttruth_record_tool.py --tool write --args '{"filePath":"x"}' --ok 1

Env:
  ACTTRUTH_AGENT   default kernel
  SOVERYN_PYTHON   optional interpreter override
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _load_payload(argv: list[str]) -> dict[str, Any]:
    p = argparse.ArgumentParser(description="Record ActTruth tool audit")
    p.add_argument("--tool", default="")
    p.add_argument("--args", default="{}")
    p.add_argument("--ok", default="")
    p.add_argument("--result", default="")
    p.add_argument("--error", default="")
    p.add_argument("--agent", default="")
    p.add_argument("--stdin", action="store_true", help="Read full JSON object from stdin")
    ns = p.parse_args(argv)

    data: dict[str, Any] = {}
    if ns.stdin or (not ns.tool and not sys.stdin.isatty()):
        raw = sys.stdin.read().strip()
        if raw:
            data = json.loads(raw)

    if ns.tool:
        data["tool"] = ns.tool
    if ns.args and ns.args != "{}":
        data["args"] = json.loads(ns.args) if isinstance(ns.args, str) else ns.args
    if ns.ok != "":
        data["ok"] = ns.ok in ("1", "true", "True", "yes", "ok")
    if ns.result:
        data["result"] = ns.result
    if ns.error:
        data["error"] = ns.error
    if ns.agent:
        data["agent"] = ns.agent
    return data


def main() -> int:
    try:
        data = _load_payload(sys.argv[1:])
    except Exception as e:  # noqa: BLE001
        print(f"acttruth_record_tool: bad input: {e}", file=sys.stderr)
        return 2

    tool = str(data.get("tool") or data.get("tool_name") or "").strip()
    if not tool:
        print("acttruth_record_tool: missing tool", file=sys.stderr)
        return 2

    args = data.get("args")
    if not isinstance(args, dict):
        args = {"raw": args}

    agent = str(data.get("agent") or __import__("os").environ.get("ACTTRUTH_AGENT") or "kernel")
    ok = bool(data.get("ok", True))
    result = data.get("result")
    error = data.get("error")
    if error is not None:
        error = str(error)
        ok = False

    try:
        from soveryn.platform.acttruth.hooks import record_tool_audit

        record_tool_audit(
            agent=agent,
            tool_name=f"opencode:{tool}",
            args=args,
            ok=ok,
            result=result,
            error=error,
        )
    except Exception as e:  # noqa: BLE001
        print(f"acttruth_record_tool: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
