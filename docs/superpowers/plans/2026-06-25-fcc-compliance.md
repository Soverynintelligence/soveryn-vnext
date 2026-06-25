# FCC Compliance Tool — Implementation Plan (MVP / Slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A station owner enters their station profile and gets a cited, deterministic calendar of every fine-triggering FCC obligation, with escalating multi-channel alerts so a deadline is never missed.

**Architecture:** A standalone Python package (new repo `fcc-compliance`). Declarative CFR rule definitions + a station profile feed a **pure deterministic deadline engine** (no LLM) that emits cited obligation instances; a notification layer computes lead-time alerts; a minimal web UI shows the compliance calendar. Document drafting + regs Q&A are a later phase (LLM on the swappable brain) and are NOT in this plan.

**Tech Stack:** Python 3.11, dataclasses, SQLite (profile store), pytest. Minimal web UI via Flask. No LLM, no network for the engine.

## Global Constraints (bind every task)

- **Deterministic law:** NO LLM anywhere in the date path. Dates are *computed*, never *generated*. (Drafting/Q&A are a separate later phase, not here.)
- **Cited or nothing:** every obligation instance carries its `cfr_citation`. The engine **never emits an uncited date, and never a date computed from incomplete profile data** — it emits an explicit "cannot compute, missing <field>" instead. Never guess a legal date.
- **Rules are declarative data**, inspectable/citable/attorney-reviewable — adding/fixing a rule is editing data, not engine surgery.
- **LEGAL CONSTANTS ARE PROVISIONAL:** every rule's date computation and its golden-test expected values are best-known *starting* encodings. They MUST be verified against the actual CFR text (the cited section) and confirmed in the broadcast-attorney read before production. Mark provisional rule logic with a `# VERIFY vs CFR` comment; the golden tests pin the *current* encoding so a later correction is a visible, deliberate change.
- **No auto-file:** the tool tracks/alerts (and later drafts); the licensee reviews and files. Nothing is ever submitted to the FCC by the tool.
- **Test env:** new repo's own venv, Python 3.11, `pytest`.

---

## Phase 0 — Repo + scaffold

### Task 0.1: New repo + package skeleton
**Files:** new repo `fcc-compliance/`; `pyproject.toml`; `fcc/__init__.py`; `tests/test_smoke.py`
- [ ] Create the repo + package layout: `fcc/rules.py`, `fcc/profile.py`, `fcc/engine.py`, `fcc/notify.py`, `fcc/ui/` (later). `pyproject.toml` with pytest configured.
- [ ] Failing test `tests/test_smoke.py`: `import fcc` succeeds and `fcc.__version__ == "0.1.0"`.
- [ ] Run → fail (no package). Implement minimal package. Run → pass. Commit.

---

## Phase 1 — Declarative rule definitions (the legal data)

### Task 1.1: Rule schema + the Quarterly Issues/Programs rule
**Files:** `fcc/rules.py`; `tests/test_rules.py`

**Interfaces — Produces:**
- `@dataclass(frozen=True) class Rule: id:str; cfr_citation:str; title:str; description:str; required_fields:tuple[str,...]; alert_lead_days:tuple[int,...]; due_dates: Callable[["StationProfile", int], list[date]]` — `due_dates(profile, horizon_days)` returns the obligation due-dates within `horizon_days` from today.
- `QUARTERLY_ISSUES_PROGRAMS: Rule` (§73.3526).

- [ ] **Failing test:** for a profile + 365-day horizon starting 2026-01-01, `QUARTERLY_ISSUES_PROGRAMS.due_dates(profile, 365)` returns `[date(2026,1,10), date(2026,4,10), date(2026,7,10), date(2026,10,10)]`, and `.cfr_citation == "47 CFR §73.3526"`, `.required_fields == ()` (no profile data needed — fixed calendar dates).
- [ ] Run → fail.
- [ ] **Implement** the `Rule` dataclass + the quarterly rule. The due_dates computes the Jan/Apr/Jul/Oct-10 dates within the horizon. `# VERIFY vs CFR: §73.3526 quarterly I/P list filing dates (10th of month after each quarter — well established, confirm).`
- [ ] Run → pass. Commit (`feat(rules): Rule schema + Quarterly I/P (§73.3526)`).

### Task 1.2: License renewal rule (profile-dependent)
**Files:** `fcc/rules.py`; `tests/test_rules.py`
**Interfaces — Produces:** `LICENSE_RENEWAL: Rule` (§73.3539), `required_fields=("license_expiration",)`.
- [ ] **Failing test:** a profile with `license_expiration = date(2028,10,1)` → `LICENSE_RENEWAL.due_dates(profile, horizon)` returns the renewal-application due date = the first day of the 4th full calendar month before expiration (`date(2028,6,1)`), and `required_fields == ("license_expiration",)`, `cfr_citation == "47 CFR §73.3539"`. (Horizon wide enough to include it.)
- [ ] Run → fail.
- [ ] **Implement** the renewal rule. `# VERIFY vs CFR: §73.3539 renewal application filing window (4 months before expiration — confirm exact mechanic + the broadcast attorney read).`
- [ ] Run → pass. Commit.

> Additional rules (EEO §73.2080, political file §73.1943) are added the same way — each its own small task: a `Rule` data definition + golden test + `# VERIFY vs CFR`. They are *data*, not new engine code. Add them once their date-math is verified; the engine handles any rule generically.

---

## Phase 2 — Station profile

