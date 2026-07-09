# @Soveryn_AI Presence Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A daemon that pulls niche + mention tweets off Jon's X Pro API, ranks them, has Aetheria draft posts/replies in her voice, sends each draft to Jon over Signal for approve/edit/reject, and publishes only what he approves to @Soveryn_AI.

**Architecture:** Hybrid (C). A mechanical daemon (`soveryn/agents/presence/`) mirrors the Ares daemon pattern: `scan_once()` ingests → dedups → scores → stores candidates → invokes Aetheria's `AgentLoop.process_message` to draft → sends the draft to Signal. A separate reply handler resolves Jon's Signal reply against the pending draft and, on approval, calls the publisher. All external edges (X API, Aetheria loop, Signal) are injected so the whole thing is unit-testable with fakes and no network.

**Tech Stack:** Python 3.11 (soveryn conda env), `httpx` (thin X wrappers, no X SDK), SQLite (candidate + signal-log stores, mirroring existing `soveryn/platform/*/store.py`), pytest.

## Global Constraints

- **Python 3.11**, run tests with `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest` (NOT base 3.13).
- **No third-party X SDK** — thin `httpx` wrappers over the 2–3 endpoints used.
- **Credentials only from env**, exact names: `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET`, `X_BEARER_TOKEN`. Never log a credential value.
- **Nothing publishes without Jon's explicit approval.** A pending draft is inert until a matching Signal reply resolves it. Bias to safety: any reply that is not a clear approve/reject token is treated as an *edit* (publishes Jon's exact text), never as a blind approve.
- **Every draft carries provenance** — a `based_on` string naming what it is grounded in. A draft with empty provenance is flagged in the Signal message, never silently sent as fact.
- **The daemon never fabricates and never double-posts:** dedup by tweet_id, record our own posted ids, publish failure returns the item to pending (never a silent drop, never a silent repost).
- **Match SOVERYN patterns:** daemon mirrors `soveryn/agents/ares/daemon.py` + `__main__.py`; tools registered for `owner="aetheria"` via `ToolRegistry`; systemd user unit mirrors `soveryn-ares.service` **plus** the parakeet start-limit lesson (`StartLimitIntervalSec=300`/`StartLimitBurst=5`).
- **Injected edges for tests:** X client, Aetheria draft function, and Signal sender are all constructor-injected; unit tests pass fakes. A single `@pytest.mark.rig` test (opt-in, real creds) is the only thing that touches live X.

---

## File Structure

```
soveryn/agents/presence/
  __init__.py
  config.py           # PresenceConfig: niche terms, thresholds, env var names, poll interval
  x_client.py         # XClient: search_recent(), create_tweet(), reply_tweet(); XClientError; from_env()
  scorer.py           # score_tweet(tweet, cfg) -> float  (pure; niche match + author + recency + mention boost)
  candidate_store.py  # CandidateStore: upsert(), pending_ranked(), mark(), record_posted_id(), is_seen()
  drafting.py         # draft_for_candidate(candidate, draft_fn) -> Draft | None   (Draft carries provenance)
  approval.py         # format_signal_message(draft), classify_reply(text) -> Decision
  publisher.py        # publish(draft, x_client, store) -> PublishResult
  signal_log.py       # SignalLog: record(draft_id, action, original, final, reason)
  daemon.py           # PresenceDaemonSurface: scan_once(), run_forever(); resolve_reply()
  __main__.py         # entrypoint mirroring ares (__main__)
tests/agents/presence/
  test_config.py test_x_client.py test_scorer.py test_candidate_store.py
  test_drafting.py test_approval.py test_publisher.py test_signal_log.py test_daemon.py
~/.config/systemd/user/soveryn-presence.service
```

**Deferred code reads (do them inside the task that needs them, not before):**
- Task 6 (drafting): confirm `ConversationStore.new_session(agent, title=...)` and `AgentLoop.process_message(session_id, user_message) -> ChatResponse` (mapped: `loop.py:753`, returns `ChatResponse.content` / `.finish_reason`).
- Task 8 (approval send/receive): read `soveryn/agents/ares/signal_sender.py` for the send API and the Signal bot inbound path for how Jon's replies arrive; wire `resolve_reply()` to it. Until then, the Signal edge is a `send_fn(text) -> None` injected callable.
- Task 10 (observer skip): `soveryn/platform/salience/observer.py:19` skip-prefix tuple — add `"[presence]"`.

