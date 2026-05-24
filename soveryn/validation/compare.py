"""SOVERYN side-by-side comparison CLI.

Hits production (:5000) and vNext (:5001) with the same prompt, reports
per-side status / latency / content / finish_reason / usage, and prints
a unified diff when contents differ.

Stdlib only — urllib.request, json, difflib, argparse. The point is to
generate evidence from real prompts; the tool itself must not introduce
dependency surface that obscures what's being compared.

Usage:
    python -m soveryn.validation.compare --agent aetheria --message "hello"

    # Reuse existing sessions on both sides:
    python -m soveryn.validation.compare --agent vett \\
        --session-prod  abc-123 --session-vnext xyz-789 \\
        --message "summarize the latest"

    # Streaming comparison:
    python -m soveryn.validation.compare --agent aetheria \\
        --message "tell me a short joke" --stream

    # Persist the full comparison:
    python -m soveryn.validation.compare --agent vett \\
        --message "..." --json-out /tmp/compare-run.json

The tool does NOT mutate production state beyond creating a session if
none is provided (and that session sits idle thereafter).
"""

from __future__ import annotations
import argparse
import difflib
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any


DEFAULT_PROD_BASE = "http://127.0.0.1:5000"
DEFAULT_VNEXT_BASE = "http://127.0.0.1:5001"
DEFAULT_AGENT = "aetheria"
DEFAULT_TIMEOUT_SECONDS = 120.0


@dataclass
class SideResult:
    """Outcome from one side (prod or vNext) of the comparison."""
    base_url: str
    ok: bool
    status_code: int | None = None
    latency_ms: float | None = None
    session_id: str | None = None
    content: str = ""
    finish_reason: str | None = None
    usage: dict | None = None
    error: str | None = None
    raw: dict | None = None  # full response payload for --json-out only


@dataclass
class ComparisonReport:
    """Full comparison record."""
    agent: str
    message: str
    stream: bool
    prod: SideResult
    vnext: SideResult
    contents_match: bool = False
    diff: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP helpers — stdlib only
# ─────────────────────────────────────────────────────────────────────────────

def _post_json(base: str, path: str, body: dict, timeout: float) -> tuple[int, dict]:
    """POST JSON, return (status_code, parsed_body). Raises on transport errors."""
    url = base.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            parsed = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            parsed = {"_raw_body": body_text[:500]}
        return e.code, parsed
    try:
        parsed = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        parsed = {"_raw_body": raw[:500]}
    return status, parsed


def _post_sse(base: str, path: str, body: dict, timeout: float) -> tuple[int, list[dict]]:
    """POST JSON, parse SSE response into list of event dicts. Returns (status, events)."""
    url = base.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            parsed = json.loads(body_text)
            return e.code, [parsed] if isinstance(parsed, dict) else []
        except json.JSONDecodeError:
            return e.code, []

    events: list[dict] = []
    try:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line.startswith("data: "):
                continue
            data_part = line[len("data: "):].strip()
            if not data_part or data_part == "[DONE]":
                continue
            try:
                events.append(json.loads(data_part))
            except json.JSONDecodeError:
                continue
        return resp.status, events
    finally:
        try:
            resp.close()
        except Exception:
            pass


def _aggregate_sse_events(events: list[dict]) -> tuple[str, str | None, dict | None]:
    """Accumulate content, capture final finish_reason and usage. Match vNext
    canonical SSE shape: {type:"token","delta":"..."} | {type:"done", ...}
    | {type:"error","code":"...","message":"..."}.

    For unknown shapes (e.g., production may use a different schema), best-effort:
    look for 'content'/'delta'/'token' string fields; treat the last 'done'-like
    event as terminal.
    """
    content_parts: list[str] = []
    finish_reason: str | None = None
    usage: dict | None = None
    for e in events:
        if not isinstance(e, dict):
            continue
        etype = e.get("type")
        if etype == "token":
            delta = e.get("delta")
            if isinstance(delta, str):
                content_parts.append(delta)
        elif etype == "done":
            # vNext canonical: done event carries final content + finish_reason + usage
            final_content = e.get("content")
            if isinstance(final_content, str):
                # Prefer the done event's content (authoritative) over our token accumulation
                content_parts = [final_content]
            fr = e.get("finish_reason")
            if isinstance(fr, str):
                finish_reason = fr
            u = e.get("usage")
            if isinstance(u, dict):
                usage = u
        elif etype == "error":
            # Embed error message in content for the diff to show clearly
            err = f"[ERROR {e.get('code','?')}: {e.get('message','')}]"
            content_parts.append(err)
        else:
            # Unknown shape — try common content fields
            for key in ("content", "delta", "token"):
                v = e.get(key)
                if isinstance(v, str):
                    content_parts.append(v)
                    break
    return "".join(content_parts), finish_reason, usage


