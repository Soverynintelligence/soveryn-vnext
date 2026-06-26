# Shepherd Missed/Overdue — Implementation Plan (full-lifecycle obligation tracking)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Shepherd surfaces *missed/overdue* deadlines (not just upcoming), and the owner can mark obligations "filed" so a past-but-filed deadline shows **Done** while a genuinely unhandled one shows **Missed**.

**Architecture:** The deterministic engine gains a `lookback_days` window and tags each obligation with a temporal `status` (`upcoming`/`overdue`) from dates alone — staying pure (it never reads acknowledgments). A SQLite acknowledgment store records what the owner filed; a **pure** `apply_statuses` overlay flips matched obligations to `done`. The context builder groups Missed/Upcoming/Done; the calendar route + UI render the three sections with mark-filed/reopen actions and a fail-safe "ack unavailable" indicator.

**Tech Stack:** Python 3.11, Flask, SQLite, pytest. No LLM. Spec: `~/soveryn_vnext/docs/superpowers/specs/2026-06-26-shepherd-missed-overdue-design.md`.

## Global Constraints (bind every task)

- **Engine stays pure & ack-free:** `compute_schedule` derives `status` from `due_date` vs `today` only; it NEVER reads acknowledgments. "Did you file it?" is the separate overlay.
- **Backward-compatible:** `lookback_days` defaults to 0 → existing forward-only callers are unchanged.
- **Honesty intact:** overdue dates are real engine-computed past dates (authoritative); the ack overlay (licensee input) is the ONLY thing that marks something `done`; never guess whether something was filed; the existing cited-or-nothing / type-filter / never-guess invariants are untouched.
- **Status recomputed every render** (never stored as state) — nothing gets stuck overdue.
- **Date-only, server-local `today`** (on-site appliance). Overdue = `due_date < today`.
- **Acks fail SAFE + visible:** a down ack store → items show overdue/missed (never falsely Done) AND a visible "ack unavailable" indicator; never 500 the calendar.
- **Repo:** `~/shepherd`, package `shepherd`. Tests: `cd ~/shepherd && ~/miniconda3/envs/soveryn/bin/python -m pytest -v`.

---

## Task 1: Engine — lookback window + temporal status

**Files:** Modify `shepherd/engine.py`; Test `tests/test_engine.py` (add)

**Interfaces — Produces:**
- `ObligationInstance` gains: `status: str`, `addressed_on: date | None = None`, `note: str = ""` (added after the existing `alert_lead_days`).
- `compute_schedule(profile, rules, today, horizon_days, lookback_days: int = 0) -> (list[ObligationInstance], list[MissingDataFlag])` — computes due dates across `[today - lookback_days, today + horizon_days]`; each instance gets `status="overdue"` if `due_date < today` else `"upcoming"`.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.engine import compute_schedule
from shepherd.rules import ALL_RULES

def _wgrc():
    return StationProfile(call_sign="WGRC", service="FM", community_of_license="Lewisburg",
                          state="PA", station_type="NCE", license_expiration=date(2027, 4, 1))

def test_lookback_zero_is_forward_only_all_upcoming():
    today = date(2026, 6, 26)
    inst, _ = compute_schedule(profile=_wgrc(), rules=list(ALL_RULES), today=today, horizon_days=365)
    assert inst, "expected forward instances"
    assert all(i.due_date >= today for i in inst)
    assert all(i.status == "upcoming" for i in inst)   # default lookback_days=0 unchanged

def test_lookback_surfaces_overdue_and_upcoming():
    today = date(2026, 6, 26)
    inst, _ = compute_schedule(profile=_wgrc(), rules=list(ALL_RULES),
                               today=today, horizon_days=365, lookback_days=365)
    overdue = [i for i in inst if i.status == "overdue"]
    upcoming = [i for i in inst if i.status == "upcoming"]
    assert overdue and upcoming, "lookback should yield both past and future obligations"
    # every overdue instance is genuinely in the past; every upcoming is today-or-later
    assert all(i.due_date < today for i in overdue)
    assert all(i.due_date >= today for i in upcoming)
    # a known past quarterly (2026-04-10) is present and overdue, cited
    apr = [i for i in overdue if i.due_date == date(2026, 4, 10)]
    assert apr and apr[0].cfr_citation == "47 CFR §73.3526"

def test_lookback_instances_default_addressed_fields():
    today = date(2026, 6, 26)
    inst, _ = compute_schedule(profile=_wgrc(), rules=list(ALL_RULES),
                               today=today, horizon_days=365, lookback_days=365)
    assert all(i.addressed_on is None and i.note == "" for i in inst)