---

### Task 1: PresenceConfig

**Files:**
- Create: `soveryn/agents/presence/config.py`
- Test: `tests/agents/presence/test_config.py`

**Interfaces:**
- Produces: `PresenceConfig` (frozen dataclass) with `niche_terms: tuple[str,...]`, `own_handle: str="Soveryn_AI"`, `score_threshold: float`, `max_drafts_per_scan: int`, `poll_interval_seconds: float`, `db_path: Path`, `signal_log_path: Path`. Classmethod `default() -> PresenceConfig`.

- [ ] **Step 1: Write the failing test**
```python
from soveryn.agents.presence.config import PresenceConfig

def test_default_config_has_niche_and_own_handle():
    cfg = PresenceConfig.default()
    assert cfg.own_handle == "Soveryn_AI"
    assert any("sovereign" in t.lower() for t in cfg.niche_terms)
    assert cfg.score_threshold > 0
    assert cfg.max_drafts_per_scan >= 1
```
- [ ] **Step 2: Run it, verify it fails** — `pytest tests/agents/presence/test_config.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement**
```python
from dataclasses import dataclass
from pathlib import Path

_NICHE = (
    "sovereign AI", "local LLM", "on-device AI", "open-weight models",
    "AI honesty", "AI confabulation", "AI hallucination", "AI reliability",
    "local-first AI", "AI companions",
)

@dataclass(frozen=True)
class PresenceConfig:
    niche_terms: tuple[str, ...]
    own_handle: str
    score_threshold: float
    max_drafts_per_scan: int
    poll_interval_seconds: float
    db_path: Path
    signal_log_path: Path

    @classmethod
    def default(cls) -> "PresenceConfig":
        base = Path.home() / "soveryn_vnext" / "data"
        return cls(
            niche_terms=_NICHE, own_handle="Soveryn_AI", score_threshold=2.0,
            max_drafts_per_scan=3, poll_interval_seconds=300.0,
            db_path=base / "presence_candidates.db",
            signal_log_path=base / "presence_signal_log.db",
        )
```
- [ ] **Step 4: Run test, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): PresenceConfig with niche terms + thresholds`.

---

### Task 2: XClient (thin httpx wrappers)

**Files:**
- Create: `soveryn/agents/presence/x_client.py`
- Test: `tests/agents/presence/test_x_client.py`

**Interfaces:**
- Produces: `XClient` with `search_recent(query: str, since_id: str|None=None) -> list[Tweet]`, `create_tweet(text: str) -> str` (returns new tweet id), `reply_tweet(text: str, in_reply_to: str) -> str`. `Tweet` frozen dataclass: `id, author, text, url`. `XClientError(Exception)`. Classmethod `from_env(http=None)` builds credentials from the five env vars; a `_transport`/`http` client is injectable for tests. **Never** put credential values in exception messages or logs.
- Consumes: nothing (leaf).