### Task 2.1: StationProfile + required-fields completeness
**Files:** `fcc/profile.py`; `tests/test_profile.py`
**Interfaces — Produces:** `@dataclass(frozen=True) class StationProfile: call_sign:str; service:str ("AM"|"FM"); community_of_license:str; state:str; license_expiration: date | None = None`; `missing_for(rule: Rule) -> tuple[str,...]` (which of the rule's `required_fields` are None/absent).
- [ ] **Failing test:** a profile with `license_expiration=None` → `profile.missing_for(LICENSE_RENEWAL) == ("license_expiration",)`; a complete profile → `() `; `missing_for(QUARTERLY_ISSUES_PROGRAMS) == ()` always.
- [ ] Run → fail. Implement. Run → pass. Commit.

---

## Phase 3 — The deterministic deadline engine (rigor center)

### Task 3.1: compute_schedule
**Files:** `fcc/engine.py`; `tests/test_engine.py`
**Interfaces — Produces:**
- `@dataclass(frozen=True) class ObligationInstance: rule_id:str; cfr_citation:str; title:str; due_date:date`
- `@dataclass(frozen=True) class MissingDataFlag: rule_id:str; cfr_citation:str; title:str; missing_fields:tuple[str,...]`
- `compute_schedule(profile: StationProfile, rules: list[Rule], today: date, horizon_days: int) -> tuple[list[ObligationInstance], list[MissingDataFlag]]` — for each rule: if `profile.missing_for(rule)` is empty → compute due_dates → ObligationInstances (cited); else → a MissingDataFlag (NO date). Instances sorted by due_date.

- [ ] **Failing test (happy):** complete profile + `[QUARTERLY_ISSUES_PROGRAMS, LICENSE_RENEWAL]` + today=2026-01-01 + horizon=365 → instances are the 4 quarterly dates (cited §73.3526) sorted by date; flags empty (renewal due_date outside horizon → simply no instance, no flag).
- [ ] **Failing test (missing data → flagged, NOT guessed):** profile with `license_expiration=None` + `[LICENSE_RENEWAL]` → instances empty, flags == `[MissingDataFlag(rule_id="license_renewal", cfr_citation="47 CFR §73.3539", missing_fields=("license_expiration",))]`. Assert NO date is emitted for it.
- [ ] **Failing test (determinism):** same inputs twice → identical output.
- [ ] **Failing test (cited):** every returned ObligationInstance has a non-empty `cfr_citation`.
- [ ] Run → fail. Implement `compute_schedule`. Run → pass. Commit (`feat(engine): deterministic cited deadline schedule + missing-data flags`).

---

## Phase 4 — Notification layer

### Task 4.1: due_alerts (pure lead-time computation)
**Files:** `fcc/notify.py`; `tests/test_notify.py`
**Interfaces — Produces:** `@dataclass(frozen=True) class Alert: rule_id:str; cfr_citation:str; title:str; due_date:date; days_out:int`; `due_alerts(instances: list[ObligationInstance], today: date, lead_days: tuple[int,...]) -> list[Alert]` — an Alert for each (instance, lead) where `due_date - today == lead` days.
- [ ] **Failing test:** instance due 2026-01-10, today 2025-12-27, lead_days (30,14,3,1) → one Alert with `days_out=14`. today 2026-01-09 → `days_out=1`. today 2025-12-01 → no alert.
- [ ] Run → fail. Implement. Run → pass. Commit.

### Task 4.2: Notifier protocol + escalation
**Files:** `fcc/notify.py`; `tests/test_notify.py`
**Interfaces — Produces:** `class Notifier(Protocol): def send(self, alert: Alert, channel: str) -> bool`; `dispatch(alerts, notifier, channels: tuple[str,...]) -> list[DispatchResult]` — send each alert on the first channel; on `send` returning False (failure), escalate to the next channel; record per-alert outcome. (Real channel adapters — email/SMS/Signal reusing SOVERYN delivery — are wired at integration; MVP/tests use a fake Notifier.)
- [ ] **Failing test (fake notifier):** a notifier that fails channel "email" then succeeds on "sms" → `dispatch` escalates and records success on "sms"; a notifier that always succeeds → sends on the first channel only; an alert never silently dropped (always a DispatchResult).
- [ ] Run → fail. Implement. Run → pass. Commit.

---

## Phase 5 — Basic UI (structured; minimal web view)

**Files:** `fcc/ui/app.py` (Flask), `fcc/ui/templates/`. Tasks carry test intent; the read endpoints are pytest-testable (Flask test client), the rendered page is verified by a smoke check.
- [ ] **T5.1 Profile form** — create/edit a StationProfile (persist to SQLite). Test: POST profile → stored; GET → returned.
- [ ] **T5.2 Compliance calendar view** — `GET /` shows `compute_schedule(...)` output: each obligation with title, due_date, status, **CFR citation**, plus any MissingDataFlags ("can't compute X — add license_expiration"). Test: seeded profile → page lists the cited obligations + any flags.
- [ ] **T5.3 Alert settings** — view/edit lead-days + channels per station. Test: settings persist + feed `due_alerts`.

---

## Self-review notes
- Spec coverage: deterministic engine (Ph3), declarative cited rules (Ph1), profile + completeness (Ph2), multi-channel escalating alerts (Ph4), basic cited UI (Ph5), never-guess-a-date (Ph3 missing-data test), cited-or-nothing (Ph1/Ph3). Phase-2 drafting/Q&A correctly out (separate plan). 
- The legal date-constants in Ph1 are provisional-by-design — golden tests pin them so the CFR/attorney verification is a visible diff, not a silent assumption. This is the intended structure for a compliance tool, not a placeholder gap.
- Reuses SOVERYN delivery rails only at Ph4 integration (the Notifier adapter); the engine has zero external deps.
- Buildable + testable immediately (no LLM, no Spark). Sovereign Spark deployment + the generative drafting layer are later, separate efforts.
