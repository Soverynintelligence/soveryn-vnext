"""Dangerous-command classifier for the Desk Kernel (revamp phase 1, 2026-11-05).

Idea borrowed from Hermes Agent's tools/approval_detection.py (pattern lists:
"hardline" vs "ask"); this is SOVERYN's own code, nothing imported from Hermes.

classify(tool, args, repo_root) -> Verdict. Anything matched must wait for Jon's
click in the Command Center (/desk-gate). Bias: false positives are fine, false
negatives are not. Unknown/unparseable input is held.
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class Verdict:
    dangerous: bool
    rule: str = ""
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


SAFE = Verdict(False)

# (rule id, regex, human reason). Matched against the whole command string.
_PATTERNS: list[tuple[str, str, str]] = [
    ("sudo", r"(^|[\s;&|(`])(sudo|su|doas|pkexec)\b", "privilege escalation"),
    ("rm", r"(^|[\s;&|(`])rm\s", "file deletion"),
    ("delete-ops", r"(^|[\s;&|(`])(shred|unlink|rmdir|truncate|dd|mkfs(\.\w+)?|wipefs|fdisk|parted)\b", "destructive disk/file op"),
    ("find-delete", r"\bfind\b.*\s-(delete|exec\s+rm)\b", "find -delete"),
    ("git-push", r"\bgit\b(\s+-\S+(\s+\S+)?)*\s+push\b", "git push"),
    ("git-destructive", r"\bgit\b.*\s(reset\s+--hard|clean\s+-\w*f|checkout\s+--\s|checkout\s+\.|restore\s|branch\s+-D|rebase|filter-branch|filter-repo|stash\s+(drop|clear)|reflog\s+expire|gc\s+--prune|update-ref\s+-d|tag\s+-d|commit\s+--amend)", "destructive git"),
    ("git-force", r"\bgit\b.*\s(--force\b|-f\b|--force-with-lease)", "forced git op"),
    ("service", r"(^|[\s;&|(`])(systemctl|service|launchctl|supervisorctl|initctl)\b", "service control"),
    ("kill", r"(^|[\s;&|(`])(kill|pkill|killall|xkill)\b", "killing processes"),
    ("power", r"(^|[\s;&|(`])(shutdown|reboot|poweroff|halt)\b", "power control"),
    ("remote", r"(^|[\s;&|(`])(ssh|scp|rsync|sftp|mosh)\b", "remote host access (Sparks/Kernel)"),
    ("docker", r"(^|[\s;&|(`])(docker|podman|nerdctl|kubectl|helm)\b", "containers/cluster"),
    ("deploy", r"\b(wrangler\s+(deploy|publish|pages\s+deploy)|vercel|netlify\s+deploy|fly\s+deploy|flyctl|heroku|firebase\s+deploy|gcloud|aws\s|az\s|terraform\s+(apply|destroy)|pulumi\s+up|npm\s+publish|pnpm\s+publish|yarn\s+publish|twine\s+upload|gh\s+(release|pr\s+merge|repo\s+delete|workflow\s+run)|docker\s+push)\b", "deploy/publish"),
    ("tailscale", r"\btailscale\s+(funnel|serve|up|down|set|logout)\b", "tailscale exposure"),
    ("cron", r"(^|[\s;&|(`])(crontab|at)\s", "scheduling"),
    ("perm", r"(^|[\s;&|(`])(chmod|chown|chgrp|setfacl)\s+(-\w*R|--recursive)", "recursive permission change"),
    ("pipe-shell", r"(curl|wget)\b[^|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe download to shell"),
    ("pkg", r"(^|[\s;&|(`])(apt|apt-get|dnf|yum|pacman|snap|brew)\s+(install|remove|purge|upgrade)|\bpip3?\s+(install|uninstall)|\bnpm\s+(i|install|uninstall)\s+-g\b|\bconda\s+(install|remove|update)", "package install/remove"),
    ("hf-delete", r"\b(hf|huggingface-cli)\s+(repo\s+delete|upload|delete)", "hub write/delete"),
    ("db-drop", r"(?i)\b(drop\s+(table|database)|truncate\s+table|delete\s+from)\b", "destructive SQL"),
    ("eval", r"(^|[\s;&|(`])(eval|exec)\s|\b(bash|sh|zsh)\s+-c\b|\bpython3?\s+-c\b|\bnode\s+-e\b", "dynamic code exec (cannot be inspected)"),
    ("send", r"\b(sendmail|mail\s|mutt|signal-cli|curl\b.*\s-X\s*(POST|PUT|DELETE|PATCH)|curl\b.*\s(-d|--data|-F|--form)\b)", "outbound send/write request"),
]
_COMPILED = [(rid, re.compile(rx), why) for rid, rx, why in _PATTERNS]

# Commands that write to their path arguments.
_WRITERS = {"cp", "mv", "install", "ln", "touch", "mkdir", "tee", "rsync", "chmod", "chown", "sed", "perl", "patch", "tar", "unzip", "git"}
_REDIRECT = re.compile(r"(?:^|[^<>&0-9])(?:[0-9]?>>?|&>>?)\s*([^\s;&|]+)")


def _inside(path: str, cwd: Path, repo: Path) -> bool:
    p = os.path.expanduser(os.path.expandvars(path))
    if "$" in p or "`" in p:
        return False  # unexpanded var: cannot prove it is inside
    full = Path(p) if os.path.isabs(p) else (cwd / p)
    try:
        full = Path(os.path.normpath(str(full)))
        repo_n = Path(os.path.normpath(str(repo)))
        return full == repo_n or repo_n in full.parents
    except Exception:
        return False


def _outside_writes(cmd: str, cwd: Path, repo: Path) -> str | None:
    if cmd.strip() and not _inside(str(cwd), repo, repo):
        return f"cwd {cwd} is outside the repo"
    for m in _REDIRECT.finditer(cmd):
        tgt = m.group(1).strip("'\"")
        if tgt in ("/dev/null", "/dev/stdout", "/dev/stderr") or tgt.startswith("&"):
            continue
        if not _inside(tgt, cwd, repo):
            return f"redirect writes to {tgt}"
    for seg in re.split(r"&&|\|\||[;|\n]", cmd):
        try:
            toks = shlex.split(seg)
        except ValueError:
            return "unparseable command segment"
        if not toks:
            continue
        if toks[0] == "cd" and len(toks) > 1 and not _inside(toks[1], cwd, repo):
            return f"cd to {toks[1]} (outside repo)"
        if toks[0] == "cd" and len(toks) == 1:
            return "cd to $HOME (outside repo)"
        if toks[0] in _WRITERS:
            for a in toks[1:]:
                if a.startswith("-"):
                    continue
                looks_path = a.startswith(("/", "~", "$", "..")) or "/.." in a
                if looks_path and not _inside(a, cwd, repo):
                    return f"{toks[0]} touches {a} (outside repo)"
    return None


def classify_command(cmd: str, cwd: str | os.PathLike | None, repo_root: str | os.PathLike) -> Verdict:
    if not isinstance(cmd, str) or not cmd.strip():
        return Verdict(True, "empty", "empty or non-text command")
    repo = Path(repo_root)
    cwd_p = Path(cwd) if cwd else repo
    for rid, rx, why in _COMPILED:
        if rx.search(cmd):
            return Verdict(True, rid, why)
    out = _outside_writes(cmd, cwd_p, repo)
    if out:
        return Verdict(True, "outside-repo", out)
    return SAFE


def classify(tool: str, args: dict | None, repo_root, cwd=None) -> Verdict:
    tool = (tool or "").lower()
    args = args if isinstance(args, dict) else {}
    if tool == "bash":
        return classify_command(str(args.get("command", "")), cwd, repo_root)
    if tool in ("write", "edit"):
        path = args.get("path") or args.get("file_path") or args.get("file") or ""
        if not path:
            return Verdict(True, "outside-repo", f"{tool} with no path")
        if not _inside(str(path), Path(cwd) if cwd else Path(repo_root), Path(repo_root)):
            return Verdict(True, "outside-repo", f"{tool} {path} (outside repo)")
        return SAFE
    return SAFE