```

- [ ] **Step 2: Run → FAIL** (`compute_schedule() got an unexpected keyword 'lookback_days'` / `status` missing). `pytest tests/test_engine.py -v`

- [ ] **Step 3: Implement** — in `shepherd/engine.py`:

```python
# ObligationInstance dataclass — add three fields after alert_lead_days:
@dataclass(frozen=True)
class ObligationInstance:
    rule_id: str
    cfr_citation: str
    title: str
    due_date: date
    alert_lead_days: tuple[int, ...]
    status: str                       # "upcoming" | "overdue" (| "done" via overlay)
    addressed_on: date | None = None
    note: str = ""

# compute_schedule — add lookback_days param + window + status:
def compute_schedule(profile, rules, today, horizon_days, lookback_days: int = 0):
    from datetime import timedelta
    instances: list[ObligationInstance] = []
    flags: list[MissingDataFlag] = []
    start = today - timedelta(days=lookback_days)
    window = lookback_days + horizon_days
    for rule in rules:
        if not rule_applies(rule, profile.station_type):
            continue
        missing = profile.missing_for(rule)
        if missing:
            flags.append(MissingDataFlag(rule_id=rule.id, cfr_citation=rule.cfr_citation,
                                         title=rule.title, missing_fields=tuple(missing)))
            continue
        for due in rule.due_dates(profile, start, window):     # full window incl. past
            if not rule.cfr_citation:
                raise ValueError(f"rule {rule.id!r} would emit an uncited obligation")
            status = "overdue" if due < today else "upcoming"
            instances.append(ObligationInstance(
                rule_id=rule.id, cfr_citation=rule.cfr_citation, title=rule.title,
                due_date=due, alert_lead_days=rule.alert_lead_days, status=status))
    instances = sorted(instances, key=lambda i: i.due_date)
    return instances, flags
```

(Preserve the existing self-enforcing cited-or-nothing raise, the type filter, and the missing-data flagging exactly — only the window + status are new. Update any pre-existing direct `ObligationInstance(...)` construction in the test files to pass `status=` — e.g. the frozen-instance test.)

- [ ] **Step 4: Run → PASS** (and the full suite — fix any direct ObligationInstance construction that now needs `status`).
- [ ] **Step 5: Commit** (`feat(engine): lookback window + temporal status (upcoming/overdue)`)

---

## Task 2: Acknowledgment store (mark-filed persistence)

**Files:** Modify `shepherd/store.py`; Test `tests/test_status_store.py`

**Interfaces — Produces (on `ProfileStore`, same SQLite db, new table `obligation_status`):**
- `mark_addressed(self, call_sign: str, rule_id: str, due_date: date, note: str = "") -> None` — upsert keyed `(call_sign, rule_id, due_date)`; stores `addressed_on = date.today()` and the note.
- `get_addressed(self, call_sign: str) -> dict[tuple[str, str], dict]` — maps `(rule_id, due_date_iso)` → `{"addressed_on": date, "note": str}`.
- `clear_addressed(self, call_sign: str, rule_id: str, due_date: date) -> None`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.store import ProfileStore

def test_mark_get_clear_addressed(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.mark_addressed("WGRC", "quarterly_issues_programs", date(2026, 4, 10), note="filed via LMS")
    got = s.get_addressed("WGRC")
    key = ("quarterly_issues_programs", "2026-04-10")
    assert key in got
    assert got[key]["note"] == "filed via LMS"
    assert isinstance(got[key]["addressed_on"], date)
    s.clear_addressed("WGRC", "quarterly_issues_programs", date(2026, 4, 10))
    assert ("quarterly_issues_programs", "2026-04-10") not in s.get_addressed("WGRC")

def test_mark_addressed_upserts(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.mark_addressed("WGRC", "license_renewal", date(2026, 12, 1), note="first")
    s.mark_addressed("WGRC", "license_renewal", date(2026, 12, 1), note="second")
    got = s.get_addressed("WGRC")
    assert got[("license_renewal", "2026-12-01")]["note"] == "second"
    assert len([k for k in got if k[0] == "license_renewal"]) == 1
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** — add the table to `_init_db` (idempotent) and the three methods, using parameterized SQL and `INSERT … ON CONFLICT(call_sign, rule_id, due_date) DO UPDATE`. Serialize `due_date`/`addressed_on` as ISO strings; parse back in `get_addressed`. Key the returned dict by `(rule_id, due_date_iso_string)`.

- [ ] **Step 4: Run → PASS** (full suite green)
- [ ] **Step 5: Commit** (`feat(store): obligation acknowledgment store (mark/get/clear addressed)`)

---

## Task 3: apply_statuses — pure done-overlay

**Files:** Create `shepherd/status_overlay.py`; Test `tests/test_status_overlay.py`

**Interfaces — Produces:**
- `apply_statuses(instances: list[ObligationInstance], addressed: dict[tuple[str, str], dict]) -> list[ObligationInstance]` — for each instance whose `(rule_id, due_date.isoformat())` is in `addressed`, return a copy with `status="done"`, `addressed_on=addressed[...]["addressed_on"]`, `note=addressed[...]["note"]`; others unchanged. Pure (no store, no I/O). Uses `dataclasses.replace`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.engine import ObligationInstance
from shepherd.status_overlay import apply_statuses

def _inst(rule_id, due, status="overdue"):
    return ObligationInstance(rule_id=rule_id, cfr_citation="47 CFR §73.3526", title="Q I/P",
                              due_date=due, alert_lead_days=(30,), status=status)

def test_addressed_instance_becomes_done():
    inst = _inst("quarterly_issues_programs", date(2026, 4, 10))
    addressed = {("quarterly_issues_programs", "2026-04-10"):
                 {"addressed_on": date(2026, 4, 9), "note": "filed"}}
    out = apply_statuses([inst], addressed)
    assert out[0].status == "done"
    assert out[0].addressed_on == date(2026, 4, 9)
    assert out[0].note == "filed"

def test_unaddressed_instance_untouched():
    inst = _inst("quarterly_issues_programs", date(2026, 7, 10), status="upcoming")
    out = apply_statuses([inst], {})
    assert out[0].status == "upcoming"
    assert out[0].addressed_on is None
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `shepherd/status_overlay.py`:

```python
"""Pure overlay: flips obligations the licensee has marked filed to status='done'.
The engine never reads acknowledgments; this is the only place 'done' is applied."""
from __future__ import annotations

