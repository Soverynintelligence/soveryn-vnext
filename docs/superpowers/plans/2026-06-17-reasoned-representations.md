# Reasoned Representations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A background daemon that reasons over recent conversation to maintain evolving, premise-cited conclusions about Jon (and later agents) in the lattice — systematizing what the hand-curated identity spine does.

**Architecture:** New `soveryn/agents/representation/` package, a sibling of `agents/dream/` with the same skeleton (config → trigger → briefing → cognition → parse → writeback → daemon). Reasoning runs on the existing cognition surface (:8089). Conclusions are `nodes` rows (`type='conclusion'`, structure in `provenance` JSON) linked to premises by `edges` (`relationship='concluded_from'`). No schema migration, no new GPU slot, no external dependency.

**Tech stack:** Python 3.11 (env `soveryn`), stdlib + existing `LatticeStore` / `ConversationStore`. Tests: pytest. Run all tests with `/home/jon-deoliveira/miniconda3/envs/soveryn/bin/python -m pytest`.

**Spec:** `docs/superpowers/specs/2026-06-17-reasoned-representations-design.md`. Guardrails are load-bearing: conclusions MUST cite premises (Measurement≠Interpretation), dry-run before live writes (confabulation risk), injected conclusions are bare data not instruction.

**Reference patterns (read before starting):** `soveryn/agents/dream/{trigger,cognition,prompt,writeback,daemon,config}.py` — mirror their structure. `LatticeStore.write_node` (legacy.py:442) for the write signature.

## Review amendments (Vett + Aetheria, 2026-06-17)
Both agents reviewed the spec. Folded-in changes (apply in the noted tasks):
- **Briefing cap (Vett — E4B 16K budget):** run with ~**8** turns/briefing, not 20. Set `SOVERYN_REPR_TURNS=8` in the T9 systemd unit; recommend lowering `DEFAULT_TURNS_PER_BRIEFING` likewise. A bloated briefing degrades the E4B silently.
- **NL→ordinal confidence (Vett — real gap):** the spec said "rank by confidence×salience" but confidence is a natural-language phrase. Add `confidence_rank(phrase)->int` (in `parse.py`): {"confident":3, "fairly confident":2, "tentative":1, "low confidence":1}, default 1. **T6** stores `provenance.confidence_rank`; **T8** ranks injection by `confidence_rank × salience` (no NL re-parsing at query time).
- **Min-turn threshold (Vett + Aetheria — noise gate):** **T7** trigger is eligible iff `new_turn_count >= config.min_turns` (default ~4), NOT `> 0`. Avoids noise conclusions from trivial exchanges. (Fast-follow: event-driven trigger.)
- **Dry-run protocol (Vett):** the **T7** gate is a **48-hour dry run**, then inspect conclusions by eye with Jon+Vett+Aetheria for: (a) premise quality, (b) contradiction-detection accuracy, (c) confidence calibration. Don't flip live until these pass.
- **Note (premise ids):** briefing turn-premises are synthetic ids (`turn:<session>:<idx>`, T4), not lattice node ids. T6 writeback: create `concluded_from` edges only for premises that resolve to real nodes (conclusion-node premises); record turn-premises as text in provenance (no edge). Handle both gracefully.

---

## Task 1: Package + config

**Files:**
- Create: `soveryn/agents/representation/__init__.py` (empty)
- Create: `soveryn/agents/representation/config.py`
- Test: `tests/test_representation_config.py`

- [ ] **Step 1: Failing test**
```python
# tests/test_representation_config.py
from soveryn.agents.representation.config import RepresentationConfig

def test_defaults_and_env_override(monkeypatch):
    cfg = RepresentationConfig.from_env({})
    assert cfg.enabled is True
    assert cfg.tick_interval_seconds == 900
    assert cfg.turns_per_briefing == 20
    assert cfg.dry_run is True              # SAFE default — must opt into live writes
    assert cfg.subject == "jon"
    cfg2 = RepresentationConfig.from_env({
        "SOVERYN_REPR_DRY_RUN": "false",
        "SOVERYN_REPR_TICK_SECONDS": "300",
    })
    assert cfg2.dry_run is False
    assert cfg2.tick_interval_seconds == 300
```

- [ ] **Step 2: Run, expect ImportError/fail**
Run: `…/python -m pytest tests/test_representation_config.py -q`  → FAIL (no module)

