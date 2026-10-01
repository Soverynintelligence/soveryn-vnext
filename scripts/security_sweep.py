"""House security sweep — deterministic checks, weekly, pushes to Jon on findings.

The security twin of ledgers/reconcile.py. Checks:
  1. SECRETS      gitleaks scan of every house git repo (history + working tree)
  2. DEPS         pip-audit against each requirements.txt in the house services
  3. BACKUPS      nightly backup freshness (newest backup dir < 36h old)
  4. PUBLIC       health of public-facing house endpoints

Usage:
  python3 scripts/security_sweep.py            # text report, exit 1 on findings
  python3 scripts/security_sweep.py --notify   # + write docs/ops/security/SECURITY-LATEST.md, webpush on drift
"""

from __future__ import annotations

import argparse

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home()
REPO_ROOT = HOME / "soveryn_vnext"
# House repos gitleaks scans (skip sandbox: vendored upstream code, not ours).
REPOS = [d for d in (HOME / "").glob("*/") if (d / ".git").is_dir() and "sandbox" not in d.name]
REPOS = sorted(set(REPOS) | {REPO_ROOT, HOME / "pondwright-cwg-ops", HOME / "carolinawatergardens", HOME / "pondpro"})
REPOS = [r for r in REPOS if (r / ".git").is_dir()]

# Dependency audit scope: house services only. Upstream clones (llama.cpp,
# sandbox/*) are tracked upstream and audited by their maintainers, not us.
HOUSE_REQUIREMENTS = [
    REPO_ROOT / "requirements.txt",
    HOME / "pondwright-cwg-ops" / "requirements.txt",
    HOME / "pondpro" / "requirements.txt",
]

GITLEAKS = str(HOME / ".local" / "bin" / "gitleaks")
ENDPOINTS = {
    "vnext": "http://127.0.0.1:5001/health",
    "crm": "http://127.0.0.1:8100/health",
}
BACKUP_DIR = REPO_ROOT / "backups"


def check_secrets() -> list[dict]:
    findings = []
    for repo in REPOS:
        if not Path(GITLEAKS).is_file():
            return [{"repo": "all", "finding": f"gitleaks not installed at {GITLEAKS}"}]
        r = subprocess.run(
            [GITLEAKS, "detect", "--source", str(repo), "--no-banner", "--report-format", "json",
             "--report-path", "/dev/stdout", "--redact", "-q"],
            capture_output=True, text=True, timeout=300,
        )
        # exit 1 = leaks found, exit 0 = clean, other = error
        if r.returncode not in (0, 1):
            findings.append({"repo": repo.name, "finding": f"gitleaks error rc={r.returncode}: {r.stderr[:200]}"})
            continue
        try:
            leaks = json.loads(r.stdout) if r.stdout.strip() else []
        except json.JSONDecodeError:
            leaks = []
        for leak in leaks:
            findings.append({
                "repo": repo.name,
                "finding": f"{leak.get('RuleID', '?')} in {leak.get('File', '?')}:{leak.get('StartLine', '?')} (commit {str(leak.get('Commit', ''))[:8]})",
            })
    return findings


def check_deps() -> list[dict]:
    findings = []
    seen: set[tuple] = set()
    try:
        import pip_audit  # noqa: F401
    except ImportError:
        return [{"repo": "all", "finding": "pip-audit not importable; skipping dependency audit"}]
    for req_path in HOUSE_REQUIREMENTS:
        if not req_path.is_file():
            continue
        r = subprocess.run(
            [sys.executable, "-m", "pip_audit", "-r", str(req_path), "--no-deps", "-f", "json", "--progress-spinner", "off"],
            capture_output=True, text=True, timeout=600,
        )
        try:
            data = json.loads(r.stdout) if r.stdout.strip() else {}
        except json.JSONDecodeError:
            findings.append({"repo": req_path.parent.name, "finding": f"pip-audit could not parse {req_path.name}: {r.stderr[:150]}"})
            continue
        deps = data.get("dependencies", []) if isinstance(data, dict) else []
        for dep in deps:
            for vuln in dep.get("vulns", []):
                key = (req_path.parent.name, dep.get("name"), vuln.get("id"))
                if key in seen:
                    continue
                seen.add(key)
                findings.append({
                    "repo": req_path.parent.name,
                    "finding": f"{dep.get('name')}=={dep.get('version')}: {vuln.get('id')} fix={', '.join(vuln.get('fix_versions', []) or ['none'])}",
                })
    return findings


def check_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return [{"repo": "backups", "finding": f"backup dir missing: {BACKUP_DIR}"}]
    dirs = [d for d in BACKUP_DIR.iterdir() if d.is_dir() and d.name[:2] == "20"]
    if not dirs:
        return [{"repo": "backups", "finding": "no dated backups found"}]
    newest = max(d.name for d in dirs)
    age_hours = (datetime.now() - datetime.strptime(newest, "%Y-%m-%d")).total_seconds() / 3600
    if age_hours > 36:
        return [{"repo": "backups", "finding": f"newest backup {newest} is {age_hours:.0f}h old (stale)"}]
    return []


def check_public() -> list[dict]:
    import urllib.request
    findings = []
    for name, url in ENDPOINTS.items():
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                if resp.status != 200:
                    findings.append({"repo": name, "finding": f"{url} returned HTTP {resp.status}"})
        except Exception as e:
            findings.append({"repo": name, "finding": f"{url} unreachable: {type(e).__name__}"})
    return findings


CHECKS = [("SECRETS", check_secrets), ("DEPS", check_deps), ("BACKUPS", check_backups), ("PUBLIC", check_public)]


def sweep() -> dict:
    results = {name: fn() for name, fn in CHECKS}
    total = sum(len(v) for v in results.values())
    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "clean": total == 0,
        "total_findings": total,
        "results": results,
        "repos_scanned": [r.name for r in REPOS],
    }


def format_report(report: dict) -> str:
    if report["clean"]:
        return "Security sweep: clean. No secrets, no known vulns, backups fresh, public endpoints healthy."
    lines = [f"Security findings: {report['total_findings']}. Fix before they become incidents."]
    for name, findings in report["results"].items():
        for f in findings:
            lines.append(f"  [{name}] {f['repo']}: {f['finding']}")
    return "\n".join(lines)


def notify(report: dict) -> None:
    out = REPO_ROOT / "docs" / "ops" / "security"
    out.mkdir(parents=True, exist_ok=True)
    (out / "SECURITY-LATEST.md").write_text(
        f"# Security sweep — {report['checked_at']}\n\n" + format_report(report) + "\n", encoding="utf-8")
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from soveryn.platform.webpush.notify import notify_needs_you
        notify_needs_you(
            title=f"Security: {report['total_findings']} finding(s)" if not report["clean"] else "Security sweep: clean",
            body="House security sweep results in SECURITY-LATEST.md",
            url="/messages",
            tag="security-sweep",
        )
    except Exception:
        pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="security-sweep")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = sweep()
    if args.notify:
        notify(report)
    print(format_report(report))
    if args.json:
        print(json.dumps(report, indent=1))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
