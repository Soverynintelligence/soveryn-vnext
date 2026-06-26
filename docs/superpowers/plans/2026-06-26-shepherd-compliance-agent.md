# Shepherd Compliance Agent — Implementation Plan (slice 1: read-only grounded agent)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A station owner can chat with "Shepherd" on the dashboard — "what's upcoming, what's overdue, explain this rule" — and every answer is drawn ONLY from the deterministic engine's computed schedule; the model can never author a date or citation.

**Architecture:** The deterministic engine computes the schedule first; a pure `build_compliance_context` turns it into a factual text block; a `ChatAgent` (with an injected, swappable OpenAI-compatible client) sends that block + an honesty system prompt to the brain and returns the reply. A `POST /chat/<call_sign>` route + a UI panel wire it to the dashboard. A separate bake-off harness scores candidate brains. The chat is additive — the deterministic dashboard never depends on it.

**Tech Stack:** Python 3.11, Flask, `requests` (thin OpenAI-compatible client), pytest. Brain via a swappable `base_url`/`model`/`api_key` from a gitignored env.

## Global Constraints (bind every task)

- **Honesty spine:** the model is given ONLY the `ComplianceContext`. The system prompt forbids stating any date or CFR citation not present in that context; forbids legal *advice* (information only — the licensee files); requires citing the CFR section for any rule mentioned; and requires saying "I don't have that" for anything outside the data. The deterministic engine is authoritative.
- **Chat is additive, never load-bearing:** if the brain is unreachable/errors, the route returns a graceful message (HTTP 200) and the dashboard/calendar is unaffected. Never 500 the page because of the LLM.
- **Brain-agnostic:** `ChatAgent` takes an injected client implementing a `ChatClient` protocol (`chat(messages) -> str`). The concrete client is runtime config (base_url/model/api_key env). **Cloud candidates use sample/public data only.**
- **No correctness test depends on a live model** — use a fake `ChatClient`. The bake-off (Task 5) is a separate selection tool, not part of the unit suite.
- **Repo:** `~/shepherd`, package `shepherd`. Tests: `cd ~/shepherd && ~/miniconda3/envs/soveryn/bin/python -m pytest -v`.

---

## Task 1: ComplianceContext builder (pure)

**Files:** Create `shepherd/agent/__init__.py`, `shepherd/agent/context.py`; Test `tests/test_agent_context.py`

**Interfaces — Produces:**
- `build_compliance_context(profile: StationProfile, instances: list[ObligationInstance], flags: list[MissingDataFlag], today: date) -> str` — a deterministic factual block. `instances`/`flags` are the output of `compute_schedule`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import date
from shepherd.profile import StationProfile
from shepherd.engine import compute_schedule
from shepherd.rules import ALL_RULES
from shepherd.agent.context import build_compliance_context

def _wgrc():
    return StationProfile(call_sign="WGRC", service="FM", community_of_license="Lewisburg",
                          state="PA", station_type="NCE", license_expiration=date(2027, 4, 1))

def test_context_lists_obligations_with_dates_and_citations():
    p = _wgrc()
    today = date(2026, 6, 26)
    instances, flags = compute_schedule(profile=p, rules=list(ALL_RULES), today=today, horizon_days=365)
    ctx = build_compliance_context(p, instances, flags, today)
    assert "WGRC" in ctx and "NCE" in ctx
    assert "2026-06-26" in ctx                      # today is present
    assert "47 CFR §73.3526" in ctx                 # quarterly citation
    assert "2026-07-10" in ctx                      # a computed due date
    assert "47 CFR §73.3539" in ctx                 # renewal citation
    assert "2026-12-01" in ctx                      # renewal due date

def test_context_shows_missing_data_not_a_fake_date():
    p = StationProfile(call_sign="WJTL", service="FM", community_of_license="Lancaster",
                       state="PA", station_type="NCE", license_expiration=None)
    today = date(2026, 6, 26)
    instances, flags = compute_schedule(profile=p, rules=list(ALL_RULES), today=today, horizon_days=365)
    ctx = build_compliance_context(p, instances, flags, today)
    assert "license_expiration" in ctx              # the missing field is named
    assert "47 CFR §73.3539" in ctx                 # renewal cited as cannot-compute
    # renewal must NOT carry a computed due date anywhere in the block
    assert "cannot compute" in ctx.lower() or "missing" in ctx.lower()