- [ ] **Step 1: Write the failing test (injected fake HTTP — no network)**
```python
import pytest
from soveryn.agents.presence.x_client import XClient, Tweet, XClientError

class FakeResp:
    def __init__(self, status, json): self.status_code, self._j = status, json
    def json(self): return self._j

class FakeHTTP:
    def __init__(self, resp): self.resp, self.calls = resp, []
    def get(self, url, **kw): self.calls.append(("GET", url, kw)); return self.resp
    def post(self, url, **kw): self.calls.append(("POST", url, kw)); return self.resp

def test_search_recent_parses_tweets():
    http = FakeHTTP(FakeResp(200, {"data": [
        {"id": "1", "author_id": "a", "text": "local LLM honesty"}]}))
    c = XClient(bearer="B", oauth=("k","s","t","ts"), http=http)
    out = c.search_recent("local LLM")
    assert out == [Tweet(id="1", author="a", text="local LLM honesty",
                         url="https://x.com/i/web/status/1")]

def test_create_tweet_returns_id():
    http = FakeHTTP(FakeResp(201, {"data": {"id": "99"}}))
    c = XClient(bearer="B", oauth=("k","s","t","ts"), http=http)
    assert c.create_tweet("hello") == "99"

def test_error_status_raises_without_leaking_creds():
    http = FakeHTTP(FakeResp(403, {"title": "Forbidden"}))
    c = XClient(bearer="B", oauth=("k","s","t","ts"), http=http)
    with pytest.raises(XClientError) as e:
        c.create_tweet("x")
    assert "403" in str(e.value) and "B" not in str(e.value)
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — `search_recent` GETs `https://api.twitter.com/2/tweets/search/recent` with `Authorization: Bearer` (app-only read), `params={"query": query, "tweet.fields": "author_id", ...}` and `since_id` when given; parses `data[]` into `Tweet` (url = `https://x.com/i/web/status/{id}`). `create_tweet`/`reply_tweet` POST `https://api.twitter.com/2/tweets` with an **OAuth 1.0a user-context** `Authorization` header built from the four oauth tokens (use `httpx`/`requests_oauthlib`-style signing or a minimal HMAC-SHA1 signer — a helper `_oauth1_header(method, url, oauth)`); body `{"text": ...}` (+ `{"reply": {"in_reply_to_tweet_id": ...}}` for replies); returns `data.id`. Any non-2xx → `raise XClientError(f"X API {resp.status_code}: {resp.json().get('title','?')}")` (never include tokens). `from_env(http=None)` reads the five env vars, raising `XClientError("missing X_* env var: <name>")` if any absent.
- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): XClient thin httpx wrappers (read+write), creds from env`.

---

### Task 3: score_tweet (pure relevance scorer)

**Files:**
- Create: `soveryn/agents/presence/scorer.py`
- Test: `tests/agents/presence/test_scorer.py`

**Interfaces:**
- Produces: `score_tweet(tweet: Tweet, cfg: PresenceConfig, *, is_mention: bool=False, now_ts: float|None=None, tweet_ts: float|None=None) -> float`. Pure. Score = (# distinct niche terms matched, case-insensitive, ×1.0) + (mention boost 3.0 if `is_mention`) + (recency bonus up to 1.0 for tweets < 6h old). Returns 0.0 when nothing matches and not a mention.
- Consumes: `Tweet` (Task 2), `PresenceConfig` (Task 1).

- [ ] **Step 1: Write the failing test**
```python
from soveryn.agents.presence.scorer import score_tweet
from soveryn.agents.presence.x_client import Tweet
from soveryn.agents.presence.config import PresenceConfig

CFG = PresenceConfig.default()

def test_niche_match_scores_per_term():
    t = Tweet("1","a","thoughts on sovereign AI and local LLM reliability","u")
    assert score_tweet(t, CFG) >= 2.0   # two distinct niche terms

def test_mention_gets_boost_even_without_niche():
    t = Tweet("2","a","hey @Soveryn_AI what do you think?","u")
    assert score_tweet(t, CFG, is_mention=True) >= 3.0

def test_offtopic_scores_zero():
    assert score_tweet(Tweet("3","a","my lunch was great","u"), CFG) == 0.0
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the additive scorer described in Interfaces (lowercase substring match on `cfg.niche_terms`, dedup matched terms; `+3.0` if `is_mention`; recency bonus only when both timestamps given).
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): pure relevance scorer (niche + mention + recency)`.

---

### Task 4: CandidateStore (dedup + ranking + posted-id ledger)

**Files:**
- Create: `soveryn/agents/presence/candidate_store.py`
- Test: `tests/agents/presence/test_candidate_store.py`

**Interfaces:**
- Produces: `CandidateStore(db_path: Path)` with `is_seen(tweet_id) -> bool`, `upsert(candidate: Candidate) -> None`, `pending_ranked(limit: int) -> list[Candidate]` (status `pending`, `score DESC`), `mark(tweet_id, status)` (`pending|drafted|awaiting_approval|posted|rejected|failed`), `record_posted_id(tweet_id)` (marks a tweet id as one WE posted so it's never re-ingested). `Candidate` frozen dataclass: `tweet_id, author, text, url, kind ("topic"|"mention"|"reply"), score, status, created_at`.
- Consumes: nothing (SQLite leaf; mirror `soveryn/platform/coordination/store.py` connection/`os.replace`-free simple pattern).

- [ ] **Step 1: Write the failing test**
```python
from soveryn.agents.presence.candidate_store import CandidateStore, Candidate

