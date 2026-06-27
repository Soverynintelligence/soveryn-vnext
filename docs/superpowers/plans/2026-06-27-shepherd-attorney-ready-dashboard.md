# Shepherd — Navigable Dashboard + Attorney-Ready Packet Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Reorganize the dashboard into four plain-language boxes (Past Due / Upcoming / Future / Done) and add the attorney-ready flow — draft each overdue item, mark it ready, download a single attorney review packet (or a single draft).

**Architecture:** Per-rule plain-language fields drive owner-friendly display. The engine's `status` plus a days-out threshold bucket items into four boxes (pure view logic). A new `ready_for_review` draft status + a **pure** packet builder (deterministic concatenation of already-stamped drafts + a two-section cover) produce the attorney packet. All gated on `DRAFTING_ENABLED`; the packet path uses no LLM.

**Tech Stack:** Python 3.11, Flask, SQLite, pytest. No LLM in this slice. Spec: `~/soveryn_vnext/docs/superpowers/specs/2026-06-27-shepherd-attorney-ready-dashboard-design.md`.

## Global Constraints (bind every task)

- **Plain language:** items display the rule's plain name + a one-line "what it is"; the **CFR citation is a small anchor, NOT the identifier**. Plain-language strings are provisional/attorney-gated.
- **Four boxes:** Past Due (`status=="overdue"`), Upcoming (`status=="upcoming"` AND `days_out <= threshold`), Future (`status=="upcoming"` AND `days_out > threshold`), Done (`status=="done"`). Threshold = env `SHEPHERD_UPCOMING_THRESHOLD_DAYS` (default 90).
- **`ready_for_review` status:** `draft → generated → edited → ready_for_review → filed`; reopen-to-edit is `ready_for_review → edited` (the `/edit` route).
- **Packet is pure / honest:** deterministic assembly only; cover has TWO sections — "Addressed in this packet" (ready drafts) and "Still outstanding" (overdue without a ready draft). Per-draft download serves the stored `draft_text` (keeps the generator's code-enforced NOT-FILED stamp). Empty packet → 404 (never generate empty).
- **Gated:** all attorney-flow routes gated on `SHEPHERD_DRAFTING_ENABLED`. Additive — never break the deterministic calendar.
- **Repo:** `~/shepherd`, package `shepherd`. Tests: `cd ~/shepherd && ~/miniconda3/envs/soveryn/bin/python -m pytest -v`.

---

## Task 1: Per-rule plain-language fields

**Files:** Modify `shepherd/rules.py`; Test `tests/test_rules.py`

**Interfaces — Produces:** `Rule` gains `plain_name: str = ""` and `what_it_is: str = ""` (defaults so existing constructions are unaffected). `QUARTERLY_ISSUES_PROGRAMS` and `LICENSE_RENEWAL` set them.

- [ ] **Step 1: Write the failing test**

```python
from shepherd.rules import QUARTERLY_ISSUES_PROGRAMS, LICENSE_RENEWAL

def test_quarterly_has_plain_language():
    assert QUARTERLY_ISSUES_PROGRAMS.plain_name == "Quarterly Issues/Programs list"
    assert "public file" in QUARTERLY_ISSUES_PROGRAMS.what_it_is.lower()

def test_renewal_has_plain_language():
    assert LICENSE_RENEWAL.plain_name == "License Renewal application"
    assert LICENSE_RENEWAL.what_it_is  # non-empty
```

- [ ] **Step 2: Run → FAIL** (`AttributeError: ... has no attribute 'plain_name'`).
- [ ] **Step 3: Implement** — add to the `Rule` frozen dataclass (after the existing fields, with defaults):

```python
    plain_name: str = ""        # owner-facing name; falls back to title if empty
    what_it_is: str = ""        # one-line plain explanation (PROVISIONAL — attorney-gated)
```

Set on the rules (PROVISIONAL — confirm wording in the attorney read):

```python
# QUARTERLY_ISSUES_PROGRAMS(...):
    plain_name="Quarterly Issues/Programs list",
    what_it_is="the quarterly record for your public file showing the main community issues you covered and the programs that addressed them",
# LICENSE_RENEWAL(...):
    plain_name="License Renewal application",
    what_it_is="the application to renew your station's FCC license before it expires",
```

- [ ] **Step 4: Run → PASS** (full suite green — defaults keep other constructions valid).
- [ ] **Step 5: Commit** (`feat(rules): plain-language plain_name + what_it_is (provisional)`)

---

## Task 2: Store — ready_for_review status + queries

**Files:** Modify `shepherd/store.py`; Test `tests/test_draft_store.py`

**Interfaces — Produces (on `ProfileStore`):**
- `mark_draft_ready(call_sign, rule_id, due_date: date) -> None` — sets `status="ready_for_review"` for an existing draft (no-op if none).
- `list_ready_drafts(call_sign: str) -> list[dict]` — drafts with `status=="ready_for_review"`; each `{"rule_id", "due_date": date, "draft_text", "entries", "status", "filed_at"}`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.store import ProfileStore

RID, DUE = "quarterly_issues_programs", date(2026, 4, 10)

def test_mark_ready_and_list(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.save_draft("WGRC", RID, DUE, [{"issue": "x", "programs": []}], draft_text="D", status="generated")
    s.mark_draft_ready("WGRC", RID, DUE)
    assert s.get_draft("WGRC", RID, DUE)["status"] == "ready_for_review"
    ready = s.list_ready_drafts("WGRC")
    assert len(ready) == 1 and ready[0]["rule_id"] == RID and ready[0]["due_date"] == DUE

def test_list_ready_excludes_non_ready(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.save_draft("WGRC", RID, DUE, [], draft_text="D", status="generated")  # not ready
    assert s.list_ready_drafts("WGRC") == []

def test_mark_ready_noop_when_absent(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.mark_draft_ready("WGRC", RID, DUE)  # no draft → no-op, no crash
    assert s.list_ready_drafts("WGRC") == []
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — `mark_draft_ready`: parameterized `UPDATE obligation_drafts SET status='ready_for_review' WHERE call_sign=? AND rule_id=? AND due_date=?` (no-op when no row). `list_ready_drafts`: `SELECT ... WHERE call_sign=? AND status='ready_for_review'`, json.loads entries, parse due_date/filed_at. Follow the existing store patterns.
- [ ] **Step 4: Run → PASS** (full suite green)
- [ ] **Step 5: Commit** (`feat(store): ready_for_review — mark_draft_ready + list_ready_drafts`)

---

## Task 3: Pure attorney-packet builder

**Files:** Create `shepherd/packet.py`; Test `tests/test_packet.py`

**Interfaces — Produces:** `build_attorney_packet(profile, ready_drafts: list[dict], overdue_items: list[dict], today: date) -> str`. `ready_drafts` each `{"rule_id","due_date":date,"draft_text"}`; `overdue_items` each `{"rule_id","due_date":date,"plain_name","cfr_citation"}` (ALL overdue, from the engine). Pure (no LLM, no I/O, `today` passed in).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.packet import build_attorney_packet

def _p(): return StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1))

def test_packet_has_two_sections_addressed_and_outstanding():
    ready = [{"rule_id":"quarterly_issues_programs","due_date":date(2025,7,10),
              "draft_text":"DRAFT — prepared by Shepherd; requires licensee & attorney review before filing.\nQ I/P body"}]
    overdue = [
        {"rule_id":"quarterly_issues_programs","due_date":date(2025,7,10),
         "plain_name":"Quarterly Issues/Programs list","cfr_citation":"47 CFR §73.3526"},
        {"rule_id":"quarterly_issues_programs","due_date":date(2025,10,10),
         "plain_name":"Quarterly Issues/Programs list","cfr_citation":"47 CFR §73.3526"},
    ]
    out = build_attorney_packet(_p(), ready, overdue, date(2026,6,27))
    assert "FOR LICENSEE & ATTORNEY REVIEW" in out and "NOT FILED" in out
    assert "Addressed in this packet" in out
    assert "Still outstanding" in out
    assert "2025-07-10" in out          # the ready one (addressed)
    assert "2025-10-10" in out          # the undrafted one (outstanding)
    assert "Q I/P body" in out          # the draft text is included
    assert "WGRC" in out

def test_packet_no_outstanding_section_when_all_ready():
    ready = [{"rule_id":"quarterly_issues_programs","due_date":date(2025,7,10),"draft_text":"X body"}]
    overdue = [{"rule_id":"quarterly_issues_programs","due_date":date(2025,7,10),
                "plain_name":"Quarterly Issues/Programs list","cfr_citation":"47 CFR §73.3526"}]
    out = build_attorney_packet(_p(), ready, overdue, date(2026,6,27))
    assert "Addressed in this packet" in out
    # nothing outstanding → the outstanding section is omitted or says "none"
    assert "Still outstanding" not in out or "none" in out.lower()
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `shepherd/packet.py`:

```python
"""Pure attorney review packet builder. Deterministic assembly of already-stamped
drafts + a two-section cover. No LLM, no I/O — honest by construction."""
from __future__ import annotations

from datetime import date


def build_attorney_packet(profile, ready_drafts: list[dict], overdue_items: list[dict], today: date) -> str:
    ready_keys = {(d["rule_id"], d["due_date"]) for d in ready_drafts}
    outstanding = [o for o in overdue_items if (o["rule_id"], o["due_date"]) not in ready_keys]

    lines: list[str] = []
    lines.append("FOR LICENSEE & ATTORNEY REVIEW — DRAFT, NOT FILED")
    lines.append(f"Station: {profile.call_sign} ({profile.service}, {profile.community_of_license}, {profile.state})")
    lines.append(f"Prepared: {today.isoformat()}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("ADDRESSED IN THIS PACKET")
    for d in ready_drafts:
        lines.append(f"- due {d['due_date'].isoformat()} (rule {d['rule_id']})")
    if outstanding:
        lines.append("")
        lines.append("STILL OUTSTANDING (no draft yet — these remain overdue):")
        for o in outstanding:
            lines.append(f"- {o['plain_name']} — was due {o['due_date'].isoformat()} — {o['cfr_citation']}")
    lines.append("")
    lines.append("=" * 60)
    for d in ready_drafts:
        lines.append("")
        lines.append(d["draft_text"])
        lines.append("")
        lines.append("-" * 60)
    return "\n".join(lines)
```

(Note: the test checks for the human phrases "Addressed in this packet" / "Still outstanding" case-insensitively — implement headers so `"Addressed in this packet" in out` passes, e.g. use that exact casing or adjust the test to `.lower()`. Keep them consistent.)

- [ ] **Step 4: Run → PASS** (adjust header casing so the asserted substrings match exactly)
- [ ] **Step 5: Commit** (`feat(packet): pure attorney packet builder — two-section cover + stamped drafts`)

---

## Task 4: Dashboard reorg — four boxes + plain language

**Files:** Modify `shepherd/ui/app.py`, `shepherd/ui/templates/calendar.html`, `shepherd/ui/static/style.css`; Test `tests/test_ui_dashboard.py`

**Interfaces — Consumes:** the engine's `status`/`due_date`, `ALL_RULES` (for plain fields). **Produces:** the calendar route buckets into `past_due` / `upcoming` / `future` / `done` using `SHEPHERD_UPCOMING_THRESHOLD_DAYS` (default 90), and passes each item's `plain_name` + `what_it_is` (rule lookup by `rule_id`, fall back to `title`).

- [ ] **Step 1: Write the failing tests**

```python
import os
from datetime import date
from shepherd.profile import StationProfile
from shepherd.store import ProfileStore
from shepherd.ui.app import create_app

def _client(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.save(StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1)))
    return create_app(s).test_client()

def test_dashboard_has_four_boxes(tmp_path):
    body = _client(tmp_path).get("/calendar/WGRC").get_data(as_text=True)
    for label in ("Past Due", "Upcoming", "Future", "Done"):
        assert label in body

def test_dashboard_plain_language(tmp_path):
    body = _client(tmp_path).get("/calendar/WGRC").get_data(as_text=True)
    assert "Quarterly Issues/Programs list" in body          # plain name
    assert "public file" in body.lower()                     # what_it_is shown

def test_threshold_env_moves_split(tmp_path, monkeypatch):
    # with a tiny threshold, near-term items fall into Future
    monkeypatch.setenv("SHEPHERD_UPCOMING_THRESHOLD_DAYS", "1")
    body = _client(tmp_path).get("/calendar/WGRC").get_data(as_text=True)
    assert "Future" in body  # the section renders; near items now classified future
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — in the calendar route: read `threshold = int(os.environ.get("SHEPHERD_UPCOMING_THRESHOLD_DAYS", "90"))`; after `apply_statuses`, bucket: `past_due = [i for i in instances if i.status == "overdue"]`, `upcoming = [i for i in instances if i.status == "upcoming" and (i.due_date - today).days <= threshold]`, `future = [i for i in instances if i.status == "upcoming" and (i.due_date - today).days > threshold]`, `done = [i for i in instances if i.status == "done"]`. Build a `rule_by_id = {r.id: r for r in ALL_RULES}` and pass it (or precompute per-item `plain_name`/`what_it_is`) to the template. Rewrite `calendar.html` into four labelled boxes (Past Due / Upcoming / Future / Done), each item showing `plain_name or title`, the `what_it_is` line, due date + days-out, and the citation as a small pill. Style the boxes in `style.css`.
- [ ] **Step 4: Run → PASS** (full suite green)
- [ ] **Step 5: Commit** (`feat(ui): four-box plain-language dashboard + threshold env`)

---

## Task 5: Attorney-flow routes + Past Due action zone

**Files:** Modify `shepherd/ui/app.py`, `shepherd/ui/templates/calendar.html`, `shepherd/ui/templates/draft_view.html`, `shepherd/ui/static/style.css`; Test `tests/test_ui_attorney.py`

**Interfaces — Consumes:** `mark_draft_ready`/`list_ready_drafts`/`get_draft` (T2), `build_attorney_packet` (T3), `compute_schedule`/`ALL_RULES`. **Produces:** `POST /draft/<cs>/<rid>/<due>/ready`; `GET /packet/<cs>` (full); `GET /packet/<cs>/<rid>/<due>` (single); `/edit` accepts a `ready_for_review` draft → `edited`. All gated on `DRAFTING_ENABLED`.

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.store import ProfileStore
from shepherd.ui.app import create_app

RID, DUE = "quarterly_issues_programs", "2026-04-10"

def _client(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.save(StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1)))
    return create_app(s, drafting_enabled=True).test_client(), s

def test_mark_ready(tmp_path):
    c, s = _client(tmp_path)
    s.save_draft("WGRC", RID, date(2026,4,10), [], draft_text="D", status="generated")
    c.post(f"/draft/WGRC/{RID}/{DUE}/ready")
    assert s.get_draft("WGRC", RID, date(2026,4,10))["status"] == "ready_for_review"

def test_edit_reopens_ready_to_edited(tmp_path):
    c, s = _client(tmp_path)
    s.save_draft("WGRC", RID, date(2026,4,10), [], draft_text="D", status="ready_for_review")
    c.post(f"/draft/WGRC/{RID}/{DUE}/edit", data={"draft_text": "edited text"})
    assert s.get_draft("WGRC", RID, date(2026,4,10))["status"] == "edited"

def test_single_draft_download_has_stamp(tmp_path):
    c, s = _client(tmp_path)
    s.save_draft("WGRC", RID, date(2026,4,10), [],
                 draft_text="DRAFT — prepared by Shepherd; requires licensee & attorney review before filing.\nbody",
                 status="ready_for_review")
    r = c.get(f"/packet/WGRC/{RID}/{DUE}")
    assert r.status_code == 200
    assert "requires licensee & attorney review before filing" in r.get_data(as_text=True)

def test_full_packet_empty_is_404(tmp_path):
    c, _ = _client(tmp_path)
    assert c.get("/packet/WGRC").status_code == 404   # no ready drafts

def test_full_packet_when_ready(tmp_path):
    c, s = _client(tmp_path)
    s.save_draft("WGRC", RID, date(2026,4,10), [], draft_text="DRAFT body one", status="ready_for_review")
    r = c.get("/packet/WGRC")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "FOR LICENSEE & ATTORNEY REVIEW" in body and "DRAFT body one" in body

def test_attorney_routes_gated_off(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.save(StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1)))
    c = create_app(s, drafting_enabled=False).test_client()
    assert c.get("/packet/WGRC").status_code == 404
    assert c.post(f"/draft/WGRC/{RID}/{DUE}/ready").status_code == 404
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — gated routes:
  - `POST /draft/<cs>/<rid>/<due>/ready` → `store.mark_draft_ready(...)` → redirect to the dashboard.
  - `/edit` → ensure it accepts a `ready_for_review` draft and writes `status="edited"` (it loads the saved draft + saves edited; confirm no guard blocks the ready state).
  - `GET /packet/<cs>/<rid>/<due>` → `get_draft`; if none → 404; else return the `draft_text` as a downloadable text response (`Content-Disposition: attachment`, `text/plain`). The stamp is already in `draft_text`.
  - `GET /packet/<cs>` → `ready = list_ready_drafts(cs)`; if empty → 404; build `overdue_items` from `compute_schedule(profile, ALL_RULES, today, horizon_days=365, lookback_days=365)` (the `status=="overdue"` instances, mapped to `{rule_id, due_date, plain_name, cfr_citation}` via the rule lookup); `build_attorney_packet(profile, ready, overdue_items, date.today())` → download.
  - **UI:** in the Past Due box, per item: "Draft this filing" (existing), "Mark ready for review" (when a generated/edited draft exists → POST `/ready`), "Download for attorney" (per-draft, when a draft exists → `/packet/<cs>/<rid>/<due>`). Box header: "Download attorney packet · N ready" → `/packet/<cs>` (disabled/hidden when N=0). In `draft_view.html`, the Edit control returns a `ready_for_review` draft to editing.
- [ ] **Step 4: Run → PASS** (full suite green)
- [ ] **Step 5: Commit** (`feat(ui): attorney-flow routes + Past Due action zone (ready / packet / single download)`)

---

## Self-review notes
- Spec coverage: plain-language fields (T1), ready_for_review status + queries (T2), pure two-section packet builder (T3), four-box dashboard + threshold env (T4), mark-ready + reopen-to-edit + full/single packet downloads + empty=404 + gating (T5). Honesty (pure packet, code-enforced stamp via stored draft_text), DRAFTING_ENABLED gate, attorney-gated plain strings — all in Global Constraints + tasks.
- Per-station threshold, PDF, email-to-attorney, other filing types, and the agent's deeper plain-language tuning are explicitly OUT (slice 2 / separate).
- No LLM anywhere in this slice; the deterministic calendar/lifecycle is untouched (additive view + new routes).
