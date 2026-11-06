# Security sweep — pip-audit gap (commission 002f98db, item 1)

**Date:** 2026-10-23
**Owner:** Jon (needs sudo / venv decision — Forge cannot install packages from Messages)

## What is actually broken

`soveryn-security-sweep.service` has failed every run since at least Sep 27, 2026
(weekly, 09:00): Sep 27, Oct 04, Oct 11, Oct 18 — all `status=1/FAILURE` with
exactly one finding:

```
[DEPS] all: pip-audit not importable; skipping dependency audit
```

Source: `scripts/security_sweep.py` → `check_deps()` does `import pip_audit`
and returns a finding on `ImportError`. One finding ⇒ `report["clean"]` is False
⇒ `main()` returns 1 ⇒ systemd marks the unit failed. The other three checks
(SECRETS / BACKUPS / PUBLIC) are clean — the failure is *only* the missing
dependency-audit tool.

## The second problem: the audit has nothing to scan

`HOUSE_REQUIREMENTS` in `scripts/security_sweep.py` points at:

- `~/soveryn_vnext/requirements.txt` — **does not exist**
- `~/pondwright-cwg-ops/requirements.txt`
- `~/pondpro/requirements.txt`

`soveryn_vnext` declares its deps in `pyproject.toml` (`[project].dependencies`,
no requirements.txt anywhere in the tree). So even with pip-audit installed, the
vnext repo — the main house codebase — would be silently skipped by the
`if not req_path.is_file(): continue` guard. Installing pip-audit alone turns the
unit green while auditing less than intended. Both halves need fixing.

## Fix (Jon, with sudo)

1. Install into the interpreter the unit runs with (systemd *user* unit, so the
   user python — check `ExecStart` in `~/.config/systemd/user/soveryn-security-sweep.service`):

   ```
   pip install --user pip-audit
   # or, if the unit uses a venv interpreter:
   /path/to/venv/bin/pip install pip-audit
   ```

2. Make the sweep able to see vnext deps. Two options, pick one:
   - **A (small):** add a `requirements.txt` at the repo root generated from
     `pyproject.toml` (`pip-compile` or a hand-kept pin list), so the existing
     `HOUSE_REQUIREMENTS` entry resolves.
   - **B (cleaner):** teach `check_deps()` to fall back to
     `pip_audit -r pyproject.toml` (pip-audit ≥2.7 reads PEP 621 dependencies
     directly) when `requirements.txt` is absent. One-line change in the loop.

3. Verify:

   ```
   systemctl --user restart soveryn-security-sweep.service
   systemctl --user status soveryn-security-sweep.service
   journalctl --user -u soveryn-security-sweep.service -n 20
   ```

   Expect `Security sweep: clean.` and exit 0 — or real vuln findings, which is
   the point.

## Not done by Forge

- No package installed: Messages origin has no sudo and no shell; pip install is
  a host mutation outside this seat's reach.
- No unit file edited: `~/.config/systemd/user/` is outside the house roots the
  diag/read tools can touch, and the repo's `systemd/` tree does not carry a
  `soveryn-security-sweep.service` copy (installed from elsewhere — see
  `scripts/install_systemd_units.sh`).
- No code change landed: option B above is a real patch and should be Jon's call
  since it changes audit scope.

## Item 2 — ledger reconcile (informational)

Confirmed working, reporting drift accurately. Live read this turn
(`ledger_reconcile`, read-only, 2026-10-23T17:21:28):

| book | rows | evidence | missing evidence | duplicates | unreferenced evidence |
|---|---|---|---|---|---|
| CWG | 54 | 39 | 0 | 0 | 0 |
| SOVERYN | 77 | 42 | 0 | 2 groups | 1 file |

The service's exit 1 is by design: `main()` returns 1 when drift is non-zero, so
a "failed" unit here means "drift found", not "script broken". The four CWG
receipts Aetheria listed (Amazon 2026-09-23, Lowe's 2026-09-22, Amazon 2026-10-01,
Amazon 2026-10-02) are `NEED_RECEIPT` planning rows — Jon files them via
`ledger_ingest`. Two new observations since the Oct 12 journal:

- SOVERYN has 2 duplicate groups by `evidence_sha256` (one 4-row group spanning
  $3,490.00 / $1,697.00 / $97.00 / −$90.00; one 2-row group $393.53 / −$269.51).
  Worth a `ledger_amend` review — could be legitimate split receipts or a
  re-ingest.
- `evidence/2026/2026-10-22_x_refund_269.51.png` is on disk but no row
  references it. Likely the refund half of the $393.53 pair above.
