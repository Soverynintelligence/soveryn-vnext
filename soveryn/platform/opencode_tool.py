"""Kernel's write harness from Messages — headless OpenCode on GLM.

AgentLoop stays read/search in Messages. Mends go through
``soveryn-opencode run --auto`` on Spark :8001.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from soveryn.platform.tools.registry import ToolArgError, ToolSpec

DEFAULT_REPO = Path.home() / "soveryn_vnext"
ALLOWED_ROOTS: tuple[Path, ...] = (
    Path.home() / "soveryn_vnext",
    Path.home() / "soveryn_citizens" / "kernel",
)
MAX_PROMPT_CHARS = 8000
MAX_OUTPUT_CHARS = 8000
DEFAULT_TIMEOUT_S = 600
LAUNCHER_NAMES = ("soveryn-opencode",)


def _timeout_s() -> int:
    raw = os.environ.get("SOVERYN_OPENCODE_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_S
    try:
        n = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_S
    return max(30, min(n, 1800))


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
    env = os.environ.get("SOVERYN_OPENCODE_BIN")
    if env and Path(env).is_file() and os.access(env, os.X_OK):
        return env
    for name in LAUNCHER_NAMES:
        found = shutil.which(name)
        if found:
            return found
    script = Path.home() / "soveryn_vnext" / "scripts" / "soveryn-opencode"
    if script.is_file() and os.access(script, os.X_OK):
        return str(script)
    return None


def opencode_argv(launcher: str, repo: Path, prompt: str) -> list[str]:
    return [launcher, "run", "--auto", "--dir", str(repo), prompt]


def run_opencode(
    prompt: str,
    *,
    repo: Path,
    launcher: str,
    timeout_s: int,
    runner=None,
    wait: bool = True,
    follow_of: str | None = None,
    store=None,
) -> dict[str, Any]:
    cmd = opencode_argv(launcher, repo, prompt)
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "local")
    if runner is not None:
        try:
            proc = runner(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                cwd=str(repo),
                env=env,
            )
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") + (exc.stderr or "")
            return {
                "ok": False,
                "error": f"opencode timed out after {timeout_s}s",
                "output": out[-MAX_OUTPUT_CHARS:],
                "repo": str(repo),
            }
        except OSError as exc:
            return {"ok": False, "error": f"opencode failed to start: {exc}", "repo": str(repo)}
        blob = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "output": blob[-MAX_OUTPUT_CHARS:],
            "repo": str(repo),
        }
    from soveryn.platform.kernel_jobs import get_store

    st = store or get_store()
    job = st.spawn(
        kind="opencode",
        prompt=prompt,
        repo=str(repo),
        cmd=cmd,
        cwd=str(repo),
        env=env,
        timeout_s=timeout_s,
        follow_of=follow_of,
    )
    if not wait:
        snap = st.snapshot(job)
        snap["ok"] = True
        snap["job"] = job
        return snap
    return st.wait(job.id)


def build_run_opencode_tool(*, owner_agent: str = "kernel") -> ToolSpec:
    def handler(args: Mapping[str, Any]) -> Any:
        prompt = args.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ToolArgError("prompt must be a non-empty string")
        text = prompt.strip()
        if len(text) > MAX_PROMPT_CHARS:
            raise ToolArgError(f"prompt exceeds {MAX_PROMPT_CHARS} characters")
        repo_raw = args.get("repo")
        if repo_raw is not None and not isinstance(repo_raw, str):
            raise ToolArgError("repo must be a string path")
        repo = resolve_repo(repo_raw)
        launcher = find_launcher()
        if launcher is None:
            return {
                "ok": False,
                "error": "soveryn-opencode not found on PATH",
                "repo": str(repo),
            }
        return run_opencode(
            text, repo=repo, launcher=launcher, timeout_s=_timeout_s()
        )

    return ToolSpec(
        name="run_opencode",
        owner=owner_agent,
        schema={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": (
                        "The mend. Concrete: files, expected behavior, how to "
                        "verify. OpenCode edits and runs on GLM :8001."
                    ),
                },
                "repo": {
                    "type": "string",
                    "description": (
                        "Working tree. Default ~/soveryn_vnext. Must be a "
                        "house repo (soveryn_vnext or kernel desk)."
                    ),
                },
            },
            "required": ["prompt"],
            "additionalProperties": False,
        },
        handler=handler,
        description=(
            "Short soveryn-opencode run --auto on GLM :8001. Prefer run_aider "
            "for real patches. Do not use this for a lookup."
        ),
    )