def test_context_is_deterministic():
    p = _wgrc(); today = date(2026, 6, 26)
    inst, fl = compute_schedule(profile=p, rules=list(ALL_RULES), today=today, horizon_days=365)
    assert build_compliance_context(p, inst, fl, today) == build_compliance_context(p, inst, fl, today)
```

- [ ] **Step 2: Run → FAIL** (`No module named 'shepherd.agent'`). `pytest tests/test_agent_context.py -v`

- [ ] **Step 3: Implement** `shepherd/agent/context.py`

```python
"""Pure builder: turns the deterministic schedule into the factual block the LLM reads.

The LLM sees ONLY what this returns. It must contain every authoritative date+citation
and must NEVER contain a date the engine did not compute.
"""
from __future__ import annotations

from datetime import date

from shepherd.engine import MissingDataFlag, ObligationInstance
from shepherd.profile import StationProfile


def build_compliance_context(
    profile: StationProfile,
    instances: list[ObligationInstance],
    flags: list[MissingDataFlag],
    today: date,
) -> str:
    lines: list[str] = []
    lines.append(
        f"Station: {profile.call_sign} · {profile.station_type} · {profile.service} "
        f"· {profile.community_of_license}, {profile.state}"
    )
    lines.append(f"Today: {today.isoformat()}")
    lines.append("")
    lines.append("UPCOMING OBLIGATIONS (computed by the deterministic engine — authoritative):")
    if instances:
        for inst in instances:
            days = (inst.due_date - today).days
            when = "OVERDUE" if days < 0 else f"in {days} days"
            lines.append(
                f"- {inst.title} — due {inst.due_date.isoformat()} ({when}) — {inst.cfr_citation}"
            )
    else:
        lines.append("- none in the next 365 days")
    if flags:
        lines.append("")
        lines.append("CANNOT COMPUTE (missing required data — no date exists for these):")
        for fl in flags:
            missing = ", ".join(fl.missing_fields)
            lines.append(f"- {fl.title} — {fl.cfr_citation} — missing: {missing}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run → PASS**

- [ ] **Step 5: Commit** (`feat(agent): ComplianceContext builder — deterministic factual block`)

---

## Task 2: Swappable OpenAI-compatible client

**Files:** Create `shepherd/agent/llm_client.py`; Test `tests/test_agent_client.py`

**Interfaces — Produces:**
- `class ChatClient(Protocol): def chat(self, messages: list[dict]) -> str: ...`
- `class OpenAICompatibleClient: __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 30.0)`; `.chat(messages) -> str` — POSTs to `{base_url}/chat/completions`, returns `choices[0].message.content`.
- `client_from_env() -> OpenAICompatibleClient | None` — reads `SHEPHERD_LLM_BASE_URL`, `SHEPHERD_LLM_MODEL`, `SHEPHERD_LLM_API_KEY`; returns None if base_url/model unset (so the app runs without a brain configured).

- [ ] **Step 1: Write the failing test** (mock HTTP — no live call)

```python
from shepherd.agent.llm_client import OpenAICompatibleClient

class _FakeResp:
    status_code = 200
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p

def test_client_posts_and_parses(monkeypatch):
    captured = {}
    def fake_post(url, json, headers, timeout):
        captured["url"] = url; captured["json"] = json; captured["headers"] = headers
        return _FakeResp({"choices": [{"message": {"content": "hello"}}]})
    import shepherd.agent.llm_client as mod
    monkeypatch.setattr(mod.requests, "post", fake_post)
    c = OpenAICompatibleClient(base_url="http://x/v1", model="m", api_key="k")
    out = c.chat([{"role": "user", "content": "hi"}])
    assert out == "hello"
    assert captured["url"] == "http://x/v1/chat/completions"
    assert captured["json"]["model"] == "m"
    assert captured["json"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["headers"]["Authorization"] == "Bearer k"

def test_client_from_env_none_when_unset(monkeypatch):
    from shepherd.agent.llm_client import client_from_env
    monkeypatch.delenv("SHEPHERD_LLM_BASE_URL", raising=False)
    assert client_from_env() is None
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `shepherd/agent/llm_client.py`

```python
"""Thin, swappable OpenAI-compatible chat client (vLLM / NVIDIA NIM / OpenRouter / Spark)."""
from __future__ import annotations

import os
from typing import Protocol

import requests


class ChatClient(Protocol):
    def chat(self, messages: list[dict]) -> str: ...


class OpenAICompatibleClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, messages: list[dict]) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json={"model": self.model, "messages": messages},
            headers=headers,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def client_from_env() -> "OpenAICompatibleClient | None":
    base_url = os.environ.get("SHEPHERD_LLM_BASE_URL")
    model = os.environ.get("SHEPHERD_LLM_MODEL")
    if not base_url or not model:
        return None
    return OpenAICompatibleClient(base_url, model, os.environ.get("SHEPHERD_LLM_API_KEY"))
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(agent): swappable OpenAI-compatible LLM client + env config`)

---

## Task 3: ChatAgent (the honesty law)

**Files:** Create `shepherd/agent/chat_agent.py`; Test `tests/test_agent_chat.py`

**Interfaces — Produces:**
- `SYSTEM_PROMPT: str` (the persona + honesty law).
- `class ChatAgent: __init__(self, client: ChatClient)`; `reply(self, context: str, history: list[dict], user_message: str) -> str` — assembles `[{system: SYSTEM_PROMPT}, {system: "COMPLIANCE DATA:\n"+context}, *history, {user: user_message}]`, calls `client.chat(...)`, returns the content.

- [ ] **Step 1: Write the failing test** (fake client captures the messages)

```python
from shepherd.agent.chat_agent import ChatAgent, SYSTEM_PROMPT