- [ ] **Step 3: Implement** (mirror `dream/config.py` parse helpers)
```python
# soveryn/agents/representation/config.py
from __future__ import annotations
from dataclasses import dataclass

DEFAULT_TICK_SECONDS = 900
DEFAULT_TURNS_PER_BRIEFING = 20

def _b(raw, default=True):
    if raw is None or raw == "": return default
    return raw.strip().lower() in {"true","1","yes","on"}
def _i(raw, default):
    return int(raw) if raw not in (None, "") else default

@dataclass(frozen=True)
class RepresentationConfig:
    enabled: bool = True
    tick_interval_seconds: int = DEFAULT_TICK_SECONDS
    turns_per_briefing: int = DEFAULT_TURNS_PER_BRIEFING
    dry_run: bool = True
    subject: str = "jon"
    cognition_url: str = "http://127.0.0.1:8089"
    owner_agent: str = "aetheria"

    @classmethod
    def from_env(cls, env: dict) -> "RepresentationConfig":
        return cls(
            enabled=_b(env.get("SOVERYN_REPR_ENABLED"), True),
            tick_interval_seconds=_i(env.get("SOVERYN_REPR_TICK_SECONDS"), DEFAULT_TICK_SECONDS),
            turns_per_briefing=_i(env.get("SOVERYN_REPR_TURNS"), DEFAULT_TURNS_PER_BRIEFING),
            dry_run=_b(env.get("SOVERYN_REPR_DRY_RUN"), True),
            subject=env.get("SOVERYN_REPR_SUBJECT", "jon"),
            cognition_url=env.get("SOVERYN_REPR_COGNITION_URL", "http://127.0.0.1:8089"),
            owner_agent=env.get("SOVERYN_REPR_OWNER", "aetheria"),
        )
```

- [ ] **Step 4: Run, expect PASS**
- [ ] **Step 5: Commit** — `feat(repr): config for representation daemon`

---

## Task 2: Conclusion parser (the load-bearing novel piece)

The cognition model returns one conclusion per line in a strict format the prompt enforces:
`MODE | CONFIDENCE | CONTENT | [node:ID],[node:ID]`
A line with no premises is INVALID and dropped (Measurement≠Interpretation: no premise → no conclusion).

**Files:**
- Create: `soveryn/agents/representation/parse.py`
- Test: `tests/test_representation_parse.py`

- [ ] **Step 1: Failing test**
```python
# tests/test_representation_parse.py
from soveryn.agents.representation.parse import parse_conclusions, Conclusion

def test_parses_valid_lines_and_drops_premiseless():
    raw = (
        "abductive | fairly confident | Jon prefers the sharp honest read | [node:a1],[node:b2]\n"
        "inductive | tentative | Jon works in long focused sessions | [node:c3]\n"
        "deductive | confident | This line has no premises so must be dropped | \n"
        "garbage line with no pipes\n"
    )
    out = parse_conclusions(raw)
    assert len(out) == 2
    assert out[0] == Conclusion(mode="abductive", confidence="fairly confident",
                                content="Jon prefers the sharp honest read",
                                premises=("a1", "b2"))
    assert out[1].premises == ("c3",)

def test_invalid_mode_dropped():
    assert parse_conclusions("vibes | sure | x | [node:a]") == []
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement**
```python
# soveryn/agents/representation/parse.py
from __future__ import annotations
import re
from dataclasses import dataclass

_VALID_MODES = {"deductive", "inductive", "abductive"}
_NODE_RE = re.compile(r"\[node:([^\]]+)\]")

@dataclass(frozen=True)
class Conclusion:
    mode: str
    confidence: str
    content: str
    premises: tuple[str, ...]