from dataclasses import replace

from shepherd.engine import ObligationInstance


def apply_statuses(instances: list[ObligationInstance], addressed: dict) -> list[ObligationInstance]:
    out = []
    for inst in instances:
        key = (inst.rule_id, inst.due_date.isoformat())
        if key in addressed:
            a = addressed[key]
            out.append(replace(inst, status="done",
                               addressed_on=a.get("addressed_on"), note=a.get("note", "")))
        else:
            out.append(inst)
    return out
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(overlay): pure apply_statuses done-overlay`)

---

## Task 4: Context builder — Missed/Upcoming/Done grouping

**Files:** Modify `shepherd/agent/context.py`; Test `tests/test_agent_context.py` (add)

**Interfaces — Consumes:** `ObligationInstance` now has `status`. **Produces:** `build_compliance_context` groups instances into MISSED (`status=="overdue"`), UPCOMING (`status=="upcoming"`), DONE (`status=="done"`, shows `addressed_on`). Keeps the existing CANNOT COMPUTE (flags) section. Existing forward-only callers (all-upcoming) still render correctly.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.engine import ObligationInstance
from shepherd.agent.context import build_compliance_context

def _p():
    return StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1))

def test_context_groups_missed_upcoming_done():
    today = date(2026, 6, 26)
    insts = [
        ObligationInstance("quarterly_issues_programs","47 CFR §73.3526","Q I/P",
                           date(2026,4,10),(30,),"overdue"),
        ObligationInstance("quarterly_issues_programs","47 CFR §73.3526","Q I/P",
                           date(2026,7,10),(30,),"upcoming"),
        ObligationInstance("license_renewal","47 CFR §73.3539","Renewal",
                           date(2026,3,1),(90,),"done", addressed_on=date(2026,2,15), note="filed"),
    ]
    ctx = build_compliance_context(_p(), insts, [], today)
    low = ctx.lower()
    assert "missed" in low and "upcoming" in low and "done" in low
    # the missed item shows its real past date + citation
    assert "2026-04-10" in ctx and "47 CFR §73.3526" in ctx
    # the done item shows the filed date, under done (not missed)
    assert "2026-02-15" in ctx
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — restructure `build_compliance_context` to bucket by `inst.status` into three labelled sections (MISSED — ACTION NEEDED / UPCOMING / DONE), each line keeping `title — due_date — citation`; DONE lines also show `filed <addressed_on>`. Keep the CANNOT COMPUTE flags section. If a bucket is empty, omit it (or a neutral "none"). Keep it deterministic.
- [ ] **Step 4: Run → PASS** (and the existing context tests — forward-only instances are all `upcoming` and render under UPCOMING; update those assertions only if a section header genuinely changed the text they matched).
- [ ] **Step 5: Commit** (`feat(agent): context groups Missed/Upcoming/Done`)

---

## Task 5: Routes (/address, /reopen) + calendar overlay + three-section UI

**Files:** Modify `shepherd/ui/app.py`, `shepherd/ui/templates/calendar.html`, `shepherd/ui/static/style.css`; Test `tests/test_ui_lifecycle.py`

**Interfaces — Consumes:** `ProfileStore.mark_addressed/get_addressed/clear_addressed` (T2), `compute_schedule(..., lookback_days=365)` (T1), `apply_statuses` (T3). **Produces:** `POST /address/<call_sign>`, `POST /reopen/<call_sign>`; the calendar route overlays acks + renders Missed/Upcoming/Done + an `ack_unavailable` indicator.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.store import ProfileStore
from shepherd.ui.app import create_app

def _client(tmp_path):
    store = ProfileStore(str(tmp_path / "t.db"))
    store.save(StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1)))
    return create_app(store).test_client(), store

def test_calendar_shows_missed_section(tmp_path):
    client, _ = _client(tmp_path)
    body = client.get("/calendar/WGRC").get_data(as_text=True)
    assert "Missed" in body  # past quarterly within the 1-yr lookback shows as missed

def test_address_marks_done_then_reopen_restores(tmp_path):
    client, store = _client(tmp_path)
    r = client.post("/address/WGRC", data={"rule_id": "quarterly_issues_programs",
                                           "due_date": "2026-04-10", "note": "filed"})
    assert r.status_code in (302, 200)
    assert ("quarterly_issues_programs", "2026-04-10") in store.get_addressed("WGRC")
    client.post("/reopen/WGRC", data={"rule_id": "quarterly_issues_programs",
                                      "due_date": "2026-04-10"})
    assert ("quarterly_issues_programs", "2026-04-10") not in store.get_addressed("WGRC")

def test_address_unknown_station_404(tmp_path):
    client, _ = _client(tmp_path)
    assert client.post("/address/NOPE", data={"rule_id":"x","due_date":"2026-04-10"}).status_code == 404
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — in `app.py`:
  - **Calendar route:** load acks with a guard — `try: acks = store.get_addressed(call_sign); ack_unavailable = False except Exception: acks = {}; ack_unavailable = True`. Then `instances, flags = compute_schedule(profile, list(ALL_RULES), date.today(), horizon_days=365, lookback_days=365)`; `instances = apply_statuses(instances, acks)`; bucket into `missed`/`upcoming`/`done` by status; pass all three + `flags` + `ack_unavailable` to the template.
  - **`POST /address/<call_sign>`:** 404 if `store.get(call_sign) is None`; parse `rule_id`, `due_date` (`date.fromisoformat`, graceful on bad input), `note`; `store.mark_addressed(...)`; redirect to calendar.
  - **`POST /reopen/<call_sign>`:** 404 if unknown; `store.clear_addressed(...)`; redirect.
- [ ] **Step 4: UI** — `calendar.html`: render three sections — **Missed — Action Needed** (red, top; each card a small form POSTing `rule_id`+`due_date` to `/address` with an optional note → "Mark filed" button), **Upcoming**, **Done** (muted; show filed date + a "Reopen" form to `/reopen`). Status hero: if any `missed`, show ACTION NEEDED (red). Render the **"⚠ Filing status temporarily unavailable"** banner when `ack_unavailable`. Style sections in `style.css` to match. Keep the missing-data flags rendering.
- [ ] **Step 5: Run → PASS** (full suite green), verify `/calendar/WGRC` renders the sections, then **Commit** (`feat(ui): lifecycle calendar (Missed/Upcoming/Done) + address/reopen + ack-unavailable indicator`)

---

## Self-review notes
- Spec coverage: engine lookback + temporal status (T1), backward-compat lookback_days=0 (T1 test), ack store (T2), pure overlay/engine-stays-ack-free (T3), Missed/Upcoming/Done context (T4), routes + three-section UI + fail-safe-visible ack-unavailable (T5), date-only/server-local (T1 honesty), honesty (overdue = real past dates; only acks mark done). 
- Status is recomputed each render (no stored state) — addressed by T5 computing fresh per request. Reversion = mark filed→done / reopen→back (T5 test).
- The cited-or-nothing raise + type filter + missing-data flagging are preserved verbatim in T1's compute_schedule.
- Buildable + testable now (no LLM, no key). The agent (already built) automatically gains missed-awareness via T4's context grouping.
