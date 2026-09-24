"""Automation runner: execute an automation (dry-run or live), plus a small CLI.

Two modes:

  * dry-run (default) — renders exactly what a live run would send; no model,
    no tools, no egress. Safe from any process (CLI included).
  * live — drives the spec's citizen through one real ``AgentLoop`` turn
    IN-PROCESS. Requires ``agent_loop`` + ``conv_store`` (the running app's
    loops from ``app.extensions['soveryn']``). The Approval Gate governs any
    egressing tool the citizen calls. The CLI cannot do a live run (no loops
    out-of-process); it stays dry-run only.
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Dict, List, Optional, TYPE_CHECKING

from .registry import AutomationSpec, get_automation, load_automations
from .deliver import deliver
from .memory import prepare_run, save_last_output

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..agents.loop import AgentLoop
    from ..memory.conversation_store import ConversationStore

logger = logging.getLogger("soveryn.automations.runner")


def run_automation(
    automation_id: str,
    *,
    dry_run: bool = True,
    agent_loop: Optional["AgentLoop"] = None,
    conv_store: Optional["ConversationStore"] = None,
) -> Dict[str, object]:
    """Run one automation and return a result dict.

    dry_run=True (default)  -> preview only; no side effects.
    dry_run=False           -> live in-process turn; needs ``agent_loop`` +
                               ``conv_store``. If either is missing, ``deliver``
                               refuses with a clear error surfaced in the result
                               rather than silently no-oping.

    The result includes: id, agent, status, dry_run, and (dry-run) a preview of
    the prompt/delivery, or (live) the turn's content/session/tool_calls.
    Unknown ids raise KeyError.
    """
    spec: AutomationSpec = get_automation(automation_id)

    if not spec.enabled:
        return {
            "id": spec.id,
            "agent": spec.agent,
            "status": "disabled",
            "dry_run": True,
            "message": f"automation {spec.id!r} is disabled in the catalog",
        }

    assembled: str | None = None
    if not dry_run:
        prep = prepare_run(spec)
        if prep.skip:
            skip_status = prep.reason or "no_change"
            channels = ["command_center"]
            return {
                "id": spec.id,
                "title": spec.title,
                "category": spec.category,
                "agent": spec.agent,
                "cron": spec.cron,
                "status": skip_status,
                "dry_run": False,
                "mode": "skipped",
                "prompt": spec.prompt,
                "content": "",
                "message": prep.error,
                "channels": channels,
                "delivery": {
                    "channel": channels[0],
                    "channels": channels,
                    "target": spec.delivery.target,
                    "preview": None,
                },
            }
        assembled = prep.prompt
    else:
        from .memory import assemble_run_prompt

        assembled = assemble_run_prompt(spec)

    delivery = deliver(
        spec,
        dry_run=dry_run,
        agent_loop=agent_loop,
        conv_store=conv_store,
        prompt=assembled,
    )

    status = "ok" if delivery["status"] in ("would_send", "ok") else delivery["status"]  # type: ignore[assignment]
    channels = list(delivery.get("channels") or [delivery["channel"]])

    result: Dict[str, object] = {
        "id": spec.id,
        "title": spec.title,
        "category": spec.category,
        "agent": spec.agent,
        "cron": spec.cron,
        "status": status,
        "dry_run": dry_run,
        "mode": delivery.get("mode"),
        "prompt": spec.prompt,
        "channels": channels,
        "delivery": {
            "channel": delivery["channel"],
            "channels": channels,
            "target": delivery["target"],
            "preview": delivery.get("preview"),
        },
    }

    # Live runs carry the real turn output; surface it for the UI.
    if not dry_run and delivery.get("mode") == "live":
        result["session_id"] = delivery.get("session_id")
        result["content"] = delivery.get("content")
        result["finish_reason"] = delivery.get("finish_reason")
        result["tool_calls"] = delivery.get("tool_calls")
        result["usage"] = delivery.get("usage")
        result["context_usage"] = delivery.get("context_usage")
        content = str(delivery.get("content") or "")
        if status == "ok" and content:
            save_last_output(spec.id, content)

    return result


def _print_list() -> None:
    catalog, order = load_automations()
    for automation_id in order:
        spec = catalog[automation_id]
        state = "enabled" if spec.enabled else "disabled"
        print(
            f"{spec.id:<22} {spec.category:<14} {spec.agent:<10} "
            f"{spec.cron:<14} {state}"
        )
    print(f"\n{len(order)} automations (v0, dry-run only)")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m soveryn.automations.runner",
        description="Run a SOVERYN automation (v0: dry-run only).",
    )
    parser.add_argument(
        "automation",
        nargs="?",
        help="automation id to run (omit with --list to list the catalog)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list all automations and exit",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "attempt a live run. The CLI has no in-process agent loops, so "
            "this is refused: run live from the Command Center (the app's "
            "process holds the loops)."
        ),
    )
    args = parser.parse_args(argv)

    if args.list:
        _print_list()
        return 0

    if not args.automation:
        parser.print_usage(sys.stderr)
        print(
            "error: provide an automation id, or use --list",
            file=sys.stderr,
        )
        return 2

    if args.live:
        print(
            f"refused: {args.automation!r} cannot run live from the CLI. "
            "The CLI has no in-process agent loops; run a live automation "
            "from the Command Center (the app's process holds the loops).",
            file=sys.stderr,
        )
        return 3

    try:
        result = run_automation(args.automation, dry_run=True)
    except KeyError as exc:
        print(f"error: {exc.args[0]}", file=sys.stderr)
        return 4

    _print_result(result)
    return 0 if result["status"] == "ok" else 1


def _print_result(result: Dict[str, object]) -> None:
    print(f"automation : {result['id']}")
    print(f"title      : {result.get('title')}")
    print(f"category   : {result.get('category')}")
    print(f"agent      : {result['agent']}")
    print(f"cron       : {result.get('cron')}")
    print(f"status     : {result['status']}")
    print(f"dry_run    : {result['dry_run']}")
    _del = result["delivery"]  # type: ignore[index]
    _chans = _del.get("channels") or [_del.get("channel")]  # type: ignore[union-attr]
    print(f"delivery   : {'+'.join(str(c) for c in _chans)} -> {_del['target']}")  # type: ignore[index]
    print("--- prompt ---")
    print(result["prompt"])  # type: ignore[arg-type]
    preview = result["delivery"].get("preview")  # type: ignore[union-attr]
    if preview:
        print("--- delivery preview ---")
        print(preview)


if __name__ == "__main__":
    raise SystemExit(main())
