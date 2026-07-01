# Steward — Grant-Compliance Agent Tools Implementation Plan (slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A deterministic grant-compliance engine (the Shepherd pattern) exposed as agent tools so Vett and Aetheria can answer "what grant reports are due / overdue / coming up?" and mark a report submitted — grounded entirely in the engine, never confabulated.

**Architecture:** A clean, isolated `steward` engine + JSON store (developed + unit-tested standalone), then thin tool wrappers registered into SOVERYN vnext's verified tool registry (sandbox pattern). The engine computes per-award report deadlines from the grant terms; a submission overlay marks reports `done`; the agents only report what the tools return.

**Tech Stack:** Python 3.11, dataclasses, JSON files, pytest. No LLM. Integrates with `soveryn/platform/tools` (vnext). Spec: `~/soveryn_vnext/docs/superpowers/specs/2026-06-27-steward-grant-tools-design.md`.

## Global Constraints (bind every task)

- **Facts only, never the persona** (Jon's load-bearing boundary): this grounds dates/deadlines/figures; it does NOT touch warmth/metaphor/voice. The tools return computed facts; the agents' framing stays free.
- **Anti-confab:** grant dates come ONLY from `compute_grant_schedule` — agents never generate them. Read tools return engine output; the agent formats, never invents.
- **Per-award model:** deadlines computed from each grant's own terms (period + cadence + milestones), not universal rules.
- **Cadence math is provisional:** `annual`/`quarterly`/`final`/`milestone` rules are golden-test-pinned best-known encodings, marked `# VERIFY per award letter` — confirmed against each actual award before the agents treat them as authoritative.
- **Grant TERMS are config-seeded** (Jon-maintained JSON); the only write is the narrow audited `grant_submit` (records a discrete owner-authorized submission + timestamp). No `add_grant` agent tool in slice 1.
- **Engine + store are pure/isolated + fully unit-tested** before any vnext wiring. The tool layer is thin.
- **Build concrete, do NOT abstract:** grants is instance #1; extract a reusable `DeterministicEngine` base at instance #2 (system-state), not now.
- **Module path:** `soveryn/platform/steward/` (greenfield, verified). Tests: `cd ~/soveryn_vnext && <env>/python -m pytest soveryn/platform/steward/tests -v` (or the repo's test invocation — match it).

---

## Task 1: Engine — Grant model + compute_grant_schedule

**Files:** Create `soveryn/platform/steward/__init__.py`, `soveryn/platform/steward/engine.py`; Test `soveryn/platform/steward/tests/test_engine.py`

**Interfaces — Produces:**
- `@dataclass(frozen=True) class Grant: funder:str; award_id:str; title:str; period_start:date; period_end:date; reporting_cadence:str; milestones:tuple[tuple[str,str],...]=(); award_amount:float|None=None` (`milestones` = tuple of `(iso_date, description)`).
- `@dataclass(frozen=True) class GrantObligation: award_id:str; funder:str; title:str; report_label:str; due_date:date; status:str` (`status` = `"upcoming"`/`"overdue"`; `"done"` applied by the overlay in Task 2).
- `compute_grant_schedule(grants, today, lookback_days, horizon_days) -> list[GrantObligation]` — per grant, materialize report due-dates within `[today-lookback, today+horizon]` from its cadence; status `"overdue"` if `due < today` else `"upcoming"`; sorted by due_date.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from soveryn.platform.steward.engine import Grant, compute_grant_schedule

def _annual_grant():
    return Grant(funder="Cosmos Institute", award_id="COSMOS-1", title="Sovereign AI",
                 period_start=date(2025, 9, 1), period_end=date(2027, 8, 31),
                 reporting_cadence="annual")

def test_annual_reports_on_each_anniversary_in_window():
    obs = compute_grant_schedule([_annual_grant()], today=date(2026, 6, 27),
                                 lookback_days=365, horizon_days=365)
    dues = sorted(o.due_date for o in obs)
    # annual report due on each period anniversary within the window (PROVISIONAL — verify per award)
    assert date(2026, 9, 1) in dues            # upcoming anniversary
    assert all(o.award_id == "COSMOS-1" and o.funder == "Cosmos Institute" for o in obs)

def test_overdue_vs_upcoming_status():
    obs = compute_grant_schedule([_annual_grant()], today=date(2026, 6, 27),
                                 lookback_days=365, horizon_days=365)
    for o in obs:
        assert o.status == ("overdue" if o.due_date < date(2026, 6, 27) else "upcoming")

def test_milestone_cadence_materializes_each_milestone():
    g = Grant(funder="NSF", award_id="NSF-9", title="Phase I",
              period_start=date(2026, 1, 1), period_end=date(2027, 1, 1),
              reporting_cadence="milestone",
              milestones=(("2026-06-30", "Prototype report"), ("2026-12-31", "Phase I final")))
    obs = compute_grant_schedule([g], today=date(2026, 6, 27), lookback_days=365, horizon_days=365)
    dues = {o.due_date for o in obs}
    assert date(2026, 6, 30) in dues and date(2026, 12, 31) in dues

def test_final_report_after_period_end():
    g = Grant(funder="X", award_id="X-1", title="t", period_start=date(2025,1,1),
              period_end=date(2026,7,1), reporting_cadence="final")
    obs = compute_grant_schedule([g], today=date(2026,6,27), lookback_days=0, horizon_days=365)
    # final report due FINAL_OFFSET_DAYS after period_end (PROVISIONAL)
    assert any(o.due_date > date(2026,7,1) for o in obs)
```

- [ ] **Step 2: Run → FAIL** (module missing).
- [ ] **Step 3: Implement** `engine.py`:

```python
"""Deterministic grant-compliance engine (the Shepherd pattern, grant domain).
Per-award: computes report deadlines from the grant's own terms. No LLM, never-guess.
Cadence constants are PROVISIONAL — verify each against the actual award letter."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

FINAL_OFFSET_DAYS = 90        # PROVISIONAL # VERIFY per award letter (final report due N days after period_end)


@dataclass(frozen=True)
class Grant:
    funder: str
    award_id: str
    title: str
    period_start: date
    period_end: date
    reporting_cadence: str                 # "annual" | "quarterly" | "final" | "milestone"
    milestones: tuple[tuple[str, str], ...] = ()   # (iso_date, description)
    award_amount: float | None = None


@dataclass(frozen=True)
class GrantObligation:
    award_id: str
    funder: str
    title: str
    report_label: str
    due_date: date
    status: str                            # "upcoming" | "overdue" | (| "done" via overlay)


def _add_months(d: date, months: int) -> date:
    m = d.month - 1 + months
    y = d.year + m // 12
    mm = m % 12 + 1
    # clamp day to month length (handles Feb etc.)
    import calendar
    dd = min(d.day, calendar.monthrange(y, mm)[1])
    return date(y, mm, dd)


def _cadence_due_dates(g: Grant, start: date, end: date) -> list[tuple[date, str]]:
    """(due_date, report_label) pairs for the grant's cadence within [start, end]. PROVISIONAL math."""
    out: list[tuple[date, str]] = []
    if g.reporting_cadence == "annual":
        i = 1
        d = _add_months(g.period_start, 12)
        while d <= g.period_end:
            out.append((d, f"Annual report (year {i})"))
            i += 1
            d = _add_months(g.period_start, 12 * i)
    elif g.reporting_cadence == "quarterly":
        i = 1
        d = _add_months(g.period_start, 3)
        while d <= g.period_end:
            out.append((d, f"Quarterly report Q{i}"))
            i += 1
            d = _add_months(g.period_start, 3 * i)
    elif g.reporting_cadence == "final":
        out.append((g.period_end + timedelta(days=FINAL_OFFSET_DAYS), "Final report"))
    elif g.reporting_cadence == "milestone":
        for iso, desc in g.milestones:
            out.append((date.fromisoformat(iso), desc or "Milestone"))
    # window filter
    return [(d, lbl) for (d, lbl) in out if start <= d <= end]


def compute_grant_schedule(grants, today: date, lookback_days: int, horizon_days: int):
    start = today - timedelta(days=lookback_days)
    end = today + timedelta(days=horizon_days)
    obligations: list[GrantObligation] = []
    for g in grants:
        for due, label in _cadence_due_dates(g, start, end):
            status = "overdue" if due < today else "upcoming"
            obligations.append(GrantObligation(award_id=g.award_id, funder=g.funder, title=g.title,
                                               report_label=label, due_date=due, status=status))
    return sorted(obligations, key=lambda o: o.due_date)
```

- [ ] **Step 4: Run → PASS** (adjust the `final` test if the offset window needs widening).
- [ ] **Step 5: Commit** (`feat(steward): grant engine — per-award cadence schedule + status`)

---

## Task 2: Store + submission overlay (the `done` mark)

**Files:** Create `soveryn/platform/steward/store.py`; Test `soveryn/platform/steward/tests/test_store.py`

**Interfaces — Produces:**
- `load_grants(config_path: str) -> list[Grant]` — reads a JSON grants config (Jon-maintained) into `Grant` objects (parse ISO dates; default empty milestones).
- `class SubmissionStore: __init__(self, path:str)`; `record(award_id, report_due: date, note="") -> None` (writes `{award_id, report_due_iso: {submitted_at: today_iso, note}}` to the JSON file; re-record updates); `all() -> dict[tuple[str,str], dict]` keyed `(award_id, report_due_iso)`.
- `apply_submissions(obligations, submissions: dict) -> list[GrantObligation]` — pure: for each obligation whose `(award_id, due_date.isoformat())` is in `submissions`, return a copy with `status="done"` (carry `submitted_at`); others unchanged. (Add `submitted_at: date|None=None` + `note: str=""` fields to `GrantObligation`, defaulted, in Task 1's dataclass — update T1 if not already; here we consume them.)

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from soveryn.platform.steward.engine import GrantObligation
from soveryn.platform.steward.store import SubmissionStore, apply_submissions, load_grants

def test_submission_round_trip(tmp_path):
    s = SubmissionStore(str(tmp_path / "subs.json"))
    s.record("COSMOS-1", date(2026, 9, 1), note="filed in research.gov")
    got = s.all()
    assert ("COSMOS-1", "2026-09-01") in got
    assert got[("COSMOS-1", "2026-09-01")]["submitted_at"]   # a date/iso present

def test_apply_submissions_marks_done():
    obs = [GrantObligation("COSMOS-1","Cosmos","Sovereign AI","Annual report (year 1)",
                           date(2026,9,1),"upcoming")]
    subs = {("COSMOS-1","2026-09-01"): {"submitted_at": "2026-08-20", "note": ""}}
    out = apply_submissions(obs, subs)
    assert out[0].status == "done"

def test_apply_submissions_leaves_unsubmitted():
    obs = [GrantObligation("X","X","t","Final report", date(2026,10,1),"overdue")]
    assert apply_submissions(obs, {})[0].status == "overdue"

def test_load_grants_from_config(tmp_path):
    import json
    cfg = tmp_path / "grants.json"
    cfg.write_text(json.dumps([{"funder":"Cosmos Institute","award_id":"COSMOS-1","title":"Sovereign AI",
        "period_start":"2025-09-01","period_end":"2027-08-31","reporting_cadence":"annual"}]))
    grants = load_grants(str(cfg))
    assert grants[0].award_id == "COSMOS-1" and grants[0].reporting_cadence == "annual"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — in `engine.py` add `submitted_at: date | None = None` and `note: str = ""` to `GrantObligation` (defaults). In `store.py`: `load_grants` (json.load → `Grant(...)`, `date.fromisoformat`, milestones as tuples); `SubmissionStore` (JSON file: load dict on init / empty if absent; `record` sets `data[f"{award_id}|{report_due.isoformat()}"] = {"submitted_at": date.today().isoformat(), "note": note}` then writes the file; `all()` returns the dict keyed `(award_id, due_iso)` with `submitted_at` parsed to a `date`); `apply_submissions` via `dataclasses.replace` setting `status="done"`, `submitted_at`, `note`.
- [ ] **Step 4: Run → PASS** (full module suite green)
- [ ] **Step 5: Commit** (`feat(steward): grants config loader + submission store + done-overlay`)

---

## Task 3: Agent tools (vnext registry — verified sandbox pattern)

**Files:** Create `soveryn/platform/steward/tools.py`; Test `soveryn/platform/steward/tests/test_tools.py`; wire registration where vnext registers sandbox tools.

**FIRST, read the real pattern (do not guess):** `soveryn/platform/sandbox/tools.py` (the `build_*_tool()` → `ToolSpec` and `register_*_tools(registry)` template) and `soveryn/platform/tools/registry.py` (`ToolSpec(name, owner, schema, handler, description)` + owner access control). Match them EXACTLY. Owners are from `ACTIVE_AGENTS` in `soveryn/config/runtime.py` — register Steward tools for `"aetheria"` and `"vett"`. Tool invocations auto-emit `ToolAuditEvent` (no extra work).

**Interfaces — Produces:** `register_steward_tools(registry, *, grants_config_path, submissions_path)` registering, per owner in `("aetheria","vett")`:
- `grant_deadlines(window_days: int = 90)` → due/overdue/upcoming (NOT done) within the window: load grants + submissions → `compute_grant_schedule(..., lookback_days=365, horizon_days=window_days)` → `apply_submissions` → filter out `done` → list of `{award_id, funder, title, report_label, due_date, status}`.
- `grant_status(award_id: str)` → that grant's obligations (incl. done) + next deadline.
- `list_grants()` → `[{award_id, funder, title, period_start, period_end, cadence}]`.
- `grant_submit(award_id: str, report_date: str, note: str = "")` → `SubmissionStore.record(award_id, date.fromisoformat(report_date), note)`; returns `{ok: True, award_id, report_date, submitted_at}`. (The narrow audited write.)

Each read handler returns deterministic engine output (the agent formats it). Schemas (JSON-schema per the registry's `ToolSpec.schema`) describe the args above.

- [ ] **Step 1: Write the failing test** (engine/store-backed, no live agent — call the handlers directly)

```python
from datetime import date
import json
from soveryn.platform.steward import tools as steward_tools

def _setup(tmp_path):
    grants = tmp_path / "grants.json"; subs = tmp_path / "subs.json"
    grants.write_text(json.dumps([{"funder":"Cosmos Institute","award_id":"COSMOS-1","title":"Sovereign AI",
        "period_start":"2025-09-01","period_end":"2027-08-31","reporting_cadence":"annual"}]))
    return str(grants), str(subs)

def test_grant_deadlines_handler_returns_computed(tmp_path):
    gcfg, scfg = _setup(tmp_path)
    h = steward_tools.build_grant_deadlines_handler(grants_config_path=gcfg, submissions_path=scfg)
    out = h(window_days=400)
    assert any(r["award_id"] == "COSMOS-1" for r in out)
    assert all("due_date" in r and r["status"] in ("upcoming","overdue") for r in out)

def test_grant_submit_then_excluded_from_deadlines(tmp_path):
    gcfg, scfg = _setup(tmp_path)
    sub = steward_tools.build_grant_submit_handler(grants_config_path=gcfg, submissions_path=scfg)
    dead = steward_tools.build_grant_deadlines_handler(grants_config_path=gcfg, submissions_path=scfg)
    before = [r for r in dead(window_days=400) if r["award_id"]=="COSMOS-1"]
    assert before
    sub(award_id="COSMOS-1", report_date=before[0]["due_date"])   # mark it submitted
    after = [r for r in dead(window_days=400) if r["due_date"]==before[0]["due_date"]]
    assert not after          # submitted → done → no longer in deadlines

def test_register_steward_tools_registers_for_aetheria_and_vett(tmp_path):
    gcfg, scfg = _setup(tmp_path)
    # a minimal fake registry capturing registrations (or the real registry if cheap to construct)
    class _Reg:
        def __init__(self): self.specs = []
        def register(self, spec): self.specs.append(spec)
    reg = _Reg()
    steward_tools.register_steward_tools(reg, grants_config_path=gcfg, submissions_path=scfg)
    owners = {s.owner for s in reg.specs}
    names = {s.name for s in reg.specs}
    assert "aetheria" in owners and "vett" in owners
    assert {"grant_deadlines","grant_status","list_grants","grant_submit"} <= names
```

(Note: if the real `registry.register` signature differs, adapt the fake to it after reading `registry.py`. The handler-builder split keeps the engine logic unit-testable without the registry.)

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `tools.py` mirroring `sandbox/tools.py`: `build_*_handler(...)` pure closures over the engine+store (the date-returning handlers serialize `due_date` to ISO strings for tool output), `build_*_tool(...) -> ToolSpec(name, owner, schema, handler, description)`, and `register_steward_tools(registry, *, grants_config_path, submissions_path)` looping owners `("aetheria","vett")` × the four tools → `registry.register(spec)`. Then wire `register_steward_tools(...)` into wherever vnext registers sandbox tools at startup (pass the real config paths — e.g. `soveryn/platform/steward/grants.json` + `submissions.json`, or the configured data dir).
- [ ] **Step 4: Run → PASS** (module suite green; confirm registration against the real registry signature).
- [ ] **Step 5: Commit** (`feat(steward): grant agent tools (deadlines/status/list/submit) registered for aetheria+vett`)

---

## Self-review notes
- Spec coverage: per-award engine + cadences incl. milestones (T1), config-seeded grants + submission store + done-overlay + submitted_at (T2), the 3 read tools + narrow `grant_submit` write registered for Aetheria+Vett via the verified sandbox pattern with auto-audit (T3), anti-confab (tools return engine output only), facts-not-persona boundary (Global Constraints), build-concrete-don't-abstract (Global Constraints), provisional cadence math golden-pinned (T1). 
- Engine + store are pure + isolated (T1/T2 fully unit-tested with NO vnext dependency); only T3 touches the live registry, and it reads the real `sandbox/tools.py`/`registry.py` first and matches them.
- Out (later slices): drafting (Scotty), spending checks, proactive heartbeat, `add_grant`, web UI, the `DeterministicEngine` base extraction (instance #2).
- The cadence constants (`FINAL_OFFSET_DAYS`, annual/quarterly anchoring) are PROVISIONAL — verify against each real award letter before the agents report them as authoritative.