def _c(tid, score=1.0, status="pending"):
    return Candidate(tid,"a","t","u","topic",score,status,"2026-07-09T00:00:00")

def test_dedup_and_seen(tmp_path):
    s = CandidateStore(tmp_path/"c.db")
    assert not s.is_seen("1")
    s.upsert(_c("1"))
    assert s.is_seen("1")

def test_pending_ranked_by_score(tmp_path):
    s = CandidateStore(tmp_path/"c.db")
    s.upsert(_c("1", score=1.0)); s.upsert(_c("2", score=5.0))
    assert [c.tweet_id for c in s.pending_ranked(10)] == ["2", "1"]

def test_posted_id_counts_as_seen(tmp_path):
    s = CandidateStore(tmp_path/"c.db")
    s.record_posted_id("42")
    assert s.is_seen("42")   # our own post never re-ingested as a fresh mention
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — one table `candidates(tweet_id PK, author, text, url, kind, score, status, created_at)` plus a `posted_ids(tweet_id PK)` table. `is_seen` = present in either table. `upsert` = `INSERT OR IGNORE`. `pending_ranked` = `SELECT ... WHERE status='pending' ORDER BY score DESC LIMIT ?`. Bootstrap schema idempotently in `__init__`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): CandidateStore (dedup, ranking, posted-id ledger)`.

---

### Task 5: draft_for_candidate (Aetheria drafting + mandatory provenance)

**Files:**
- Create: `soveryn/agents/presence/drafting.py`
- Test: `tests/agents/presence/test_drafting.py`

**Interfaces:**
- Produces: `Draft` frozen dataclass: `candidate_tweet_id, kind, text, based_on (provenance), in_reply_to: str|None`. `draft_for_candidate(candidate: Candidate, draft_fn: Callable[[str], str]) -> Draft | None`. `draft_fn` takes a prompt, returns Aetheria's raw text; drafting.py builds the prompt (instructing her to output a JSON object `{"post": "...", "based_on": "...", "skip": false}`), parses it, and returns `None` when `skip` is true or the post is empty. A parsed post with empty `based_on` is allowed through but the `Draft.based_on` is set to the literal `"(none stated)"` so the Signal message can flag it.
- Consumes: `Candidate` (Task 4). `draft_fn` is where the real `AgentLoop.process_message(session_id, prompt).content` gets wired (Task 6); tests pass a fake.

- [ ] **Step 1: Write the failing test**
```python
from soveryn.agents.presence.drafting import draft_for_candidate, Draft
from soveryn.agents.presence.candidate_store import Candidate

C = Candidate("1","a","local LLM honesty?","u","reply",3.0,"pending","t")

def test_draft_carries_provenance():
    fn = lambda p: '{"post":"Grounded honesty beats confident guessing.","based_on":"our confab measurements","skip":false}'
    d = draft_for_candidate(C, fn)
    assert isinstance(d, Draft) and d.based_on == "our confab measurements"
    assert d.in_reply_to == "1" and d.kind == "reply"

def test_skip_returns_none():
    fn = lambda p: '{"post":"","based_on":"","skip":true}'
    assert draft_for_candidate(C, fn) is None