class _FakeClient:
    def __init__(self): self.seen = None
    def chat(self, messages): self.seen = messages; return "ANSWER"

def test_agent_grounds_and_enforces_honesty():
    fc = _FakeClient()
    agent = ChatAgent(fc)
    out = agent.reply(context="UPCOMING: Quarterly — 47 CFR §73.3526", history=[], user_message="what's up?")
    assert out == "ANSWER"
    # honesty law is in the system prompt
    sys = fc.seen[0]
    assert sys["role"] == "system"
    low = sys["content"].lower()
    assert "only" in low and "context" in low or "compliance data" in low
    assert "advice" in low          # UPL guard mentioned
    # the computed context is passed to the model
    joined = " ".join(m["content"] for m in fc.seen)
    assert "47 CFR §73.3526" in joined
    # the user's question is last
    assert fc.seen[-1] == {"role": "user", "content": "what's up?"}

def test_agent_includes_history():
    fc = _FakeClient()
    ChatAgent(fc).reply(context="X", history=[{"role": "user", "content": "earlier"},
                                              {"role": "assistant", "content": "prior"}],
                        user_message="now")
    contents = [m["content"] for m in fc.seen]
    assert "earlier" in contents and "prior" in contents and "now" in contents
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `shepherd/agent/chat_agent.py`

```python
"""Shepherd's grounded chat agent. The model only ever sees the computed ComplianceContext."""
from __future__ import annotations

from shepherd.agent.llm_client import ChatClient

SYSTEM_PROMPT = (
    "You are Shepherd, an FCC compliance assistant for a single radio station. "
    "You help the licensee understand their compliance obligations and deadlines.\n\n"
    "STRICT RULES (a wrong or invented date can cost the station a fine — never do it):\n"
    "1. Answer ONLY using the COMPLIANCE DATA provided to you in this conversation. "
    "It is computed by a deterministic engine and is authoritative.\n"
    "2. NEVER state a deadline date or a CFR citation that is not present in the COMPLIANCE DATA. "
    "Do not estimate, guess, or infer dates. If a date is not in the data, it does not exist for you.\n"
    "3. When you mention a rule, include the CFR section exactly as written in the data.\n"
    "4. If the data says an obligation 'cannot compute' because of missing information, tell the "
    "user what to add — never produce a date for it.\n"
    "5. You provide compliance INFORMATION, not legal ADVICE. The licensee reviews and files. "
    "Do not tell them what they are legally required to decide; explain what the rules and their "
    "computed deadlines are.\n"
    "6. If asked something outside this station's compliance data, say you don't have that "
    "information and that you track FCC compliance for this station.\n"
    "Be concise, clear, and on-task."
)


class ChatAgent:
    def __init__(self, client: ChatClient):
        self.client = client

    def reply(self, context: str, history: list[dict], user_message: str) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": "COMPLIANCE DATA:\n" + context},
            *history,
            {"role": "user", "content": user_message},
        ]
        return self.client.chat(messages)
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** (`feat(agent): ChatAgent + honesty system prompt`)

---

## Task 4: /chat route + UI panel

**Files:** Modify `shepherd/ui/app.py`; Modify `shepherd/ui/templates/calendar.html`; Modify `shepherd/ui/static/style.css`; Test `tests/test_ui_chat.py`

**Interfaces — Consumes:** `build_compliance_context` (T1), `ChatAgent` (T3), `client_from_env` (T2), `compute_schedule`/`ALL_RULES`.
**Produces:** `create_app(store, chat_agent=None)` (new optional param); `POST /chat/<call_sign>` accepting JSON `{"message": str, "history": [...]?}` → JSON `{"reply": str, "error": bool}`.

- [ ] **Step 1: Write the failing test**

```python
import json
from datetime import date
from shepherd.profile import StationProfile
from shepherd.store import ProfileStore
from shepherd.ui.app import create_app

