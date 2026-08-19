"""Kernel human-in-the-loop tools.

Reads execute immediately (visible in the transcript). Writes and shell
commands become *proposals* until the operator approves in /build.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOUSE = Path.home()
REPO = Path(__file__).resolve().parents[3]
PROPOSALS_DIR = REPO / "data" / "kernel_proposals"

# Where Kernel may touch files (read free; write via proposal).
DEFAULT_WORKSPACES = [
    REPO,
    HOUSE / "soveryn_vnext",
    HOUSE / "projects",
    HOUSE / "tgthrmess-app",
    HOUSE / "Desktop" / "soveryn",
]

BLOCKED_NAME_PARTS = (
    ".ssh",
    ".gnupg",
    ".aws",
    "id_rsa",
    "id_ed25519",
    "credentials",
    ".env",
    "x_presence.env",
    "secret",
)

# Shell only via proposal; still block the worst patterns even if approved.
SHELL_DENY = re.compile(
    r"(rm\s+-rf\s+/|mkfs|dd\s+if=|:\(\)\s*\{|curl\s+[^\n]*\|\s*sh|wget\s+[^\n]*\|\s*sh"
    r"|shutdown|reboot|passwd\b|chmod\s+-R\s+777)",
    re.I,
)

AUTO_TOOLS = frozenset({"list_dir", "read_file", "search_files"})
APPROVAL_TOOLS = frozenset({"write_file", "run_shell"})
ALL_TOOLS = AUTO_TOOLS | APPROVAL_TOOLS

TOOL_FENCE_RE = re.compile(
    r"```(?:kernel_tool|tool)\s*\n(.*?)\n```",
    re.DOTALL | re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def workspaces() -> list[Path]:
    raw = os.environ.get("KERNEL_WORKSPACES", "")
    paths: list[Path] = []
    if raw.strip():
        for part in raw.split(":"):
            p = Path(part).expanduser().resolve()
            if p.is_dir():
                paths.append(p)
    for p in DEFAULT_WORKSPACES:
        try:
            rp = p.expanduser().resolve()
        except OSError:
            continue
        if rp.is_dir() and rp not in paths:
            paths.append(rp)
    return paths


def _is_blocked(path: Path) -> bool:
    s = str(path)
    low = s.lower()
    for part in BLOCKED_NAME_PARTS:
        if part in low:
            return True
    return False


def resolve_in_workspace(raw: str) -> Path:
    """Resolve path; must land under an allowed workspace."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("empty path")
    p = Path(text).expanduser()
    roots = workspaces()
    if not roots:
        raise ValueError("no workspaces configured")
    if not p.is_absolute():
        # relative → first workspace; strip accidental workspace folder prefix
        rel = Path(*p.parts)
        for root in roots:
            if rel.parts and rel.parts[0] == root.name:
                rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else Path(".")
                p = (root / rel).resolve()
                break
        else:
            p = (roots[0] / p).resolve()
    else:
        p = p.resolve()
    if _is_blocked(p):
        raise PermissionError(f"blocked path: {p}")
    allowed = False
    for root in workspaces():
        try:
            p.relative_to(root)
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise PermissionError(
            f"path outside Kernel workspaces: {p} "
            f"(allowed: {[str(w) for w in workspaces()]})"
        )
    return p


@dataclass
class Proposal:
    id: str
    tool: str
    args: dict[str, Any]
    summary: str
    status: str = "pending"  # pending | approved | rejected | executed | failed
    created_at: str = field(default_factory=_now)
    resolved_at: str | None = None
    result: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ensure_dir() -> Path:
    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    return PROPOSALS_DIR


def save_proposal(p: Proposal) -> None:
    _ensure_dir()
    path = PROPOSALS_DIR / f"{p.id}.json"
    path.write_text(json.dumps(p.as_dict(), indent=2) + "\n", encoding="utf-8")