def test_missing_provenance_flagged_not_dropped():
    fn = lambda p: '{"post":"a claim","based_on":"","skip":false}'
    d = draft_for_candidate(C, fn)
    assert d is not None and d.based_on == "(none stated)"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — build the prompt (candidate text + kind + instruction to reply in her voice, substantively, grounded, and to emit the JSON contract; instruct her to set `skip:true` if nothing worth saying — silence is valid). Parse JSON defensively (a non-JSON return → treat as skip, return `None`, so a malformed generation never becomes a post). `in_reply_to = candidate.tweet_id` when `kind` is `reply`/`mention`, else `None`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): Aetheria drafting with mandatory provenance + skip path`.

---

### Task 6: Wire real Aetheria draft_fn (session + AgentLoop)

**Files:**
- Create: `soveryn/agents/presence/aetheria_bridge.py`
- Test: `tests/agents/presence/test_drafting.py` (extend — integration seam with a fake loop)

**Interfaces:**
- Produces: `make_draft_fn(loop, conv_store) -> Callable[[str], str]`. Each call creates a fresh `[presence]`-titled session (`conv_store.new_session("aetheria", title="[presence] draft")`), calls `loop.process_message(session_id, prompt)`, returns `resp.content`. If `resp.finish_reason == "tool_round_limit"` or content empty, returns the JSON skip literal `'{"skip":true,"post":"","based_on":""}'` (so an exhausted turn becomes a silent skip, never a broken post).
- Consumes: `AgentLoop` (`soveryn/agents/loop.py:753` `process_message` → `ChatResponse.content`/`.finish_reason`), `ConversationStore.new_session`. **Read these signatures before implementing** to confirm `new_session` params.

- [ ] **Step 1: Write the failing test (fake loop + fake conv_store)**
```python
from soveryn.agents.presence.aetheria_bridge import make_draft_fn

class FakeResp:  # mirrors ChatResponse fields used
    def __init__(self, content, finish="stop"): self.content, self.finish_reason = content, finish
class FakeLoop:
    def __init__(self, resp): self.resp = resp
    def process_message(self, sid, msg): return self.resp
class FakeConv:
    def new_session(self, agent, title=None): return "sess-1"

def test_tool_round_limit_becomes_skip():
    fn = make_draft_fn(FakeLoop(FakeResp("", "tool_round_limit")), FakeConv())
    assert '"skip":true' in fn("prompt")

def test_normal_returns_content():
    fn = make_draft_fn(FakeLoop(FakeResp('{"post":"hi","based_on":"x","skip":false}')), FakeConv())
    assert '"post":"hi"' in fn("prompt")
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Read** `loop.py:753` + `ConversationStore.new_session`, then implement `make_draft_fn`.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): bridge presence drafting to Aetheria's AgentLoop`.

---

### Task 7: Signal message formatting + reply classification

**Files:**
- Create: `soveryn/agents/presence/approval.py`
- Test: `tests/agents/presence/test_approval.py`

**Interfaces:**
- Produces: `format_signal_message(draft: Draft, draft_id: str) -> str` (shows id, kind, the post text, `based_on` — flags "(none stated)" — and, for replies, the tweet url). `classify_reply(text: str) -> Decision` where `Decision` is `("approve", None)`, `("reject", reason)`, or `("edit", new_text)`. Rules (bias to safety): exact-ish `y`/`yes`/`approve`/`post` → approve; `n`/`no`/`reject`/`skip` (optionally `reject: reason`) → reject; **anything else non-empty → edit with that text as the post.**
- Consumes: `Draft` (Task 5).

- [ ] **Step 1: Write the failing test**
```python
from soveryn.agents.presence.approval import format_signal_message, classify_reply
from soveryn.agents.presence.drafting import Draft

D = Draft("1","reply","Grounded > confident.","confab data","1")

def test_message_shows_provenance_and_link():
    m = format_signal_message(D, "d1")
    assert "confab data" in m and "d1" in m and "status/1" in m or "x.com" in m

def test_approve_tokens():
    assert classify_reply("y") == ("approve", None)
    assert classify_reply("approve") == ("approve", None)

def test_reject_with_reason():
    assert classify_reply("reject: off message") == ("reject", "off message")

def test_freeform_is_edit():
    assert classify_reply("Say it softer, lead with the question.") == \
        ("edit", "Say it softer, lead with the question.")
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — normalize/strip; token sets for approve/reject; `reject:` prefix captures reason; everything else is an edit. This is the safety seam — an ambiguous reply must NEVER map to approve.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): Signal message format + safe reply classification`.

---

### Task 8: SignalLog (voice signal)

**Files:**
- Create: `soveryn/agents/presence/signal_log.py`
- Test: `tests/agents/presence/test_signal_log.py`

**Interfaces:**
- Produces: `SignalLog(db_path)` with `record(draft_id, action, original_text, final_text, reason) -> None` and `all() -> list[dict]` (for tests / later DPO export). `action` ∈ `approve|edit|reject`.
- Consumes: nothing (SQLite leaf).