class _FakeAgent:
    def __init__(self, text="REPLY", boom=False): self.text=text; self.boom=boom; self.last=None
    def reply(self, context, history, user_message):
        if self.boom: raise RuntimeError("brain down")
        self.last = (context, history, user_message); return self.text

def _client(tmp_path, agent):
    store = ProfileStore(str(tmp_path / "t.db"))
    store.save(StationProfile("WGRC","FM","Lewisburg","PA","NCE", date(2027,4,1)))
    return create_app(store, chat_agent=agent).test_client(), store

def test_chat_returns_grounded_reply(tmp_path):
    agent = _FakeAgent("here is your status")
    client, _ = _client(tmp_path, agent)
    r = client.post("/chat/WGRC", json={"message": "what's up?"})
    assert r.status_code == 200
    assert r.get_json()["reply"] == "here is your status"
    # the agent was handed a context mentioning the real citation (grounding wired through the route)
    assert "47 CFR §73.3526" in agent.last[0]

def test_chat_unknown_station_404(tmp_path):
    client, _ = _client(tmp_path, _FakeAgent())
    assert client.post("/chat/NOPE", json={"message":"hi"}).status_code == 404

def test_chat_brain_error_is_graceful_not_500(tmp_path):
    client, _ = _client(tmp_path, _FakeAgent(boom=True))
    r = client.post("/chat/WGRC", json={"message":"hi"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["error"] is True
    assert "calendar" in body["reply"].lower()  # points user to the still-accurate dashboard
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** — in `shepherd/ui/app.py`: add the import block and the param + route.

```python
# add imports at top
from shepherd.agent.context import build_compliance_context
# (compute_schedule, ALL_RULES, date already imported in app.py)

def create_app(store, chat_agent=None):   # add chat_agent param (default None)
    app = Flask(__name__, template_folder="templates")
    # ... existing routes unchanged ...

    @app.route("/chat/<call_sign>", methods=["POST"])
    def chat(call_sign):
        profile = store.get(call_sign)
        if profile is None:
            return {"reply": f"No station {call_sign} on file.", "error": True}, 404
        if chat_agent is None:
            return {"reply": "The assistant isn't configured yet, but your calendar above is accurate.",
                    "error": True}, 200
        data = request.get_json(silent=True) or {}
        message = (data.get("message") or "").strip()
        history = data.get("history") or []
        today = date.today()
        instances, flags = compute_schedule(profile=profile, rules=list(ALL_RULES),
                                            today=today, horizon_days=365)
        context = build_compliance_context(profile, instances, flags, today)
        try:
            reply = chat_agent.reply(context=context, history=history, user_message=message)
            return {"reply": reply, "error": False}, 200
        except Exception:
            return {"reply": "I can't reach my brain right now — but your calendar above is still accurate.",
                    "error": True}, 200

    return app
```

Also: where the app is actually constructed for serving (e.g. `run_demo.py`), build the agent from env: `from shepherd.agent.llm_client import client_from_env; from shepherd.agent.chat_agent import ChatAgent; _c = client_from_env(); agent = ChatAgent(_c) if _c else None; create_app(store, chat_agent=agent)`. (Existing `create_app(store)` calls keep working — `chat_agent` defaults to None.)

- [ ] **Step 4: UI panel** — add a chat panel to `calendar.html` (message list + input) and a small `fetch`-based script that POSTs to `/chat/<call_sign>`, appends the user message + the reply, and maintains a `history` array in JS. Style it in `style.css` to match the dashboard (card, message bubbles). Keep it minimal. (Verify by loading `/calendar/WGRC` and confirming the panel renders; the route logic is covered by the tests above.)

- [ ] **Step 5: Run → PASS** (full suite green), then **Commit** (`feat(ui): /chat route + dashboard chat panel (additive, graceful)`)

---

## Task 5: Brain bake-off harness

**Files:** Create `shepherd/agent/bakeoff.py`, `shepherd/agent/scenarios.py`; Test `tests/test_agent_bakeoff.py`

**Interfaces — Produces:**
- `SCENARIOS: list[Scenario]` where `Scenario` = `{name, profile, question, expect_out_of_scope: bool}`.
- `score_reply(reply: str, context: str, scenario) -> dict` — automatable honesty checks: `invented_date` (any `YYYY-MM-DD` in reply not in context → fail), `invented_citation` (any `47 CFR §...` in reply not in context → fail), `refused` (for out-of-scope scenarios, did it decline?).
- `run_bakeoff(candidates: list[ChatClient], today: date) -> list[dict]` — for each candidate × scenario: compute schedule → build context → ChatAgent.reply → `score_reply`; returns a scored report.

- [ ] **Step 1: Write the failing test** (scoring logic tested with a FAKE client — no live brain)

```python
from datetime import date
from shepherd.agent.bakeoff import score_reply

def test_score_flags_invented_date():
    ctx = "UPCOMING: Quarterly — due 2026-07-10 — 47 CFR §73.3526"
    bad = score_reply("Your renewal is due 2099-01-01.", ctx, scenario=None)
    assert bad["invented_date"] is True          # 2099-01-01 not in context
    good = score_reply("Quarterly is due 2026-07-10.", ctx, scenario=None)
    assert good["invented_date"] is False

def test_score_flags_invented_citation():
    ctx = "47 CFR §73.3526"
    bad = score_reply("See 47 CFR §99.9999.", ctx, scenario=None)
    assert bad["invented_citation"] is True
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement** `bakeoff.py` (scoring + runner) and `scenarios.py` (the scenario set). `score_reply` uses regex: dates `\b\d{4}-\d{2}-\d{2}\b`, citations `47 CFR §[\d.]+`; any token in the reply not present in `context` → invented. `run_bakeoff` loops candidates × `SCENARIOS`, building real contexts via `compute_schedule` + `build_compliance_context`, calling `ChatAgent(candidate).reply(...)`, scoring each, and returning rows `{candidate, scenario, invented_date, invented_citation, refused, reply}`. Scenario set covers: upcoming, overdue (seed a past due_date via an expiration that lands renewal in the past), missing-data station, "explain §73.3526", an out-of-scope question (`expect_out_of_scope=True`), an ambiguous one.

- [ ] **Step 4: Run → PASS** (scoring logic green with the fake)

- [ ] **Step 5: Commit** (`feat(agent): brain bake-off harness + honesty scoring`)

> **Running the actual bake-off (separate from the suite):** set `SHEPHERD_LLM_BASE_URL`/`MODEL`/`API_KEY` for each candidate (cloud Nemotron-Nano-3-Omni via NVIDIA NIM/OpenRouter; local vett-scotty at `http://localhost:8090/v1` model `vett-scotty`; others), construct an `OpenAICompatibleClient` per candidate, call `run_bakeoff([...], date.today())`, and read the scored report. **Cloud candidates: sample/public data only.** The automatable checks (invented date/citation, refusal) are the hard gates; tone/grounding get a human read (and optionally an LLM-judge). Pick the winner; wire it via the env. This step needs the key(s) — run when available.

---

## Self-review notes
- Spec coverage: honesty spine (T1 context + T3 system prompt + T5 scoring), context-injection grounding (T1→T3→T4), swappable seam (T2), ChatAgent (T3), /chat route + additive/graceful error handling (T4), chat UI (T4), bake-off + rubric’s automatable checks (T5), fake-client tests / no live-model dependency (T1–T5). Statuses overlay is omitted by design (the "address obligations" feature isn’t built yet; folds into `build_compliance_context` when it ships — YAGNI for slice 1).
- The deterministic engine is untouched; the agent only consumes its output.
- Buildable + testable now (T1–T4 fully; T5’s scoring logic too). Only the live bake-off run needs the cloud key.
