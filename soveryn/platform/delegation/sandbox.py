"""Bubblewrap sandbox for delegated code execution (2026-07-17).

Delegated execution runs code that Scotty writes or selects — during his loop
(``run_command`` / ``run_pytest``) and at the acceptance gate. Every one of
those paths is wrapped in bubblewrap by this module so the executed code:

  - has NO network (``--unshare-net``);
  - sees a READ-ONLY host filesystem (``--ro-bind / /``) EXCEPT the task
    worktree, which is writable (``--bind <worktree>``);
  - gets a fresh, ephemeral tmpfs ``/tmp`` (also serving as ``HOME``), discarded
    when the sandbox exits;
  - runs in unshared pid/ipc/uts namespaces, dies with its parent, no TTY.

Callers FAIL CLOSED: if bwrap is unavailable they refuse to run rather than
execute Scotty's code unsandboxed on the host. Requires bwrap to be usable
(setuid, or unprivileged user namespaces permitted).
"""
from __future__ import annotations

import shutil
from pathlib import Path

#: Resolved once. None if bwrap isn't on PATH — callers must treat that as
#: "refuse to run", never "run unsandboxed".
BWRAP: str | None = shutil.which("bwrap")

#: HOME inside the sandbox — the ephemeral tmpfs, so caches/dotfiles vanish.
SANDBOX_HOME = "/tmp"


class SandboxUnavailable(RuntimeError):
    """bwrap is not available; the caller must refuse to run."""


class Sandbox:
    """Build a fail-closed bubblewrap argv for one worktree."""

    @staticmethod
    def dest_dir_flags(worktree_path: str) -> list[str]:
        """Recreate dest parents after ``--tmpfs /tmp`` so a /tmp worktree binds.

        pytest's ``tmp_path`` lives under ``/tmp/pytest-of-…``. ``--tmpfs /tmp``
        hides those parents; ``--bind`` then cannot create the mount point and
        acceptance fails even though bwrap is installed.
        """
        flags: list[str] = []
        tmp = Path("/tmp")
        parent = Path(worktree_path).resolve().parent
        try:
            rel = parent.relative_to(tmp)
        except ValueError:
            return flags
        acc = tmp
        for part in rel.parts:
            acc = acc / part
            flags.extend(["--dir", str(acc)])
        return flags

    @staticmethod
    def argv(worktree_path: str, argv: list[str]) -> list[str]:
        if BWRAP is None:
            raise SandboxUnavailable(
                "bwrap (bubblewrap) not found on PATH; refusing to run delegated "
                "code unsandboxed."
            )
        wt = str(Path(worktree_path).resolve())
        return [
            BWRAP,
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            *Sandbox.dest_dir_flags(wt),
            "--bind", wt, wt,
            "--unshare-net",
            "--unshare-pid", "--unshare-ipc", "--unshare-uts",
            "--die-with-parent", "--new-session",
            "--chdir", wt,
            "--",
            *argv,
        ]


def sandbox_argv(worktree_path: str, argv: list[str]) -> list[str]:
    """Prefix *argv* with a bubblewrap jail scoped to *worktree_path*.

    Raises :class:`SandboxUnavailable` if bwrap is missing — callers catch it and
    fail closed. The returned list is a full ``bwrap … -- <argv>`` command ready
    for ``subprocess.run``.
    """
    return Sandbox.argv(worktree_path, argv)