# ─────────────────────────────────────────────────────────────────────────────
# One-side runner
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_session(base: str, agent: str, existing: str | None, timeout: float) -> tuple[str | None, str | None]:
    """Return (session_id, error).

    - If `existing` is provided, return it as-is.
    - If POST /sessions returns 404, treat as "this side has no explicit
      sessions endpoint" (production behaves this way — it auto-mints
      session_ids inside /chat). Return (None, None) so the caller proceeds
      WITHOUT a session_id; the chat body will omit the field.
    - Any other non-2xx is a real error.
    """
    if existing:
        return existing, None
    try:
        status, body = _post_json(base, "/sessions", {"agent": agent}, timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, f"session create transport error: {type(e).__name__}: {e}"
    if status == 404:
        # Side doesn't expose POST /sessions — fall back to ambient/auto-mint.
        return None, None
    if not (200 <= status < 300):
        return None, f"session create HTTP {status}: {body}"
    sid = body.get("session_id")
    if not isinstance(sid, str):
        return None, f"session create returned no session_id: {body}"
    return sid, None


def run_one_side(
    *,
    base: str,
    agent: str,
    message: str,
    session_id: str | None,
    stream: bool,
    timeout: float,
) -> SideResult:
    """Hit one side end-to-end. Always returns a SideResult; transport errors
    are captured in .error/.ok=False rather than raised."""
    result = SideResult(base_url=base, ok=False)

    sid, err = _ensure_session(base, agent, session_id, timeout)
    if err:
        result.error = err
        return result
    result.session_id = sid  # may be None when ambient-session side

    # Build chat body. Omit session_id when None (ambient session — prod auto-mints).
    body: dict = {"agent": agent, "message": message}
    if sid is not None:
        body["session_id"] = sid
    path = "/chat_stream" if stream else "/chat"

    started = time.monotonic()
    try:
        if stream:
            status, events = _post_sse(base, path, body, timeout)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            result.status_code = status
            result.latency_ms = elapsed_ms
            if not (200 <= status < 300):
                result.error = f"HTTP {status}"
                result.raw = {"events": events}
                return result
            content, finish_reason, usage = _aggregate_sse_events(events)
            result.content = content
            result.finish_reason = finish_reason
            result.usage = usage
            result.raw = {"events": events}
            result.ok = True
            return result
        else:
            status, payload = _post_json(base, path, body, timeout)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            result.status_code = status
            result.latency_ms = elapsed_ms
            result.raw = payload if isinstance(payload, dict) else None
            if not (200 <= status < 300):
                result.error = f"HTTP {status}: {payload}"
                return result
            # vNext shape: {agent, session_id, content, finish_reason, tool_calls, usage}
            # Production may differ; pull defensively.
            content = payload.get("content") if isinstance(payload, dict) else None
            if not isinstance(content, str):
                # Production might use 'response' or 'message' field
                for alt in ("response", "message", "text", "reply"):
                    v = payload.get(alt) if isinstance(payload, dict) else None
                    if isinstance(v, str):
                        content = v
                        break
            result.content = content if isinstance(content, str) else ""
            fr = payload.get("finish_reason") if isinstance(payload, dict) else None
            if isinstance(fr, str):
                result.finish_reason = fr
            u = payload.get("usage") if isinstance(payload, dict) else None
            if isinstance(u, dict):
                result.usage = u
            result.ok = True
            return result
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        elapsed_ms = (time.monotonic() - started) * 1000.0
        result.latency_ms = elapsed_ms
        result.error = f"transport error: {type(e).__name__}: {e}"
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Comparison + reporting
# ─────────────────────────────────────────────────────────────────────────────

def run_comparison(
    *,
    agent: str,
    message: str,
    stream: bool,
    prod_base: str = DEFAULT_PROD_BASE,
    vnext_base: str = DEFAULT_VNEXT_BASE,
    session_prod: str | None = None,
    session_vnext: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ComparisonReport:
    """Run both sides and assemble a ComparisonReport."""
    prod = run_one_side(
        base=prod_base, agent=agent, message=message,
        session_id=session_prod, stream=stream, timeout=timeout,
    )
    vnext = run_one_side(
        base=vnext_base, agent=agent, message=message,
        session_id=session_vnext, stream=stream, timeout=timeout,
    )

    report = ComparisonReport(agent=agent, message=message, stream=stream,
                              prod=prod, vnext=vnext)
    if prod.ok and vnext.ok:
        if prod.content == vnext.content:
            report.contents_match = True
        else:
            report.diff = list(difflib.unified_diff(
                prod.content.splitlines(),
                vnext.content.splitlines(),
                fromfile="prod", tofile="vnext", lineterm="",
            ))
    return report


def format_report(report: ComparisonReport) -> str:
    """Human-readable summary for stdout."""
    lines: list[str] = []
    lines.append(f"=== SOVERYN side-by-side: agent={report.agent}, stream={report.stream} ===")
    lines.append(f"message: {report.message!r}")
    lines.append("")
    for side_name, side in (("PROD ", report.prod), ("vNEXT", report.vnext)):
        lines.append(f"--- {side_name} ({side.base_url}) ---")
        if side.ok:
            lat = f"{side.latency_ms:.0f}ms" if side.latency_ms is not None else "?ms"
            lines.append(f"  status: {side.status_code}  latency: {lat}  session: {side.session_id}")
            lines.append(f"  finish_reason: {side.finish_reason}")
            if side.usage:
                u = side.usage
                lines.append(f"  usage: prompt={u.get('prompt_tokens','?')} "
                             f"completion={u.get('completion_tokens','?')} "
                             f"total={u.get('total_tokens','?')}")
            lines.append(f"  content ({len(side.content)} chars):")
            # Indent content for readability
            for cline in side.content.splitlines() or [""]:
                lines.append(f"    {cline}")
        else:
            lat = f"{side.latency_ms:.0f}ms" if side.latency_ms is not None else "?ms"
            lines.append(f"  FAILED ({lat}): {side.error}")
        lines.append("")
    if report.prod.ok and report.vnext.ok:
        if report.contents_match:
            lines.append("=== Contents match exactly ===")
        else:
            lines.append("=== Diff (prod → vnext) ===")
            for d in report.diff:
                lines.append(d)
    else:
        lines.append("=== Diff skipped (one side failed) ===")
    return "\n".join(lines)


def _report_to_json(report: ComparisonReport) -> dict:
    """Serialize for --json-out. Includes raw payloads."""
    return {
        "agent": report.agent,
        "message": report.message,
        "stream": report.stream,
        "contents_match": report.contents_match,
        "diff": report.diff,
        "prod": asdict(report.prod),
        "vnext": asdict(report.vnext),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m soveryn.validation.compare",
        description="Side-by-side compare prod (:5000) vs vNext (:5001) for one prompt.",
    )
    p.add_argument("--agent", default=DEFAULT_AGENT,
                   help=f"agent name (default: {DEFAULT_AGENT})")
    p.add_argument("--message", required=True,
                   help="user message to send (required, non-empty)")
    p.add_argument("--session-prod", default=None,
                   help="reuse existing prod session_id (default: create new)")
    p.add_argument("--session-vnext", default=None,
                   help="reuse existing vNext session_id (default: create new)")
    p.add_argument("--stream", action="store_true",
                   help="use /chat_stream (SSE) instead of /chat (sync)")
    p.add_argument("--prod-base", default=DEFAULT_PROD_BASE,
                   help=f"prod base URL (default: {DEFAULT_PROD_BASE})")
    p.add_argument("--vnext-base", default=DEFAULT_VNEXT_BASE,
                   help=f"vNext base URL (default: {DEFAULT_VNEXT_BASE})")
    p.add_argument("--json-out", default=None,
                   help="write full comparison as JSON to this path (default: stdout only)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                   help=f"per-request timeout seconds (default: {DEFAULT_TIMEOUT_SECONDS})")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.message.strip():
        print("error: --message must be a non-empty string", file=sys.stderr)
        return 2

    report = run_comparison(
        agent=args.agent,
        message=args.message,
        stream=args.stream,
        prod_base=args.prod_base,
        vnext_base=args.vnext_base,
        session_prod=args.session_prod,
        session_vnext=args.session_vnext,
        timeout=args.timeout,
    )

    print(format_report(report))

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(_report_to_json(report), f, indent=2, ensure_ascii=False)
        print(f"\nJSON report written: {args.json_out}")

    # Exit code: 0 only if both sides ok AND contents match.
    if report.prod.ok and report.vnext.ok:
        return 0 if report.contents_match else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
