# Shepherd Drafting — Quarterly Issues/Programs List Implementation Plan (phase-2 slice 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** From a Quarterly Issues/Programs obligation, the owner enters issues + programs (validated at the form), and the LLM (Gemma, via the existing seam) formats them into a cited DRAFT document — code-stamped "for licensee & attorney review," never auto-filed — behind a `DRAFTING_ENABLED` gate.

**Architecture:** A draft store keyed to the obligation instance (immutable key, full status lifecycle). A grounded draft generator that gets ONLY the owner's validated entries + a provisional §73.3526 requirements block, and whose output is wrapped in a deterministic DRAFT stamp + citation (code-enforced, not model-trusted). Routes gated on a `DRAFTING_ENABLED` flag (default false). All additive — never blocks the calendar.

**Tech Stack:** Python 3.11, Flask, SQLite, the existing `ChatClient` seam, pytest. Spec: `~/soveryn_vnext/docs/superpowers/specs/2026-06-26-shepherd-drafting-design.md`.

## Global Constraints (bind every task)

- **No-invention is a prompt POSTURE, not a guarantee:** the system prompt biases the model to format-only-the-given-facts; the real safeguards are (1) deterministic engine owns the deadline+citation, (2) model sees ONLY the owner's entries, (3) the prompt, (4) the human/attorney review. Never call it a "guarantee."
- **DRAFT stamp + citation are CODE-enforced**, not left to the model: the generator wraps the model body in a deterministic header carrying "DRAFT — prepared by Shepherd; requires licensee & attorney review before filing" + "47 CFR §73.3526".
- **`SHEPHERD_DRAFTING_ENABLED` defaults FALSE** — drafting routes/UI are gated on it; the attorney sign-off flips it true. No drafting in production until then.
- **Validation at the FORM layer, never the LLM.** Thin/incomplete entries are rejected before generation.
- **Entry shape:** one issue → nested programs: `{"issue": str, "programs": [{"program_title", "air_date", "duration", "description"}, ...]}`. The exact §73.3526 field set is provisional (attorney-gated).
- **Additive / never-500:** an LLM error → entries saved, graceful message; the calendar is untouched. Immutable draft key. Nothing auto-files.
- **Repo:** `~/shepherd`, package `shepherd`. Tests: `cd ~/shepherd && ~/miniconda3/envs/soveryn/bin/python -m pytest -v`.

---

## Task 1: Entry model + form-level validation (pure)

**Files:** Create `shepherd/agent/draft_validate.py`; Test `tests/test_draft_validate.py`

**Interfaces — Produces:** `validate_entries(entries: list[dict]) -> list[str]` — returns a list of human-readable error strings (empty list = valid). Rules: at least one issue; each issue has a non-empty `issue` and a non-empty `programs` list; each program has non-empty `program_title`, `air_date`, `duration`, and a `description` of at least 20 characters.

- [ ] **Step 1: Write the failing test**

```python
from shepherd.agent.draft_validate import validate_entries

def _prog(**kw):
    base = {"program_title": "Community Forum", "air_date": "2026-04-12",
            "duration": "30 min", "description": "A panel on local school budget cuts and their impact."}
    base.update(kw); return base

def _issue(**kw):
    base = {"issue": "School budget cuts", "programs": [_prog()]}
    base.update(kw); return base

def test_valid_entries_pass():
    assert validate_entries([_issue()]) == []

def test_no_issues_fails():
    errs = validate_entries([])
    assert errs and any("at least one issue" in e.lower() for e in errs)

def test_issue_without_programs_fails():
    assert validate_entries([_issue(programs=[])])

def test_program_missing_title_fails():
    assert validate_entries([_issue(programs=[_prog(program_title="")])])

def test_short_description_fails():
    assert validate_entries([_issue(programs=[_prog(description="too short")])])

def test_missing_air_date_or_duration_fails():
    assert validate_entries([_issue(programs=[_prog(air_date="")])])
    assert validate_entries([_issue(programs=[_prog(duration="")])])
```