def parse_conclusions(raw: str) -> list[Conclusion]:
    out: list[Conclusion] = []
    for line in (raw or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 4:
            continue
        mode, confidence, content, prem_field = parts
        mode = mode.lower()
        premises = tuple(_NODE_RE.findall(prem_field))
        if mode not in _VALID_MODES or not content or not premises:
            continue  # premise-less or malformed → dropped
        out.append(Conclusion(mode=mode, confidence=confidence,
                              content=content, premises=premises))
    return out
```

- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `feat(repr): conclusion parser (drops premise-less lines)`

---

## Task 3: Prompt

**Files:** Create `soveryn/agents/representation/prompt.py`; Test `tests/test_representation_prompt.py`

- [ ] **Step 1: Failing test** — assert the rendered prompt contains the strict output format, the three modes, the subject, the briefing turns, and prior conclusions; and instructs premise citation by `[node:ID]`.
```python
from soveryn.agents.representation.prompt import render_representation_prompt
def test_prompt_contains_contract():
    p = render_representation_prompt(subject="jon",
        briefing="[node:t1] jon: I want the honest read",
        prior_conclusions="[node:p1] Jon values directness")
    for s in ("jon", "deductive", "inductive", "abductive",
              "MODE | CONFIDENCE | CONTENT | [node:ID]", "[node:t1]", "[node:p1]"):
        assert s in p
```

- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — a function returning a prompt that: states the subject; supplies the briefing + prior conclusions (each line prefixed `[node:ID]`); asks for new/updated conclusions; enforces `MODE | CONFIDENCE | CONTENT | [node:ID],[node:ID]` one per line; says confidence is plain words; says cite at least one premise; says flag a contradiction of a prior conclusion by restating it with the corrected content (writeback handles supersede). Keep it bare-data/no-persona.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `feat(repr): reasoning prompt`

---

## Task 4: Briefing assembly

Gather the last N user/assistant turns for the owner agent since the last run + the subject's existing conclusions, each rendered with a `[node:ID]` prefix so the model can cite them.

**Files:** Create `soveryn/agents/representation/briefing.py`; Test `tests/test_representation_briefing.py`

- [ ] **Step 1: Failing test** — init `LatticeStore(db)` + `ConversationStore(db2)`; insert a couple turns + an existing `type='conclusion'` node; assert `build_briefing(...)` returns (briefing_text, prior_text, source_node_ids) where turns and the prior conclusion appear with `[node:...]` prefixes. (Mirror `tests/test_lattice_embed_on_write.py` for store setup.)
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** `build_briefing(conv_store, lattice_store, *, owner_agent, subject, turns_per_briefing) -> tuple[str,str,list[str]]`:
  - recent turns via `conv_store.list_sessions_with_recent_activity` + `load_history` (cap to turns_per_briefing, non-autonomous sessions);
  - prior conclusions via `lattice_store.iter_nodes(agent=owner_agent)` filtered `type=='conclusion'` and `provenance.subject==subject`;
  - render each as `[node:<id>] <content>`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `feat(repr): briefing assembly`

---

## Task 5: Cognition call

**Files:** Create `soveryn/agents/representation/cognition.py`; Test `tests/test_representation_cognition.py`

- [ ] **Step 1: Failing test** — inject a fake `chat_completion` (no HTTP); assert `run_representation_pass(briefing, prior, subject, cognition_url, chat_fn=fake)` returns the parsed `list[Conclusion]`.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — mirror `dream/cognition.py chat_completion` (POST `/v1/chat/completions`, model `"dream"` alias on :8089, return content). `run_representation_pass` renders the prompt, calls `chat_fn`, returns `parse_conclusions(content)`. Best-effort: on HTTP error return `[]` and log.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `feat(repr): cognition pass`

---

## Task 6: Writeback + supersede (live writes; default OFF)

**Files:** Create `soveryn/agents/representation/writeback.py`; Test `tests/test_representation_writeback.py`

- [ ] **Step 1: Failing tests**
  - `write_conclusions` with `embed_fn=lambda t:(0.1,0.2,0.3)` writes one `type='conclusion'` node per Conclusion: `layer='private'`, embedding set, provenance `{kind:'conclusion',subject,premises,confidence,mode,run_id}`; and one `concluded_from` edge per premise (skip premise ids that don't exist).
  - supersede is a LOUD, traceable event (per Aetheria's review — "evolving a personality, not updating a variable"). When a new conclusion supersedes an old one:
    - old node tagged `historical_snapshot` (preserved, not deleted);
    - new node `provenance.supersedes` = old id;
    - an explicit `edges` row `relationship='supersedes'` (new → old) so the belief-evolution chain is graph-traversable;
    - a row in a new `representation_log` audit table capturing the WHY: `{old_id, new_id, old_content_head, new_content_head, driving_premises:[node:ID], confidence_from, confidence_to, run_id, created_at}`. The driving_premises ARE the answer to "why did I change my mind" — they point at the turns/data that forced the revision.
    - Test: superseding writes the edge AND a `representation_log` row whose `driving_premises` == the new conclusion's premises.
  - `dry_run=True` path writes nothing (no node, no edge, no log row).
  (Setup: `LatticeStore(db)` then assert via sqlite, like `tests/test_lattice_embed_on_write.py`.)
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** using `lattice_store.write_node(agent=owner, content=c.content, node_type="conclusion", layer="private", embedding=embed_fn(c.content), provenance={...})`; `concluded_from` edges via the same INSERT pattern as `dream/writeback._write_edges_from_synthesis`. Add `CREATE TABLE IF NOT EXISTS representation_log (...)` to the lattice schema in `legacy.py` (alongside the existing `dream_log`/`heartbeat_log`/`signal_log` audit tables) + an `idx_representation_log_created`. Supersede path: tag old (`UPDATE nodes SET tags` += `historical_snapshot`), write `supersedes` edge (new→old), insert the `representation_log` row. Guard ALL writes (node, edges, log) behind `if not dry_run`.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `feat(repr): writeback + supersede (dry-run default)`

---

## Task 7: Trigger + daemon (dry-run skeleton end-to-end)

**Files:** Create `trigger.py`, `daemon.py`, `__main__.py`; Test `tests/test_representation_trigger.py`, `tests/test_representation_daemon_tick.py`

- [ ] **Step 1: Failing tests**
  - `trigger.evaluate(new_turn_count, config)` → eligible iff `enabled and new_turn_count > 0`; returns skip_reason otherwise. (Mirror `dream/trigger.py`.)
  - DESIGN NOTE (Aetheria's review): v1 uses a tick + activity-gate (above) for simplicity. The better end-state is **event-driven** — reason when a *meaningful* thing happens (an `intent_mark` is recorded, a `friction` coord node resolves) rather than on a clock, so the triggering event becomes a natural premise of the conclusion. Infra exists (coord event bus + intent ledger). Fast-follow after v1 validates; keep `evaluate()` pure so the trigger source can swap without touching the reasoning.
  - daemon `_do_tick` (dry-run, fakes for conv/lattice/chat) calls briefing→cognition→writeback and writes NOTHING in dry-run; returns a summary with the parsed conclusion count.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — `daemon.py` mirrors `dream/daemon.py` spin-resistant tick loop; `_do_tick` wires Tasks 4–6; `__main__.py` builds config from env + `LatticeStore`/`ConversationStore` and runs. Wire `embed_fn=_default_embed` (from app startup helper) for live; `None` in dry-run.
- [ ] **Step 4: Run → PASS**
- [ ] **Step 5: Commit** — `feat(repr): trigger + daemon (dry-run end-to-end)`

- [ ] **Step 6: MANUAL dry-run gate (no code).** Run `__main__` once against the live DBs with `SOVERYN_REPR_DRY_RUN=true`, capture the conclusions it WOULD write, and eyeball them with Jon for confabulation/quality BEFORE enabling live writes. This is the confabulation guardrail — do not skip.

---

## Task 8: Injection into prelude (P4)

**Files:** Modify `soveryn/agents/loop.py` (`_identity_spine_nodes`); Test `tests/test_loop_conclusion_injection.py`

- [ ] **Step 1: Failing test** — with a lattice containing `type='identity'` spine nodes AND `type='conclusion'` nodes for the agent, `_identity_spine_nodes(store, agent=...)` includes the conclusions (capped top-K by salience), and excludes `historical_snapshot`-tagged (superseded) ones.
- [ ] **Step 2: Run → FAIL**
- [ ] **Step 3: Implement** — extend `_identity_spine_nodes` to also collect `node.type == 'conclusion'` for the agent (skip `historical_snapshot` tagged), capped. Injected as bare data via the existing identity-context path (no new instruction text).
- [ ] **Step 4: Run → PASS + full suite** `…/python -m pytest tests/ -q`
- [ ] **Step 5: Commit** — `feat(repr): inject conclusions into identity prelude`

---

## Task 9: systemd unit + docs

**Files:** Create `~/.config/systemd/user/soveryn-representation.service` (mirror `soveryn-dream.service`); update `tests/test_systemd_units_shape.py` if it enumerates units.

- [ ] Mirror the dream unit; `ExecStart=…/python -m soveryn.agents.representation`; default env `SOVERYN_REPR_DRY_RUN=true`. Do NOT enable live until the Task 7 dry-run gate passes with Jon.
- [ ] Commit — `feat(repr): systemd unit (dry-run default)`

---

## Deferred (not in this plan)
- **P5 peer representations** (subject = agent name; each agent models the others).
- Graduating select conclusions from `private` → shared (`library`/`global`) model of Jon.
- Feeding conclusions into the parked **self-model aggregation** engine (keep distinct: this REASONS, self-model MEASURES).

## Self-review checks done
- Spec coverage: P1 (T1–7) / P2 (T6) / P3 (T6 supersede) / P4 (T8) all have tasks; P5 explicitly deferred.
- Types consistent: `Conclusion` (parse.py) used by cognition + writeback; provenance keys match the spec.
- No placeholders: parser/config/prompt-contract are concrete; daemon/briefing reference exact existing patterns to mirror.
- Guardrails as tasks: premise-less drop (T2), dry-run default + manual gate (T1/T6/T7), bare-data injection (T8).
