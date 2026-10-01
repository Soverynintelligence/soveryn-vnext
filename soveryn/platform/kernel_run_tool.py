"""kernel_run — phone Messages ↔ CLI Kernel (read-and-report).

Phone Messages Kernel already has AgentLoop reads + run_aider/run_opencode.
This tool is the thin door into the *CLI* surface (`kernel` / soveryn-pi):

- status:   `kernel status` (non-mutating)
- receipts: recent black_box/kernel JSONL lines
- report:   `kernel -p` with Pi tools locked to read,grep,find,ls only

Every action returns receipt-per-claim lines + a run_id written under
data/black_box/kernel/. Mutate verbs in report prompts are refused.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import uuid
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from soveryn.platform.tools.registry import ToolArgError, ToolSpec

DEFAULT_REPO = Path.home() / "soveryn_vnext"
ALLOWED_ROOTS: tuple[Path, ...] = (
    Path.home() / "soveryn_vnext",
    Path.home() / "soveryn_citizens" / "kernel",
)
# Read-only Pi tool surface — never bash/edit/write from phone-origin runs.
REPORT_TOOLS = "read,grep,find,ls"
MAX_PROMPT_CHARS = 4000
MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT_S = 180
LAUNCHER_NAMES = ("kernel", "soveryn-pi")

_MUTATE_RE = re.compile(
    r"\b(mend|patch|edit|write|apply|commit|push|sudo|chmod|chown|"
    r"rm\s+-|unlink|truncate|force-push|rebase|reset\s+--hard)\b"
    r"|/\.ssh\b|\.env\b|id_rsa|private[_\s-]?key",
    re.I,
)

Runner = Callable[..., subprocess.CompletedProcess[str]]


def _data_root() -> Path:
    raw = os.environ.get("SOVERYN_DATA_ROOT")
    if raw:
        return Path(raw)
    from soveryn.config.loader import DEFAULT_DATA_ROOT

    return Path(DEFAULT_DATA_ROOT)


def _black_box_kernel_dir() -> Path:
    return _data_root() / "black_box" / "kernel"


def _timeout_s() -> int:
    raw = os.environ.get("SOVERYN_KERNEL_RUN_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return max(30, min(n, 600))


def resolve_repo(raw: str | None) -> Path:
    repo = Path(raw).expanduser() if (raw or "").strip() else DEFAULT_REPO
    try:
        repo = repo.resolve()
    except OSError as exc:
        raise ToolArgError(f"repo path unreadable: {exc}") from exc
    for root in ALLOWED_ROOTS:
        try:
            root_r = root.expanduser().resolve()
        except OSError:
            root_r = root.expanduser()
        if repo == root_r or root_r in repo.parents:
            if not repo.is_dir():
                raise ToolArgError(f"repo is not a directory: {repo}")
            return repo
    raise ToolArgError(
        f"repo must be under {sorted(str(p) for p in ALLOWED_ROOTS)}, got {str(repo)!r}"
    )


def find_launcher() -> str | None:
    env = os.environ.get("SOVERYN_KERNEL_BIN")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    for name in LAUNCHER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    home_bin = Path.home() / "bin" / "kernel"
    if home_bin.is_file() and os.access(home_bin, os.X_OK):
        return str(home_bin)
    script = Path.home() / "soveryn_vnext" / "scripts" / "soveryn-pi"
    if script.is_file() and os.access(script, os.X_OK):
        return str(script)
    return None


def _write_receipt(*, run_id: str, action: str, payload: dict[str, Any]) -> Path:
    dest_dir = _black_box_kernel_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"cli-{run_id}.jsonl"
    line = {
        "kind": "kernel_run",
        "run_id": run_id,
        "action": action,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "origin": "messages",
        **payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    return path


def _verdict_lines(claims: list[tuple[str, bool, str]]) -> list[str]:
    """Receipt-per-claim: PASS/FAIL lines the phone can show verbatim."""
    out: list[str] = []
    for name, ok, detail in claims:
        tag = "PASS" if ok else "FAIL"
        out.append(f"[{tag}] {name}: {detail}")
    return out


def run_status(*, runner: Runner | None = None) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    launcher = find_launcher()
    claims: list[tuple[str, bool, str]] = []
    if not launcher:
        claims.append(("launcher", False, "kernel / soveryn-pi not found on PATH"))
        receipt = _write_receipt(
            run_id=run_id,
            action="status",
            payload={"ok": False, "claims": claims, "output": ""},
        )
        return {
            "ok": False,
            "action": "status",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "launcher_missing",
        }

    run = runner or subprocess.run
    try:
        proc = run(
            [launcher, "status"],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(DEFAULT_REPO),
        )
    except subprocess.TimeoutExpired:
        claims.append(("kernel status", False, "timed out after 60s"))
        receipt = _write_receipt(
            run_id=run_id,
            action="status",
            payload={"ok": False, "claims": claims, "output": ""},
        )
        return {
            "ok": False,
            "action": "status",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "timeout",
        }
    except OSError as exc:
        claims.append(("kernel status", False, str(exc)))
        receipt = _write_receipt(
            run_id=run_id,
            action="status",
            payload={"ok": False, "claims": claims, "output": ""},
        )
        return {
            "ok": False,
            "action": "status",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "spawn_error",
        }

    text = ((proc.stdout or "") + (proc.stderr or "")).strip()
    ok = proc.returncode == 0 and "READY" in text
    claims.append(
        (
            "kernel status",
            ok,
            f"exit={proc.returncode}" + ("; READY" if ok else "; not READY"),
        )
    )
    # Flash-Next live?
    flash_ok = "flash" in text.lower() and "OK" in text and ":8888" in text
    claims.append(
        (
            "flash-next :8888",
            flash_ok,
            "listed OK on status HUD" if flash_ok else "not confirmed OK",
        )
    )
    receipt = _write_receipt(
        run_id=run_id,
        action="status",
        payload={
            "ok": ok,
            "claims": [{"name": n, "ok": o, "detail": d} for n, o, d in claims],
            "output": text[:MAX_OUTPUT_CHARS],
            "exit_code": proc.returncode,
        },
    )
    return {
        "ok": ok,
        "action": "status",
        "run_id": run_id,
        "receipt_path": str(receipt),
        "verdict": _verdict_lines(claims),
        "output": text[:MAX_OUTPUT_CHARS],
        "finish_reason": "stop" if ok else "status_not_ready",
    }


def run_receipts(*, limit: int = 5) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    limit = max(1, min(int(limit or 5), 20))
    root = _black_box_kernel_dir()
    claims: list[tuple[str, bool, str]] = []
    if not root.is_dir():
        claims.append(("black_box/kernel", False, f"missing dir {root}"))
        receipt = _write_receipt(
            run_id=run_id,
            action="receipts",
            payload={"ok": False, "claims": claims, "entries": []},
        )
        return {
            "ok": False,
            "action": "receipts",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "entries": [],
            "finish_reason": "missing_black_box",
        }

    files = sorted(root.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    entries: list[dict[str, Any]] = []
    for path in files[:limit]:
        try:
            # last non-empty line
            last = ""
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        last = line.strip()
            if not last:
                continue
            row = json.loads(last)
            fr = str(row.get("finish_reason") or "")
            # Never paint tool_round_limit as success
            successish = fr in ("", "stop", "stop_sequence") and not row.get(
                "telemetry", {}
            ).get("tool_round_limit_hit")
            if fr == "tool_round_limit" or row.get("telemetry", {}).get(
                "tool_round_limit_hit"
            ):
                successish = False
            entries.append(
                {
                    "file": path.name,
                    "path": str(path),
                    "finish_reason": fr or row.get("action"),
                    "ok": bool(successish) if fr else bool(row.get("ok", True)),
                    "started_at": row.get("started_at"),
                    "run_id": row.get("run_id") or path.stem,
                    "snippet": str(row.get("final_content") or row.get("output") or "")[
                        :240
                    ],
                }
            )
        except (OSError, json.JSONDecodeError) as exc:
            entries.append({"file": path.name, "ok": False, "error": str(exc)})

    claims.append(
        ("black_box/kernel", True, f"{len(entries)} recent receipt(s) under {root}")
    )
    receipt = _write_receipt(
        run_id=run_id,
        action="receipts",
        payload={"ok": True, "claims": claims, "entries": entries},
    )
    return {
        "ok": True,
        "action": "receipts",
        "run_id": run_id,
        "receipt_path": str(receipt),
        "verdict": _verdict_lines(claims),
        "entries": entries,
        "finish_reason": "stop",
    }


def run_report(
    prompt: str,
    *,
    repo: Path | None = None,
    launcher: str | None = None,
    timeout_s: int | None = None,
    runner: Runner | None = None,
) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    text = (prompt or "").strip()
    if not text:
        raise ToolArgError("prompt is required for action=report")
    if len(text) > MAX_PROMPT_CHARS:
        raise ToolArgError(f"prompt exceeds {MAX_PROMPT_CHARS} chars")
    if _MUTATE_RE.search(text):
        claims = [
            (
                "mutate_gate",
                False,
                "report is read-and-report only — refused mend/write/sudo/secrets language",
            )
        ]
        receipt = _write_receipt(
            run_id=run_id,
            action="report",
            payload={"ok": False, "claims": claims, "prompt": text[:200]},
        )
        return {
            "ok": False,
            "action": "report",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "mutate_refused",
        }

    cwd = repo or resolve_repo(None)
    bin_path = launcher or find_launcher()
    claims: list[tuple[str, bool, str]] = []
    if not bin_path:
        claims.append(("launcher", False, "kernel / soveryn-pi not found"))
        receipt = _write_receipt(
            run_id=run_id,
            action="report",
            payload={"ok": False, "claims": claims},
        )
        return {
            "ok": False,
            "action": "report",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "launcher_missing",
        }

    framed = (
        "[ORIGIN=messages phone] READ-AND-REPORT ONLY. "
        "Tools are locked to read,grep,find,ls. "
        "No edits, no bash, no secrets, no leaving the working tree. "
        "Answer with evidence. If you cannot verify a claim, say FAIL.\n\n"
        f"{text}"
    )
    # Pass --tools after -- so pack does not re-inject bash/edit/write.
    cmd = [
        bin_path,
        "-p",
        framed,
        "--",
        "--tools",
        REPORT_TOOLS,
    ]
    t_s = timeout_s if timeout_s is not None else _timeout_s()
    run = runner or subprocess.run
    try:
        proc = run(
            cmd,
            capture_output=True,
            text=True,
            timeout=t_s,
            cwd=str(cwd),
            env={
                **os.environ,
                "SOVERYN_HARNESS": "kernel",
                # Keep phone-origin runs offline-ish for print if set by house.
            },
        )
    except subprocess.TimeoutExpired:
        claims.append(("kernel -p", False, f"timed out after {t_s}s"))
        receipt = _write_receipt(
            run_id=run_id,
            action="report",
            payload={"ok": False, "claims": claims, "cmd": cmd[:3]},
        )
        return {
            "ok": False,
            "action": "report",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "timeout",
        }
    except OSError as exc:
        claims.append(("kernel -p", False, str(exc)))
        receipt = _write_receipt(
            run_id=run_id,
            action="report",
            payload={"ok": False, "claims": claims},
        )
        return {
            "ok": False,
            "action": "report",
            "run_id": run_id,
            "receipt_path": str(receipt),
            "verdict": _verdict_lines(claims),
            "output": "",
            "finish_reason": "spawn_error",
        }

    out = ((proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")).strip()
    out = out[:MAX_OUTPUT_CHARS]
    # Heuristic: Pi sometimes exits 0 with empty body after tool_round_limit-like stalls
    empty = not out.strip()
    ok = proc.returncode == 0 and not empty
    finish_reason = "stop" if ok else ("empty_generation" if empty else "cli_nonzero")
    # Detect tool_round_limit / limit language in output — never success
    if re.search(r"tool_round_limit(_hit)?", out, re.I):
        ok = False
        finish_reason = "tool_round_limit"
        claims.append(
            ("tool_round_limit", False, "CLI output mentions tool_round_limit — not success")
        )
    claims.append(
        (
            "kernel -p report",
            ok,
            f"exit={proc.returncode} chars={len(out)} tools={REPORT_TOOLS}",
        )
    )
    receipt = _write_receipt(
        run_id=run_id,
        action="report",
        payload={
            "ok": ok,
            "claims": [{"name": n, "ok": o, "detail": d} for n, o, d in claims],
            "output": out,
            "exit_code": proc.returncode,
            "finish_reason": finish_reason,
            "repo": str(cwd),
            "tools": REPORT_TOOLS,
        },
    )
    return {
        "ok": ok,
        "action": "report",
        "run_id": run_id,
        "receipt_path": str(receipt),
        "verdict": _verdict_lines(claims),
        "output": out,
        "finish_reason": finish_reason,
        "repo": str(cwd),
    }


def build_kernel_run_tool(*, owner_agent: str = "kernel") -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        action = (args.get("action") or "status").strip().lower()
        if action not in {"status", "receipts", "report"}:
            raise ToolArgError("action must be status, receipts, or report")
        if action == "status":
            return run_status()
        if action == "receipts":
            return run_receipts(limit=int(args.get("limit") or 5))
        prompt = args.get("prompt")
        if not isinstance(prompt, str):
            raise ToolArgError("prompt (string) required for action=report")
        repo_raw = args.get("repo")
        repo = resolve_repo(repo_raw if isinstance(repo_raw, str) else None)
        return run_report(prompt, repo=repo)

    return ToolSpec(
        name="kernel_run",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["status", "receipts", "report"],
                    "description": (
                        "status = CLI kernel status HUD; "
                        "receipts = recent black_box/kernel lines; "
                        "report = read-only kernel -p (tools: read,grep,find,ls)."
                    ),
                },
                "prompt": {
                    "type": "string",
                    "description": "Required for report. Read-and-report question only.",
                },
                "repo": {
                    "type": "string",
                    "description": "Optional cwd under house roots for report.",
                },
                "limit": {
                    "type": "integer",
                    "description": "receipts: how many recent files (default 5).",
                },
            },
            "required": ["action"],
        },
        description=(
            "Talk to Kernel CLI from Messages. status/receipts are local reads; "
            "report runs kernel -p with read-only tools. Returns verdict lines + "
            "run_id → data/black_box/kernel/. Never treat tool_round_limit as success. "
            "Phone-origin: no .ssh/sudo/leave-tree privilege."
        ),
        handler=handler,
    )
