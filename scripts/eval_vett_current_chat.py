"""Re-run the cross_source_link task against Vett-current's /chat path.

Matches the flat-format baseline shape used in the 2026-06-13 Harness-1
eval report (artifact `20260612_162531_baseline_rebaseline.json`):

    {
        "task": "cross_source_link",
        "query": "...",
        "expected_ids": [...],
        "response": "...",
        "elapsed_s": float,
        "session_id": "...",
        "tool_calls": null | [...],
        "black_box_jsonl_path": "..." | null,
    }

Adds the black_box JSONL path for the trajectory captured by the
2026-06-13 Phase 1 Black Box recorder (commit c2b9d31). Lets us
distinguish "Vett still single-shot synthesizes" from "Vett now tool-
loops and we can see what she did."
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


def _post_chat(
    *,
    chat_url: str,
    session_id: str,
    query: str,
    timeout: float,
) -> tuple[dict[str, Any], float]:
    body = {
        "session_id": session_id,
        "agent": "vett",
        "message": query,
    }
    started = time.monotonic()
    resp = requests.post(chat_url, json=body, timeout=timeout)
    elapsed = time.monotonic() - started
    resp.raise_for_status()
    return resp.json(), elapsed


def _new_session(sessions_url: str) -> str:
    resp = requests.post(
        sessions_url,
        json={"agent": "vett", "title": "cross_source_link rerun"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp.json()["session_id"]


def _score(response_text: str, expected_ids: tuple[str, ...]) -> dict:
    """Score the response against the expected IDs.

    - literal: 8-char prefix appears anywhere in the response text
    - content: substring of distinctive evidence keywords for each
      anchor (hard-coded — these are the same keywords the original
      report used so the numbers are directly comparable)
    """
    text = response_text.lower()

    literal = {}
    for eid in expected_ids:
        prefix = eid[:8]
        literal[eid] = prefix in text

    # Content keywords for each canonical node (matching the report's
    # "content evidence coverage" definition).
    content_keywords = {
        "bc6e16f3-a251-4791-8547-3f2a8da2058e": ("143 gib", "quadro", "blackwell"),
        "7e406410-09d3-43ee-b953-00339dfe626c": ("fully-local", "multi-agent", "llama.cpp"),
        "b42064cc-fce8-4b84-940d-ff4faf2eec75": ("scotty", "direct agent communication", "dac"),
    }
    content = {}
    for eid in expected_ids:
        keywords = content_keywords.get(eid, ())
        content[eid] = any(k in text for k in keywords) if keywords else False

    return {
        "literal_coverage": sum(1 for v in literal.values() if v),
        "content_coverage": sum(1 for v in content.values() if v),
        "literal": literal,
        "content": content,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-url", default="http://127.0.0.1:5001")
    parser.add_argument(
        "--task-module",
        default="soveryn.agents.vett.harness.eval_tasks.cross_source_link",
    )
    parser.add_argument("--output-dir", default="eval_runs")
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--label", default="vett_current_post_phase3")
    args = parser.parse_args(argv)

    # Load the task definition
    import importlib
    mod = importlib.import_module(args.task_module)
    task = mod.CROSS_SOURCE_LINK
    query = task.query
    expected_ids = tuple(task.expected_evidence_ids)

    # Run
    sessions_url = f"{args.app_url}/sessions"
    chat_url = f"{args.app_url}/chat"
    session_id = _new_session(sessions_url)
    print(f"[eval] session_id={session_id}", file=sys.stderr)
    print(f"[eval] hitting {chat_url} (timeout={args.timeout}s)...", file=sys.stderr)
    body, elapsed = _post_chat(
        chat_url=chat_url,
        session_id=session_id,
        query=query,
        timeout=args.timeout,
    )

    response_text = body.get("content", "")
    tool_calls = body.get("tool_calls")
    finish_reason = body.get("finish_reason")

    # Resolve the Black Box trajectory path, if any
    bb_path = Path("data/black_box/vett") / f"{session_id}.jsonl"
    bb_jsonl_path: str | None = str(bb_path) if bb_path.exists() else None

    # Score
    scoring = _score(response_text, expected_ids)
    print(
        f"[eval] elapsed={elapsed:.1f}s "
        f"literal_coverage={scoring['literal_coverage']}/{len(expected_ids)} "
        f"content_coverage={scoring['content_coverage']}/{len(expected_ids)}",
        file=sys.stderr,
    )
    if bb_jsonl_path:
        print(f"[eval] black_box: {bb_jsonl_path}", file=sys.stderr)
    else:
        print("[eval] no black_box record (Vett didn't tool-loop)", file=sys.stderr)

    # Persist
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{timestamp}_{args.label}.json"
    payload = {
        "task": task.name,
        "query": query,
        "expected_ids": list(expected_ids),
        "response": response_text,
        "elapsed_s": round(elapsed, 2),
        "session_id": session_id,
        "tool_calls": tool_calls,
        "finish_reason": finish_reason,
        "black_box_jsonl_path": bb_jsonl_path,
        "scoring": scoring,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[eval] wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