- [ ] **Step 2: Run → FAIL** (`No module named 'shepherd.agent.draft_validate'`).
- [ ] **Step 3: Implement** `shepherd/agent/draft_validate.py`:

```python
"""Form-level validation for draft entries. The LLM is NOT the validation layer —
incomplete entries are rejected here, before generation."""
from __future__ import annotations

_MIN_DESC = 20


def validate_entries(entries: list[dict]) -> list[str]:
    errors: list[str] = []
    if not entries:
        return ["Add at least one issue with a program before generating a draft."]
    for i, issue in enumerate(entries, 1):
        label = (issue.get("issue") or "").strip()
        if not label:
            errors.append(f"Issue {i}: the issue description is required.")
        programs = issue.get("programs") or []
        if not programs:
            errors.append(f"Issue {i} ({label or '?'}): add at least one program that addressed it.")
        for j, prog in enumerate(programs, 1):
            for field in ("program_title", "air_date", "duration"):
                if not (prog.get(field) or "").strip():
                    errors.append(f"Issue {i}, program {j}: '{field}' is required.")
            desc = (prog.get("description") or "").strip()
            if len(desc) < _MIN_DESC:
                errors.append(f"Issue {i}, program {j}: description must be at least {_MIN_DESC} characters.")
    return errors
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(draft): form-level entry validation`)

---

## Task 2: Draft store

**Files:** Modify `shepherd/store.py`; Test `tests/test_draft_store.py`

**Interfaces — Produces (on `ProfileStore`, new table `obligation_drafts`):**
- `save_draft(call_sign, rule_id, due_date: date, entries: list[dict], draft_text: str = "", status: str = "draft") -> None` — upsert keyed `(call_sign, rule_id, due_date)`; `entries` stored as JSON.
- `get_draft(call_sign, rule_id, due_date: date) -> dict | None` — returns `{"entries": list, "draft_text": str, "status": str, "filed_at": date | None}`.
- `set_draft_filed(call_sign, rule_id, due_date: date) -> None` — if a draft exists, set `status="filed"`, `filed_at=date.today()` (no-op if no draft).

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.store import ProfileStore

def test_draft_round_trip_and_filed(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    entries = [{"issue": "X", "programs": [{"program_title": "P", "air_date": "2026-04-12",
                "duration": "30 min", "description": "d"*30}]}]
    s.save_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10), entries, draft_text="DRAFT...", status="generated")
    d = s.get_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10))
    assert d["entries"] == entries and d["draft_text"] == "DRAFT..." and d["status"] == "generated"
    assert d["filed_at"] is None
    s.set_draft_filed("WGRC", "quarterly_issues_programs", date(2026, 4, 10))
    d2 = s.get_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10))
    assert d2["status"] == "filed" and d2["filed_at"] is not None

def test_get_draft_none_when_absent(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    assert s.get_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10)) is None

def test_save_draft_upserts(tmp_path):
    s = ProfileStore(str(tmp_path / "t.db"))
    s.save_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10), [], status="draft")
    s.save_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10), [], draft_text="v2", status="edited")
    assert s.get_draft("WGRC", "quarterly_issues_programs", date(2026, 4, 10))["status"] == "edited"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — add the `obligation_drafts` table to `_init_db` (idempotent; PK `(call_sign, rule_id, due_date)`; columns `entries_json, draft_text, status, filed_at`), and the three methods, following the existing parameterized `INSERT … ON CONFLICT DO UPDATE` pattern. `json.dumps(entries)` in, `json.loads` out; `due_date`/`filed_at` as ISO strings (parse `filed_at` back to `date`).
- [ ] **Step 4: Run → PASS** (full suite green)
- [ ] **Step 5: Commit** (`feat(store): obligation draft store (save/get/set_filed)`)

---

## Task 3: Draft generator (grounded + code-stamped)

**Files:** Create `shepherd/agent/draft.py`; Test `tests/test_draft_generator.py`