- [ ] **Step 1: Write the failing test**
```python
from soveryn.agents.presence.signal_log import SignalLog

def test_records_edit_signal(tmp_path):
    log = SignalLog(tmp_path/"s.db")
    log.record("d1","edit","orig text","edited text","")
    rows = log.all()
    assert rows[0]["action"]=="edit" and rows[0]["final_text"]=="edited text"
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** — table `signals(id INTEGER PK, draft_id, action, original_text, final_text, reason, created_at)`; `record` inserts; `all` selects as dicts.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): voice-signal log (approve/edit/reject)`.

---

### Task 9: Publisher (publish-on-approval, anti-double-post)

**Files:**
- Create: `soveryn/agents/presence/publisher.py`
- Test: `tests/agents/presence/test_publisher.py`

**Interfaces:**
- Produces: `PublishResult` frozen dataclass `(ok: bool, posted_id: str|None, error: str|None)`. `publish(text: str, draft: Draft, x_client, store: CandidateStore) -> PublishResult`. Routes to `x_client.reply_tweet(text, draft.in_reply_to)` when `in_reply_to` is set, else `x_client.create_tweet(text)`. On success: `store.record_posted_id(posted_id)`, `store.mark(draft.candidate_tweet_id, "posted")`, return ok. On `XClientError`: `store.mark(candidate, "failed")`, return `ok=False` with the error (item stays recoverable; never silently dropped, never posted twice because mark→posted only happens after a returned id).
- Consumes: `Draft` (Task 5), `XClient` (Task 2), `CandidateStore` (Task 4).

- [ ] **Step 1: Write the failing test (fake x_client)**
```python
from soveryn.agents.presence.publisher import publish
from soveryn.agents.presence.drafting import Draft
from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.x_client import XClientError

class FakeX:
    def __init__(self, fail=False): self.fail, self.calls = fail, []
    def create_tweet(self, text): 
        if self.fail: raise XClientError("X API 500: boom")
        self.calls.append(("post", text)); return "posted-1"
    def reply_tweet(self, text, in_reply_to):
        self.calls.append(("reply", text, in_reply_to)); return "posted-2"

def test_reply_routes_and_records(tmp_path):
    store = CandidateStore(tmp_path/"c.db")
    d = Draft("1","reply","hi","x","1")
    r = publish("hi", d, FakeX(), store)
    assert r.ok and r.posted_id=="posted-2" and store.is_seen("posted-2")

def test_failure_marks_failed_no_post(tmp_path):
    store = CandidateStore(tmp_path/"c.db")
    d = Draft("1","topic","hi","x",None)
    r = publish("hi", d, FakeX(fail=True), store)
    assert not r.ok and r.posted_id is None
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** as specified in Interfaces.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): publisher (publish-on-approval, anti-double-post)`.

---

### Task 10: PresenceDaemonSurface — scan_once + resolve_reply + run_forever

**Files:**
- Create: `soveryn/agents/presence/daemon.py`
- Modify: `soveryn/platform/salience/observer.py:19` (add `"[presence]"` to the skip-prefix tuple)
- Test: `tests/agents/presence/test_daemon.py`

