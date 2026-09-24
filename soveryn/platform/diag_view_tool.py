"""house_diag — read-only diagnostic terminal view for citizens (2026-09-24).

Jon's call: citizens should SEE when something is fixed, not stay blocked on
verification they have no terminal for. Aetheria carried "SearXNG repair"
open for weeks because one `curl` would have shown it healthy; Scout repeats
caveats because she cannot re-check a source. Verification is the missing
half of the citizen loop.

This is terminal VIEW, not edit. The mechanism, not documentation:

  1. Fixed argv allowlist — no shell, no pipes, no `bash -c`. Arguments are
     strictly validated (unit names, ports, line counts, paths) and every
     execution is argv-only.
  2. curl is pinned to 127.0.0.1 — citizens can probe house services, never
     the internet (web_fetch/scout exists for that, with its own gates).
  3. Paths must resolve under an allowed house root. `.ssh`, `.env`,
     `*secret*`, and `*.key` are refused outright.
  4. Read-only verbs only: status/is-active/list-units/list-timers, journalctl
     -n, ss -tlnp, df, ls/stat, tail -n, git log. No sudo. No writes anywhere.
  5. Every call is receipted to data/black_box/diag/ — same ledger discipline
     as kernel_run.

Output cap and timeout keep a misbehaving caller from stalling the wire.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from soveryn.config.loader import DEFAULT_DATA_ROOT
from soveryn.platform.tools.registry import ToolArgError, ToolSpec

DEFAULT_TIMEOUT_S = 10
MAX_OUTPUT_BYTES = 4096
MAX_LINES = 100

_UNIT_RE = re.compile(r"^[A-Za-z0-9_.@\\-]{1,64}\.(service|timer|target|socket)$")
_GIT_RE = re.compile(r"^[0-9a-f]{7,40}$")

#: Roots a citizen may inspect. Everything else is out of scope.
ALLOWED_ROOTS = (
    Path(DEFAULT_DATA_ROOT),
    Path.home() / "soveryn_vnext",
    Path.home() / "teammates",
    Path.home() / "soveryn_citizens",
    Path.home() / "soveryn_eyes",
)

#: Path fragments that are secrets, wherever they appear under the roots.
_DENY_FRAGMENTS = (".ssh", ".env", "secret", "credential", ".key", ".pem")

HOUSE_PORT_MIN, HOUSE_PORT_MAX = 1, 65535


def _receipt_dir() -> Path:
    return Path(DEFAULT_DATA_ROOT) / "black_box" / "diag"


def _write_receipt(*, run_id: str, action: str, argv: list[str], ok: bool) -> Path:
    _receipt_dir().mkdir(parents=True, exist_ok=True)
    path = _receipt_dir() / f"diag-{run_id}.jsonl"
    line = {
        "kind": "house_diag",
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "action": action,
        "argv": argv,
        "ok": ok,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def _run(argv: list[str]) -> str:
    proc = subprocess.run(  # noqa: S603 — argv is validated, no shell
        argv,
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT_S,
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()[:300]
        return f"[command failed: {' '.join(argv[:3])}…] {err}".strip()
    return out[:MAX_OUTPUT_BYTES]


def _validated_unit(raw: Any) -> str:
    unit = str(raw or "").strip()
    if not _UNIT_RE.match(unit):
        raise ToolArgError(
            "unit must be a systemd unit name like soveryn-searxng.service"
        )
    return unit


def _validated_port(raw: Any) -> int:
    try:
        port = int(raw)
    except (TypeError, ValueError):
        raise ToolArgError("port must be an integer") from None
    if not (HOUSE_PORT_MIN <= port <= HOUSE_PORT_MAX):
        raise ToolArgError(f"port out of range: {port}")
    return port


def _validated_lines(raw: Any) -> int:
    try:
        n = int(raw or 20)
    except (TypeError, ValueError):
        raise ToolArgError("lines must be an integer") from None
    return max(1, min(n, MAX_LINES))


def _validated_path(raw: Any) -> Path:
    p = Path(str(raw or "")).expanduser()
    if not p.is_absolute():
        raise ToolArgError("path must be absolute")
    resolved = p.resolve()
    if not any(
        resolved == root or root in resolved.parents for root in ALLOWED_ROOTS
    ):
        raise ToolArgError(f"path outside house roots: {resolved}")
    lowered = str(resolved).lower()
    if any(frag in lowered for frag in _DENY_FRAGMENTS):
        raise ToolArgError("refused: path looks like a secret location")
    return resolved


# ── actions ─────────────────────────────────────────────────────────────────
def diag_unit(unit_raw: Any, *, mode: str = "status") -> str:
    unit = _validated_unit(unit_raw)
    argv = ["systemctl", "--user", mode, unit]
    return _run(argv)


def diag_journal(unit_raw: Any, lines_raw: Any = None) -> str:
    unit = _validated_unit(unit_raw)
    n = _validated_lines(lines_raw)
    return _run(["journalctl", "--user", "-u", unit, "-n", str(n), "--no-pager"])


def diag_listeners() -> str:
    return _run(["ss", "-H", "-tlnp"])


def diag_http(port_raw: Any, path_raw: Any = None, *, body: bool = False) -> str:
    port = _validated_port(port_raw)
    path = str(path_raw or "/")
    if not path.startswith("/") or any(c in path for c in "\"' \t"):
        raise ToolArgError("path must start with / and contain no spaces/quotes")
    if body:
        argv = ["curl", "-fsS", "-m", str(DEFAULT_TIMEOUT_S), "-o", "-",
                f"http://127.0.0.1:{port}{path}"]
    else:
        # Status probe: the "is it actually up" check. Body fetch is opt-in.
        argv = ["curl", "-fsS", "-m", str(DEFAULT_TIMEOUT_S), "-o", "/dev/null",
                "-w", "HTTP %{http_code} %{content_type}",
                f"http://127.0.0.1:{port}{path}"]
    return _run(argv)


def diag_disk() -> str:
    return _run(["df", "-h", "--output=target,size,used,pcent", "-x", "tmpfs",
                 "-x", "devtmpfs"])


def diag_file(path_raw: Any, lines_raw: Any = None) -> str:
    p = _validated_path(path_raw)
    if p.is_dir():
        return _run(["ls", "-la", str(p)])
    n = _validated_lines(lines_raw)
    if not p.is_file():
        raise ToolArgError(f"no such file: {p}")
    return _run(["tail", "-n", str(n), str(p)])


def diag_gitlog(repo_raw: Any, lines_raw: Any = None) -> str:
    repo = _validated_path(repo_raw)
    gitdir = repo / ".git"
    if not gitdir.exists():
        raise ToolArgError(f"not a git repo: {repo}")
    n = _validated_lines(lines_raw)
    return _run(["git", "-C", str(repo), "log", "--oneline", "-n", str(n)])


# ── ToolSpec ────────────────────────────────────────────────────────────────
_ACTIONS = ("unit", "journal", "listeners", "http", "disk", "file", "gitlog")


def house_diag(action: str, args: Mapping[str, Any]) -> str:
    """Dispatch one allowlisted read-only diagnostic. Returns capped output."""
    if action == "unit":
        mode = "is-active" if args.get("mode") == "is-active" else "status"
        out = diag_unit(args.get("unit"), mode=mode)
    elif action == "journal":
        out = diag_journal(args.get("unit"), args.get("lines"))
    elif action == "listeners":
        out = diag_listeners()
    elif action == "http":
        out = diag_http(args.get("port"), args.get("path"), body=bool(args.get("body")))
    elif action == "disk":
        out = diag_disk()
    elif action == "file":
        out = diag_file(args.get("path"), args.get("lines"))
    elif action == "gitlog":
        out = diag_gitlog(args.get("repo"), args.get("lines"))
    else:
        raise ToolArgError(f"action must be one of: {', '.join(_ACTIONS)}")
    return out


def build_house_diag_tool(*, owner_agent: str) -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        action = str(args.get("action") or "").strip().lower()
        import uuid

        run_id = str(uuid.uuid4())[:8]
        argv_preview = f"{action}:{args.get('unit') or args.get('path') or args.get('port') or ''}"
        try:
            out = house_diag(action, args)
            _write_receipt(run_id=run_id, action=argv_preview, argv=[action], ok=True)
            return {"ok": True, "run_id": run_id, "output": out}
        except ToolArgError:
            raise
        except subprocess.TimeoutExpired:
            _write_receipt(run_id=run_id, action=argv_preview, argv=[action], ok=False)
            raise ToolArgError(f"command timed out after {DEFAULT_TIMEOUT_S}s") from None
        except Exception as exc:  # noqa: BLE001 — report, never crash the wire
            _write_receipt(run_id=run_id, action=argv_preview, argv=[action], ok=False)
            return {"ok": False, "run_id": run_id, "error": str(exc)[:300]}

    return ToolSpec(
        name="house_diag",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(_ACTIONS),
                    "description": (
                        "unit = systemctl status/is-active; journal = recent unit logs; "
                        "listeners = ss -tlnp; http = curl 127.0.0.1:PORT (localhost "
                        "only); disk = df -h; file = ls dir or tail file (house roots "
                        "only); gitlog = git log --oneline."
                    ),
                },
                "unit": {"type": "string", "description": "systemd unit name, e.g. soveryn-searxng.service"},
                "lines": {"type": "integer", "description": "line count (default 20, max 100)"},
                "port": {"type": "integer", "description": "http: localhost port"},
                "body": {"type": "boolean", "description": "http: fetch response body instead of status line (capped)"},
                "path": {"type": "string", "description": "http: URL path (default /); file: absolute path under house roots; gitlog: repo path"},
                "mode": {"type": "string", "enum": ["status", "is-active"], "description": "unit: default status"},
            },
            "required": ["action"],
        },
        description=(
            "Read-only host diagnostics for verifying fixes yourself: systemd "
            "unit status, recent logs, listening ports, localhost HTTP probes, "
            "disk, file tails, git logs. Allowlist only — no shell, no writes, "
            "no sudo, curl pinned to 127.0.0.1, secrets paths refused. "
            "Receipted to data/black_box/diag/."
        ),
        handler=handler,
    )