**Interfaces — Consumes:** `ChatClient` (`shepherd/agent/llm_client.py`). **Produces:**
- `REQUIREMENTS_73_3526: str` (provisional formatting-requirements block — attorney-gated config).
- `DRAFT_SYSTEM_PROMPT: str` (the format-not-invent honesty posture).
- `generate_draft(profile, obligation: dict, entries: list[dict], client) -> str` — `obligation` = `{"title", "due_date", "cfr_citation"}`. Returns a **deterministic DRAFT header** (stamp + citation + station + quarter) followed by the LLM-formatted body.

- [ ] **Step 1: Write the failing test** (fake client — no live model)

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.agent.draft import generate_draft, DRAFT_SYSTEM_PROMPT

class _FakeClient:
    def __init__(self): self.seen = None
    def chat(self, messages): self.seen = messages; return "<formatted body>"

def _p(): return StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1))
_OBL = {"title": "Quarterly Issues/Programs List", "due_date": date(2026,4,10), "cfr_citation": "47 CFR §73.3526"}
_ENTRIES = [{"issue":"School budget cuts","programs":[{"program_title":"Community Forum",
            "air_date":"2026-04-12","duration":"30 min","description":"A panel on local school budget cuts."}]}]

def test_generate_draft_is_stamped_and_cited_deterministically():
    fc = _FakeClient()
    out = generate_draft(_p(), _OBL, _ENTRIES, fc)
    # stamp + citation are CODE-enforced, present regardless of model output
    assert "DRAFT" in out and "requires licensee & attorney review before filing" in out
    assert "47 CFR §73.3526" in out
    assert "<formatted body>" in out          # the model body is included

def test_generator_grounds_only_on_entries_and_honesty_prompt():
    fc = _FakeClient()
    generate_draft(_p(), _OBL, _ENTRIES, fc)
    sys = fc.seen[0]["content"].lower()
    assert "only" in sys and ("invent" in sys or "fabricat" in sys)   # format-not-invent posture
    joined = " ".join(m["content"] for m in fc.seen)
    assert "School budget cuts" in joined and "Community Forum" in joined   # the entries are passed
    assert "73.3526" in joined                                              # the framing/citation
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `shepherd/agent/draft.py`:

```python
"""Grounded draft generator for the Quarterly Issues/Programs list.
The model formats ONLY the owner-provided entries (prompt posture, not a guarantee).
The DRAFT stamp + citation are code-enforced — never left to the model."""
from __future__ import annotations

import json

# PROVISIONAL — attorney-gated. The §73.3526 formatting requirements block.
REQUIREMENTS_73_3526 = (
    "An Issues/Programs list documents the station's most significant treatment of "
    "community issues for the quarter. For each issue, list the program(s) that addressed it "
    "with: program title, air date, duration, and a brief narrative of how it addressed the issue. "
    "Use ONLY the issues and programs provided below. Do not add, infer, or embellish any issue, "
    "program, date, or duration. (PROVISIONAL pending broadcast-attorney confirmation.)"
)

DRAFT_SYSTEM_PROMPT = (
    "You format an FCC Quarterly Issues/Programs list from facts the licensee provides. "
    "STRICT RULES:\n"
    "1. Use ONLY the issues and programs given to you. NEVER invent, infer, or embellish an "
    "issue, a program, a date, a duration, or any fact. If a detail isn't provided, omit it — "
    "do not fabricate it.\n"
    "2. Organize the output by issue, listing each program that addressed it with its title, "
    "air date, duration, and the provided narrative.\n"
    "3. This is document preparation, not legal advice. Produce only the formatted list body — "
    "no commentary, no added recommendations.\n"
    "Format cleanly and professionally."
)


def _stamp_header(profile, obligation: dict) -> str:
    return (
        "DRAFT — prepared by Shepherd; requires licensee & attorney review before filing. NOT FILED.\n"
        f"{obligation['cfr_citation']}\n"
        f"Station: {profile.call_sign} ({profile.service}, {profile.community_of_license}, {profile.state})\n"
        f"{obligation['title']} — quarter due {obligation['due_date'].isoformat()}\n"
        "=" * 60
    )


def _format_entries(entries: list[dict]) -> str:
    return json.dumps(entries, indent=2)


def generate_draft(profile, obligation: dict, entries: list[dict], client) -> str:
    messages = [
        {"role": "system", "content": DRAFT_SYSTEM_PROMPT},
        {"role": "system", "content":
            f"REQUIREMENTS ({obligation['cfr_citation']}):\n{REQUIREMENTS_73_3526}\n\n"
            f"ENTRIES (the ONLY facts you may use):\n{_format_entries(entries)}"},
        {"role": "user", "content": "Produce the Issues/Programs list body from the entries above."},
    ]
    body = client.chat(messages)
    return _stamp_header(profile, obligation) + "\n\n" + body
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(draft): grounded generator with code-enforced DRAFT stamp + citation`)