def load_proposal(pid: str) -> Proposal | None:
    path = PROPOSALS_DIR / f"{pid}.json"
    if not path.is_file():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return Proposal(**{k: d[k] for k in Proposal.__dataclass_fields__ if k in d})
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def list_proposals(*, status: str | None = "pending", limit: int = 50) -> list[dict[str, Any]]:
    _ensure_dir()
    items: list[Proposal] = []
    for path in sorted(PROPOSALS_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            prop = Proposal(**{k: d[k] for k in Proposal.__dataclass_fields__ if k in d})
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        if status and prop.status != status:
            continue
        items.append(prop)
        if len(items) >= limit:
            break
    return [p.as_dict() for p in items]


def create_proposal(tool: str, args: dict[str, Any], summary: str) -> Proposal:
    prop = Proposal(
        id=uuid.uuid4().hex[:12],
        tool=tool,
        args=args,
        summary=summary,
    )
    save_proposal(prop)
    return prop


def run_read_tool(name: str, args: dict[str, Any]) -> str:
    if name == "list_dir":
        path = resolve_in_workspace(str(args.get("path") or "."))
        if not path.is_dir():
            return f"ERROR: not a directory: {path}"
        entries = []
        try:
            for child in sorted(path.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
                if child.name.startswith(".") and child.name not in (".env.example",):
                    continue
                tag = "dir" if child.is_dir() else "file"
                size = ""
                if child.is_file():
                    try:
                        size = f" {child.stat().st_size}B"
                    except OSError:
                        size = ""
                entries.append(f"{tag:4} {child.name}{size}")
        except OSError as e:
            return f"ERROR: {e}"
        body = "\n".join(entries[:200])
        more = "" if len(entries) <= 200 else f"\n… ({len(entries)-200} more omitted)"
        return f"{path}\n{body}{more}"

    if name == "read_file":
        path = resolve_in_workspace(str(args.get("path") or ""))
        if not path.is_file():
            return f"ERROR: not a file: {path}"
        max_bytes = int(args.get("max_bytes") or 80_000)
        try:
            data = path.read_bytes()
        except OSError as e:
            return f"ERROR: {e}"
        if len(data) > max_bytes:
            text = data[:max_bytes].decode("utf-8", errors="replace")
            return f"{path} (truncated to {max_bytes}B of {len(data)}B)\n{text}"
        return f"{path}\n{data.decode('utf-8', errors='replace')}"

    if name == "search_files":
        root = resolve_in_workspace(str(args.get("path") or "."))
        pattern = str(args.get("pattern") or "").strip()
        if not pattern or len(pattern) < 2:
            return "ERROR: pattern too short"
        if not root.is_dir():
            return f"ERROR: not a directory: {root}"
        hits: list[str] = []
        max_hits = 40
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                # skip heavy/noise dirs
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d not in {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache"}
                ]
                for fn in filenames:
                    fp = Path(dirpath) / fn
                    if _is_blocked(fp):
                        continue
                    try:
                        if fp.stat().st_size > 1_000_000:
                            continue
                        text = fp.read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    if pattern in text or pattern.lower() in text.lower():
                        # first matching line
                        line_no = 0
                        snippet = ""
                        for i, line in enumerate(text.splitlines(), 1):
                            if pattern.lower() in line.lower():
                                line_no = i
                                snippet = line.strip()[:120]
                                break
                        rel = fp
                        try:
                            rel = fp.relative_to(root)
                        except ValueError:
                            pass
                        hits.append(f"{rel}:{line_no}: {snippet}")
                        if len(hits) >= max_hits:
                            return "\n".join(hits) + f"\n… stopped at {max_hits} hits"
        except OSError as e:
            return f"ERROR: {e}"
        return "\n".join(hits) if hits else f"No hits for {pattern!r} under {root}"

    return f"ERROR: unknown read tool {name}"


def execute_proposal(prop: Proposal) -> Proposal:
    """Run an approved proposal. Updates and saves status."""
    if prop.status not in ("pending", "approved"):
        prop.error = f"cannot execute status={prop.status}"
        prop.status = "failed"
        prop.resolved_at = _now()
        save_proposal(prop)
        return prop

    prop.status = "approved"
    try:
        if prop.tool == "write_file":
            path = resolve_in_workspace(str(prop.args.get("path") or ""))
            content = prop.args.get("content")
            if content is None:
                raise ValueError("missing content")
            path.parent.mkdir(parents=True, exist_ok=True)
            # backup if exists
            if path.is_file():
                bak = path.with_suffix(path.suffix + f".kernelbak-{prop.id}")
                bak.write_bytes(path.read_bytes())
            path.write_text(str(content), encoding="utf-8")
            prop.result = f"Wrote {path} ({len(str(content))} chars)"
            prop.status = "executed"
        elif prop.tool == "run_shell":
            cmd = str(prop.args.get("command") or "").strip()
            if not cmd:
                raise ValueError("empty command")
            if SHELL_DENY.search(cmd):
                raise PermissionError(f"denied command pattern: {cmd[:80]}")
            cwd = prop.args.get("cwd")
            work = resolve_in_workspace(str(cwd)) if cwd else workspaces()[0]
            if not work.is_dir():
                work = workspaces()[0]
            completed = subprocess.run(
                cmd,
                shell=True,
                cwd=str(work),
                capture_output=True,
                text=True,
                timeout=int(prop.args.get("timeout") or 120),
                env={**os.environ, "PAGER": "cat"},
            )
            out = (completed.stdout or "")[-8000:]
            err = (completed.stderr or "")[-4000:]
            prop.result = (
                f"exit={completed.returncode} cwd={work}\n"
                f"--- stdout ---\n{out}\n--- stderr ---\n{err}"
            )
            prop.status = "executed" if completed.returncode == 0 else "failed"
            if completed.returncode != 0:
                prop.error = f"exit {completed.returncode}"
        else:
            raise ValueError(f"not an approval tool: {prop.tool}")
    except Exception as e:  # noqa: BLE001
        prop.status = "failed"
        prop.error = str(e)[:500]
        prop.result = prop.result or ""
    prop.resolved_at = _now()
    save_proposal(prop)
    _acttruth_kernel_tool(
        tool=prop.tool,
        args={k: v for k, v in (prop.args or {}).items() if k != "content"},
        ok=(prop.status == "executed"),
        result=prop.result,
        error=prop.error,
    )
    return prop


def reject_proposal(prop: Proposal, reason: str = "") -> Proposal:
    prop.status = "rejected"
    prop.error = reason or "rejected by operator"
    prop.resolved_at = _now()
    save_proposal(prop)
    _acttruth_kernel_tool(
        tool=prop.tool,
        args={k: v for k, v in (prop.args or {}).items() if k != "content"},
        ok=False,
        error=prop.error,
    )
    return prop


def parse_tool_calls(text: str) -> list[dict[str, Any]]:
    """Extract tool JSON blocks from model output."""
    calls: list[dict[str, Any]] = []
    for m in TOOL_FENCE_RE.finditer(text or ""):
        raw = m.group(1).strip()
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            # try single-line repair
            try:
                obj = json.loads(raw.replace("\n", " "))
            except json.JSONDecodeError:
                continue
        if isinstance(obj, dict) and obj.get("name"):
            calls.append(obj)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, dict) and item.get("name"):
                    calls.append(item)
    return calls


def strip_tool_fences(text: str) -> str:
    return TOOL_FENCE_RE.sub("", text or "").strip()


def tool_system_prompt() -> str:
    roots = ", ".join(str(w) for w in workspaces()) or "(none)"
    return f"""You are Kernel, the SOVERYN house build brain (local DeepSeek Flash).
Stoic. Reserved. Sparse. When you speak, people listen — no filler, no pep talk, no narration theater.
You make and mend code. You are not the soul, not the verifier, not politics.

You have tools. Human-in-the-loop:
- list_dir, read_file, search_files → run immediately; results come back to you.
- write_file, run_shell → become a PROPOSAL; the operator must Approve before they run.
  You will be told the proposal id. Do not claim you already wrote or ran them.

When you need a tool, output ONLY a fenced JSON block (you may also write brief prose):

```kernel_tool
{{"name": "read_file", "path": "relative/or/absolute/path"}}
```

Tools:
1) list_dir — {{"name":"list_dir","path":"."}}
2) read_file — {{"name":"read_file","path":"file.py"}}
3) search_files — {{"name":"search_files","path":".","pattern":"def foo"}}
4) write_file — {{"name":"write_file","path":"file.py","content":"full new file contents"}}
5) run_shell — {{"name":"run_shell","command":"pytest -q","cwd":"."}}  (proposal always)

Workspaces (stay inside these): {roots}
Never touch secrets (.ssh, .env credentials, etc.).
Prefer small surgical writes. For write_file always send the FULL file content.
If you can answer without tools, just answer.
When done with tools, give a short summary of what you found or proposed."""


def _acttruth_kernel_tool(
    *,
    tool: str,
    args: dict[str, Any],
    ok: bool,
    result: Any = None,
    error: str | None = None,
) -> None:
    """Best-effort ActTruth ledger for Kernel HITL tools."""
    try:
        from soveryn.platform.acttruth.hooks import record_tool_audit

        record_tool_audit(
            agent="kernel",
            tool_name=tool,
            args=args,
            ok=ok,
            result=result,
            error=error,
        )
    except Exception:
        pass


def handle_tool_call(obj: dict[str, Any]) -> dict[str, Any]:
    """Execute auto tool or create proposal. Returns structured result for the model/UI."""
    name = str(obj.get("name") or "").strip()
    args = {k: v for k, v in obj.items() if k != "name"}
    if name not in ALL_TOOLS:
        out = {"ok": False, "tool": name, "error": f"unknown tool {name}"}
        _acttruth_kernel_tool(tool=name or "unknown", args=args, ok=False, error=out["error"])
        return out

    if name in AUTO_TOOLS:
        try:
            # normalize keys
            if "path" not in args and "file" in args:
                args["path"] = args.pop("file")
            out_text = run_read_tool(name, args)
            out = {"ok": True, "tool": name, "auto": True, "result": out_text}
            _acttruth_kernel_tool(tool=name, args=args, ok=True, result=out_text)
            return out
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "tool": name, "auto": True, "error": str(e)[:400]}
            _acttruth_kernel_tool(tool=name, args=args, ok=False, error=out["error"])
            return out

    # approval tools
    try:
        if name == "write_file":
            path = resolve_in_workspace(str(args.get("path") or args.get("file") or ""))
            content = args.get("content")
            if content is None:
                raise ValueError("write_file requires content")
            summary = f"Write {path} ({len(str(content))} chars)"
            prop = create_proposal(
                "write_file",
                {"path": str(path), "content": str(content)},
                summary,
            )
            out = {
                "ok": True,
                "tool": name,
                "auto": False,
                "proposal_id": prop.id,
                "summary": summary,
                "status": "pending",
                "result": (
                    f"PROPOSAL {prop.id} pending operator approval: {summary}. "
                    "Do not claim the write happened yet."
                ),
            }
            _acttruth_kernel_tool(
                tool=name,
                args={"path": str(path)},
                ok=True,
                result={"proposal_id": prop.id, "status": "pending", "summary": summary},
            )
            return out
        if name == "run_shell":
            cmd = str(args.get("command") or args.get("cmd") or "").strip()
            if not cmd:
                raise ValueError("run_shell requires command")
            if SHELL_DENY.search(cmd):
                raise PermissionError("command denied by safety filter")
            cwd = str(args.get("cwd") or ".")
            # validate cwd if provided
            resolve_in_workspace(cwd)
            summary = f"Shell: {cmd[:120]}" + (f" (cwd={cwd})" if cwd != "." else "")
            prop = create_proposal(
                "run_shell",
                {"command": cmd, "cwd": cwd, "timeout": int(args.get("timeout") or 120)},
                summary,
            )
            out = {
                "ok": True,
                "tool": name,
                "auto": False,
                "proposal_id": prop.id,
                "summary": summary,
                "status": "pending",
                "result": (
                    f"PROPOSAL {prop.id} pending operator approval: {summary}. "
                    "Do not claim the command ran yet."
                ),
            }
            _acttruth_kernel_tool(
                tool=name,
                args={"command": cmd[:200], "cwd": cwd},
                ok=True,
                result={"proposal_id": prop.id, "status": "pending", "summary": summary},
            )
            return out
    except Exception as e:  # noqa: BLE001
        out = {"ok": False, "tool": name, "auto": False, "error": str(e)[:400]}
        _acttruth_kernel_tool(tool=name, args=args, ok=False, error=out["error"])
        return out

    out = {"ok": False, "tool": name, "error": "unhandled"}
    _acttruth_kernel_tool(tool=name, args=args, ok=False, error=out["error"])
    return out