**Interfaces:**
- Produces: `PresenceDaemonSurface(*, cfg, x_client, store, draft_fn, send_fn, signal_log, pending: dict|None=None)`. `scan_once() -> int` (returns # drafts sent): search each niche term + own mentions via `x_client`, skip `store.is_seen`, `score_tweet`, `store.upsert` above `cfg.score_threshold`, then for `store.pending_ranked(cfg.max_drafts_per_scan)` call `draft_for_candidate`; on a non-None draft assign a `draft_id`, hold it in `self.pending[draft_id]`, `store.mark(..., "awaiting_approval")`, and `send_fn(format_signal_message(draft, draft_id))`. `resolve_reply(draft_id, reply_text) -> PublishResult|None`: look up pending draft, `classify_reply`, then approve→`publish(draft.text,...)`, edit→`publish(new_text,...)`, reject→`store.mark(...,"rejected")`; log every outcome to `signal_log`; drop from pending. `run_forever(*, interval_seconds, iterations=None, sleep=time.sleep, stop_requested=None, shutdown_poll_granularity_seconds=1.0)` mirrors `AresDaemonSurface.run_forever` exactly (copy `_interruptible_sleep` semantics from `ares/daemon.py:172`).
- Consumes: everything from Tasks 1–9.

- [ ] **Step 1: Write failing tests (all edges faked)**
```python
from soveryn.agents.presence.daemon import PresenceDaemonSurface
from soveryn.agents.presence.config import PresenceConfig
from soveryn.agents.presence.candidate_store import CandidateStore
from soveryn.agents.presence.signal_log import SignalLog
from soveryn.agents.presence.x_client import Tweet

class FakeX:
    def __init__(self, tweets): self.tweets, self.posted = tweets, []
    def search_recent(self, q, since_id=None): return self.tweets
    def create_tweet(self, text): self.posted.append(text); return "p1"
    def reply_tweet(self, text, in_reply_to): self.posted.append(text); return "p2"

def _daemon(tmp_path, tweets, draft_fn, sent):
    cfg = PresenceConfig.default().__class__(**{**PresenceConfig.default().__dict__,
          "db_path": tmp_path/"c.db", "signal_log_path": tmp_path/"s.db"})
    return PresenceDaemonSurface(cfg=cfg, x_client=FakeX(tweets),
        store=CandidateStore(tmp_path/"c.db"), draft_fn=draft_fn,
        send_fn=lambda m: sent.append(m), signal_log=SignalLog(tmp_path/"s.db"))

def test_scan_sends_draft_for_relevant_tweet(tmp_path):
    sent = []
    fn = lambda p: '{"post":"grounded.","based_on":"data","skip":false}'
    d = _daemon(tmp_path, [Tweet("1","a","sovereign AI local LLM","u")], fn, sent)
    assert d.scan_once() == 1 and len(sent) == 1

def test_resolve_approve_publishes(tmp_path):
    sent = []
    fn = lambda p: '{"post":"grounded.","based_on":"data","skip":false}'
    d = _daemon(tmp_path, [Tweet("1","a","sovereign AI local LLM","u")], fn, sent)
    d.scan_once()
    draft_id = next(iter(d.pending))
    r = d.resolve_reply(draft_id, "y")
    assert r.ok and d.x_client.posted == ["grounded."]

def test_resolve_reject_no_publish(tmp_path):
    sent = []
    fn = lambda p: '{"post":"grounded.","based_on":"data","skip":false}'
    d = _daemon(tmp_path, [Tweet("1","a","sovereign AI local LLM","u")], fn, sent)
    d.scan_once()
    assert d.resolve_reply(next(iter(d.pending)), "n") is None
    assert d.x_client.posted == []
```
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** `scan_once`/`resolve_reply`/`run_forever` per Interfaces; draft_id via a counter (deterministic, no wall-clock/random — e.g. `f"{candidate.tweet_id}"`). Then add `"[presence]"` to `observer.py:19` skip prefixes.
- [ ] **Step 4: Run, verify pass** (and run the salience observer tests to confirm the skip-prefix change is green).
- [ ] **Step 5: Commit** — `feat(presence): daemon scan/resolve/run_forever + observer skip [presence]`.

---

### Task 11: Entrypoint + Signal wiring + systemd unit

**Files:**
- Create: `soveryn/agents/presence/__main__.py`
- Read then modify: wire `send_fn`/`resolve_reply` to `soveryn/agents/ares/signal_sender.py` + the Signal bot inbound path
- Create: `~/.config/systemd/user/soveryn-presence.service`
- Test: `tests/agents/presence/test_main.py`

**Interfaces:**
- Produces: `parse_args(argv) -> LauncherArgs` (`--interval-seconds`, `--iterations`, `--dry-run`), `build_daemon(args) -> PresenceDaemonSurface` (assembles config, `XClient.from_env()`, stores, `make_draft_fn` over the wired Aetheria loop, `signal_sender` send_fn), `run(args, ...)`/`main(argv=None)` mirroring `ares/__main__.py` (SIGTERM/SIGINT via `_ShutdownRequest`, `run_forever(stop_requested=...)`). In `--dry-run`, `send_fn` prints instead of sending to Signal and publisher is not reachable (no approvals arrive), so a dry run only exercises ingest→score→draft.
- Consumes: Task 10 daemon; `ares/__main__.py` as the structural template; `ares/signal_sender.py` for the real Signal send.

- [ ] **Step 1: Write the failing test** — `parse_args([])` returns defaults; `parse_args(["--iterations","1","--dry-run"])` sets them; `build_daemon` with monkeypatched env + faked `XClient.from_env` returns a `PresenceDaemonSurface`.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Read** `ares/__main__.py` + `ares/signal_sender.py` + the Signal bot inbound handler; implement `__main__.py`; wire `send_fn` to `signal_sender` and register `resolve_reply` as the handler for inbound Signal replies that match a pending `draft_id` (correlation via the id printed in `format_signal_message`). Write the systemd unit:
```ini
[Unit]
Description=SOVERYN Presence Agent (@Soveryn_AI drafts, human-approved via Signal)
PartOf=soveryn.target
After=soveryn-vnext.service network-online.target
Wants=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/home/jon-deoliveira/soveryn_vnext
Environment=PATH=/home/jon-deoliveira/miniconda3/envs/soveryn/bin:/usr/bin
# X_* creds injected here (EnvironmentFile=) — never committed
ExecStartPre=/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.platform.supervisor.readiness http://127.0.0.1:5001/health --name vnext --max-wait 60
ExecStart=/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m soveryn.agents.presence --interval-seconds 300
Restart=on-failure
RestartSec=20
StandardOutput=append:/tmp/soveryn-presence.log
StandardError=append:/tmp/soveryn-presence.log

[Install]
WantedBy=soveryn.target
```
- [ ] **Step 4: Run tests, verify pass.** Do NOT enable the unit yet — enabling/`--no-dry-run` waits on Jon's creds + a `@pytest.mark.rig` live check.
- [ ] **Step 5: Commit** — `feat(presence): entrypoint, Signal wiring, systemd unit (disabled pending creds)`.

---

### Task 12: Register `read_presence_candidates` tool for Aetheria (optional pull path)

**Files:**
- Create: `soveryn/agents/presence/tools.py`
- Test: `tests/agents/presence/test_tools.py`

**Interfaces:**
- Produces: `build_read_presence_candidates_tool(*, store: CandidateStore) -> ToolSpec` (name `read_presence_candidates`, `owner="aetheria"`, schema `{limit?}`, handler returns pending ranked candidates). Lets Aetheria *look at* what's queued on her own initiative (heartbeat), separate from the daemon's push-draft path. Register via `registry.register(spec)`.
- Consumes: `ToolSpec`/`ToolRegistry` (`soveryn/platform/tools/registry.py:31/71`), `CandidateStore` (Task 4).

- [ ] **Step 1: Write the failing test** — build the tool over a store with 2 pending candidates; `spec.owner=="aetheria"`; invoking the handler returns them ranked.
- [ ] **Step 2: Run, verify fail.**
- [ ] **Step 3: Implement** the ToolSpec + handler.
- [ ] **Step 4: Run, verify pass.**
- [ ] **Step 5: Commit** — `feat(presence): read_presence_candidates tool for Aetheria`.

---

## Self-Review

- **Spec coverage:** daemon+ingest (T10), dedup (T4), salience→presence scorer (T3, refinement noted), candidate store not CoordBoard (T4, refinement noted), drafting+provenance (T5/T6), Signal approval (T7, replaces messenger), publisher (T9), voice-signal log (T8), systemd+start-limit (T11), observer skip (T10), Aetheria pull tool (T12). All v1-IN scope items map to a task.
- **Placeholder scan:** two intentional deferred *reads* (T6 loop signature, T8/T11 Signal bot API) are flagged as explicit steps inside their tasks, with a faked seam so the surrounding code is testable without them — not placeholders.
- **Type consistency:** `Tweet` (T2) → `score_tweet` (T3) → `Candidate` (T4) → `Draft` (T5) → `publish`/`resolve_reply` (T9/T10) thread consistently; `draft_fn: Callable[[str],str]` is the single seam between T5 and the real loop (T6).

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-09-soveryn-ai-presence-agent-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration. Tasks 1–4, 8, 9 are mechanical (cheap model); 5, 10, 11 need judgment (standard); the Signal wiring in 11 is the only integration-heavy one.

**2. Inline Execution** — execute in this session with checkpoints.

**Which approach?**