---

## Task 4: DRAFTING_ENABLED gate + draft routes + /address filed-link

**Files:** Modify `shepherd/ui/app.py`, `run_demo.py`; Test `tests/test_ui_draft.py`

**Interfaces — Consumes:** `validate_entries` (T1), draft store methods (T2), `generate_draft` (T3). **Produces:** `create_app(store, chat_agent=None, draft_client=None, drafting_enabled=None)` — `drafting_enabled` defaults to `os.environ.get("SHEPHERD_DRAFTING_ENABLED","").lower() in ("1","true","yes")`. Routes (all 404 with a friendly "drafting not enabled" body when `drafting_enabled` is false):
- `GET /draft/<call_sign>/<rule_id>/<due_date>` — entry form, pre-filled from `get_draft`.
- `POST /draft/<call_sign>/<rule_id>/<due_date>/save` — parse entries from the form into the nested shape; `validate_entries`; errors → re-render with them; else `save_draft(..., status="draft")` → redirect to the draft page.
- `POST /draft/<call_sign>/<rule_id>/<due_date>/generate` — load the saved entries; if none/invalid → redirect back; else `generate_draft(profile, obligation, entries, draft_client)` inside try/except (LLM error → graceful message, status stays `draft`, never 500) → `save_draft(..., draft_text=..., status="generated")`. (Regenerate posts here again — overwrites; the UI warns if status was `edited`.)
- `POST /draft/<call_sign>/<rule_id>/<due_date>/edit` — save edited `draft_text`, status `edited`.

Also: in the existing `POST /address/<call_sign>`, after `mark_addressed`, call `store.set_draft_filed(call_sign, rule_id, due_date)` (links the filing to the draft for the audit trail).

- [ ] **Step 1: Write the failing tests**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.store import ProfileStore
from shepherd.ui.app import create_app

class _FakeClient:
    def chat(self, messages): return "<body>"

def _client(tmp_path, enabled=True):
    store = ProfileStore(str(tmp_path / "t.db"))
    store.save(StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1)))
    app = create_app(store, draft_client=_FakeClient(), drafting_enabled=enabled)
    return app.test_client(), store

RID, DUE = "quarterly_issues_programs", "2026-04-10"

def test_drafting_gated_off_when_disabled(tmp_path):
    client, _ = _client(tmp_path, enabled=False)
    assert client.get(f"/draft/WGRC/{RID}/{DUE}").status_code == 404

def test_save_rejects_thin_entries(tmp_path):
    client, store = _client(tmp_path)
    # one issue, program missing description → validation rejects, nothing saved as generated
    r = client.post(f"/draft/WGRC/{RID}/{DUE}/save", data={
        "issue_0":"X","prog_0_0_title":"P","prog_0_0_air_date":"2026-04-12",
        "prog_0_0_duration":"30 min","prog_0_0_description":"short"})
    assert r.status_code in (200, 400)        # re-rendered with errors, not a redirect to a saved draft
    assert store.get_draft("WGRC", RID, date(2026,4,10)) in (None,) or \
           store.get_draft("WGRC", RID, date(2026,4,10))["status"] == "draft"

def test_generate_produces_stamped_draft(tmp_path):
    client, store = _client(tmp_path)
    client.post(f"/draft/WGRC/{RID}/{DUE}/save", data={
        "issue_0":"School budget cuts","prog_0_0_title":"Community Forum",
        "prog_0_0_air_date":"2026-04-12","prog_0_0_duration":"30 min",
        "prog_0_0_description":"A thirty minute panel on the local school budget cuts."})
    client.post(f"/draft/WGRC/{RID}/{DUE}/generate")
    d = store.get_draft("WGRC", RID, date(2026,4,10))
    assert d["status"] == "generated"
    assert "DRAFT" in d["draft_text"] and "47 CFR §73.3526" in d["draft_text"]

def test_address_links_draft_filed(tmp_path):
    client, store = _client(tmp_path)
    store.save_draft("WGRC", RID, date(2026,4,10), [], draft_text="x", status="generated")
    client.post("/address/WGRC", data={"rule_id": RID, "due_date": DUE})
    assert store.get_draft("WGRC", RID, date(2026,4,10))["status"] == "filed"
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** the routes + the gate + the `/address` filed-link per the interfaces above. Parse the nested issue/program form fields (`issue_<i>`, `prog_<i>_<j>_title|air_date|duration|description`) into the entry shape. Keep every route additive (try/except around the generate call; never 500). Gate: a small helper returns a 404 + "drafting not yet enabled" when `not drafting_enabled`, called at the top of each draft route. Update `run_demo.py` to pass `draft_client=client_from_env()` and `create_app(store, chat_agent=agent, draft_client=_c, drafting_enabled=...)` (reads the env flag by default).
- [ ] **Step 4: Run → PASS** (full suite green)
- [ ] **Step 5: Commit** (`feat(ui): DRAFTING_ENABLED-gated draft routes + /address draft filed-link`)

---

## Task 5: UI — entry form + draft view

**Files:** Create `shepherd/ui/templates/draft_form.html`, `shepherd/ui/templates/draft_view.html`; Modify `shepherd/ui/templates/calendar.html`, `shepherd/ui/static/style.css`

- [ ] **T5 UI** (render-verified; route logic covered by Task 4 tests):
  - `draft_form.html`: a nested entry form — add/remove issues, and under each issue add/remove programs (title, air date, duration, description), with the field names matching Task 4's parser (`issue_<i>`, `prog_<i>_<j>_*`). Show validation errors when present. A small JS helper to add issue/program rows. "Save" posts to `/save`.
  - `draft_view.html`: shows the generated `draft_text` (monospace), an **edit** textarea (posts to `/edit`), a **Regenerate** button that **warns if status is `edited`** ("Regenerating replaces the current draft — your edits will be lost"), and **copy/download**. The DRAFT stamp is already in the text (code-enforced).
  - `calendar.html`: on each **Quarterly Issues/Programs** obligation card (missed or upcoming), add a **"Draft this filing"** link to `/draft/<call_sign>/quarterly_issues_programs/<due_date>` — only rendered when drafting is enabled (pass `drafting_enabled` to the template).
  - Style to match the premium dashboard.
  - **Verify:** with `drafting_enabled=True`, load the draft form + draft view render; with it false, the calendar shows no "Draft this filing" link.
- [ ] **Commit** (`feat(ui): draft entry form + draft view + calendar drafting link`)

---

## Self-review notes
- Spec coverage: nested issue→programs model + form validation (T1), draft store w/ lifecycle + filed_at audit link (T2), grounded generator + code-enforced DRAFT stamp/citation + provisional §73.3526 block (T3), DRAFTING_ENABLED code gate + routes + additive generation + /address filed-link + regeneration-overwrite (T4/T5), entry-form UI (T5). Honesty-as-posture, validation-at-form-not-LLM, immutable key, no-auto-submit — all in Global Constraints + the relevant tasks.
- Clone-from-last-quarter + paste/import are explicitly slice-2 (named UX debt in the spec) — NOT in this plan.
- Buildable + testable now (the seam is live); the bake-off already picked Gemma. Production drafting stays gated on `SHEPHERD_DRAFTING_ENABLED` + the attorney sign-off.
