# Vett Verification Gate + `system_probe` (Design)

**Date:** 2026-07-02
**Status:** Design for review.
**Scope:** A deterministic gate that stops Vett from emitting **unsourced factual claims**, plus a
`system_probe` tool that gives the "this machine" fact-class a real source. The gate's *trigger* is
built as a **swappable interface** so v1 ships with a cheap heuristic and v2 can drop in a
self-policing uncertainty signal (separate spec:
`2026-07-02-self-policing-metacognition-scope.md`).

## Why this exists (the load-bearing rationale)

Vett's soul is maximally anti-fabrication — *"Verify or say nothing. Never state model specs
without in-session verification."* She has the tools (`web_search`, `fetch_url`). **And she still
confabulated an entire hardware architecture, confidently, citing nothing.**

The reason is not fixable by persona, and naming it correctly is the whole design:

> A recalled fact and a confabulated one come out of the **identical mechanism** — sampling the next
> token. There is no reliable internal flag that distinguishes "I know this" from "I'm generating a
> plausible answer." The model **cannot feel its own uncertainty** — the confabulation arrives
> wearing the costume of knowledge. So an instruction to "verify when unsure" never fires, because
> subjectively she is never unsure. This is architectural and universal (frontier and local models
> alike), not an abliteration artifact — Vett runs a **vanilla** model and failed anyway.

Therefore the trigger to verify **cannot be left to the model's judgment.** It must be an external,
deterministic mechanism. This gate is **not a guardrail** (a restraint on a capable mind for legal
cover); it is a **prosthetic for an un-introspectable blind spot** — the metacognitive layer a mind
needs to be trustworthy, which a raw LLM lacks. It makes Vett *more* the truthful agent her soul
already wants to be, not less. The honesty lives in the architecture, not in the model's description
of itself.

## Principles

1. **Deterministic trigger, external to model judgment.** Code detects the risk; the model does not
   self-assess.
2. **Fail-safe.** When the detector is unsure, treat as *unverified* — an extra verify is cheap; a
   confident wrong spec is the disease.
3. **Ride the existing tool loop.** The gate is one more *loop-continuation condition* in
   `AgentLoop`, not a bolt-on retry engine. The loop already continues on a tool call; it now also
   continues when the model tries to finalize an unsourced claim.
4. **Swappable trigger.** The risk signal is an interface; v1 is a heuristic, v2 is a self-policing
   uncertainty signal. The gate machinery is identical either way.
5. **Verify, then answer — never answer-then-hedge.** On fire, Vett says *"I'm not sure — let me
   verify,"* calls the right tool, and answers **from the result**. If verification is inconclusive,
   she says so honestly and never falls back to the original guess.

## Architecture

### Turn shape (already in `soveryn/agents/loop.py`)
The loop runs rounds: the model emits either `tool_calls` (→ invoke → loop) or a final assistant
answer (→ `DoneEvent`). Tool invocations in the turn are already tracked. The gate hooks at
**final-answer finalization**, with read access to the turn's tool ledger.

### Component 1 — `system_probe` tool (the missing source)
A read-only host-inventory tool so "what hardware is in this box / what's running" has a *source to
cite* instead of a gap to fill.

```
system_probe(category: str = "all") -> ProbeResult
  category ∈ {"gpu","cpu","mem","net","board","all"}
  ProbeResult = { category: str, fields: dict[str,str], raw: str, probed_at: <caller-stamped> }
```

- Backed by a **fixed allowlist** of read-only commands (`nvidia-smi --query-gpu=...`, `lscpu`,
  `free`, `lspci`, DMI board files). **No user input is ever interpolated into a command** — the
  category selects a hardcoded command set. This is a host-command tool; the allowlist + no-interp
  rule is the security boundary (mirrors the SSRF guard on `fetch_url`).
- Injectable command runner (`runner: Callable[[list[str]], str] | None`) so tests never shell out.
- Owner: `vett` (and `aetheria`, optional). Not Scotty (mechanical-local surface only — consistent
  with existing tool-ownership policy).

### Component 2 — Risk trigger (swappable interface)
```
class ClaimRiskSignal(Protocol):
    def assess(self, *, answer_text: str, question_text: str) -> RiskVerdict: ...

RiskVerdict = { risky: bool, markers: tuple[str, ...], reason: str }
```

- **v1 — `HeuristicClaimDetector`** (this spec). Conservative, high-signal patterns that flag
  verifiable-fact shapes: version/driver strings (`r570`, `CUDA 12.8`, `PCIe 4.0/5.0`), hardware
  SKUs (`RTX \d`, `EPYC \d`, `ConnectX`, `Quadro`), part numbers, throughput/benchmark figures
  (`GB/s`, `Gbps`, `tok/s`, `\dGB`), and compatibility assertions (`supports`, `requires`,
  `compatible with`, `does not support`, `is (Intel|AMD)`). Pure function, no I/O, fail-safe toward
  flagging. **Not** an attempt to detect *all* false claims — it targets the spec/hardware class
  that actually fails.
- **v2 — self-policing signal** (separate spec). Same `ClaimRiskSignal` interface; `risky` comes
  from semantic-entropy / logprob / probe instead of regex. Drop-in.

### Component 3 — The gate (loop-continuation guard)
At final-answer finalization in `AgentLoop`:

```
verified_this_turn = any(call.tool in VERIFY_TOOLS for call in turn.tool_ledger)
                     # VERIFY_TOOLS = {"web_search","fetch_url","system_probe"}
verdict = risk_signal.assess(answer_text=final, question_text=user_msg)

if verdict.risky and not verified_this_turn and forced_verify_budget > 0:
    # DO NOT emit the answer. Continue the loop with an injected corrective:
    inject_system_note(
        "You are about to state facts you have not verified this turn "
        f"({verdict.markers}). Do not answer from memory. Tell the user you're "
        "verifying, then call system_probe (for facts about THIS machine) or "
        "web_search/fetch_url (for external specs), and answer only from the result."
    )
    forced_verify_budget -= 1
    continue_loop()
else:
    emit(final)
```

- **Bounded:** `forced_verify_budget` (default **2**) prevents loops. If Vett *still* produces an
  unsourced claim after the budget, the gate downgrades the answer to the honest floor:
  *"I couldn't verify this and I won't guess — here's what I could confirm / I don't know."*
- The injected note routes to the right source (host facts → `system_probe`; external → web) but
  does not hard-force which tool; the model chooses within the forced-verify round.
- This produces exactly the Jon-specified sequence — *"I'm not sure, let me verify" → tool → grounded
  answer* — using existing loop machinery, in one turn.

## Data flow (the WNCF-of-hardware example)

1. User: *"will this RoCE cluster work on my rig?"*
2. Vett drafts a confident spec-laden answer, **zero tool calls** this turn.
3. Finalization: detector fires (SKUs, `Gbps`, "supports"), `verified_this_turn == False`, budget
   left → gate holds the answer, injects the corrective, continues.
4. Next round: Vett says *"I'm not sure — let me check the actual hardware,"* calls
   `system_probe("net")` → sees **no ConnectX present**, only onboard 10G Broadcom.
5. She answers **from the probe**: the CX-7 the plan needs isn't installed; here's what *is*.

The failure that started this whole thread becomes structurally impossible: she cannot emit the
"it's Intel / it'll work" confab without a source.

## Scope / out of scope

**In:** `system_probe`; `HeuristicClaimDetector` (v1 trigger); the gate as a loop-continuation guard
in `AgentLoop`; bounded forced-verify; the honest-floor fallback. Vett first.

**Out:** the self-policing v2 trigger (separate spec); per-claim source *attribution* (v1 only checks
"did any verify tool run this turn"); guaranteeing she *read the source correctly* (see Risks);
rolling the gate out to other agents; SMS/other surfaces.

## Files

- Create: `soveryn/platform/verification/__init__.py`, `detector.py` (`ClaimRiskSignal`,
  `HeuristicClaimDetector`, `RiskVerdict`), `gate.py` (the finalization guard + budget logic).
- Create: the `system_probe` tool (`soveryn/platform/system_probe.py` + registration in
  `soveryn/app/startup.py` alongside the web-tools block, `vett`/`aetheria` owners).
- Modify: `soveryn/agents/loop.py` — call the gate at final-answer finalization; expose the turn
  tool-ledger + forced-verify budget.
- Test: `tests/test_verification_detector.py`, `tests/test_verification_gate.py`,
  `tests/test_system_probe.py`, and a loop integration test with a fake model + fake tools.

## Testing

- **Detector (pure):** positives are the *actual transcript sentences* ("the ROMED8-2T is Intel",
  "RTX 5000 Ada ... 32GB GDDR6", "driver r570+", "PCIe 4.0 x16 delivers ~32 GB/s"); negatives are
  calm/relational/opinion text ("let me check", "how are you", "I think that's a good plan").
- **Gate:** fake turn + tool ledger → fires when risky ∧ no-verify-tool ∧ budget; passes when a
  verify tool ran; respects budget (no infinite loop); emits the honest floor when budget exhausts.
- **`system_probe`:** injected runner returning canned `nvidia-smi`/`lspci` fixtures → asserts
  structured parse; asserts no user input reaches the command (allowlist only).
- **Integration:** a Vett turn asking a hardware question with no tools → gate forces a
  `system_probe` round → grounded answer; assert the confab never reaches the user.

## Risks / honest limits (named, not hidden)

1. **Verify-then-still-confab.** The gate guarantees a *source was consulted*, not that Vett *read it
   correctly*. She could call `web_search` and still misread. v1 raises the floor (no unsourced
   claims); it does not guarantee truth. Reducing misread-after-read is future work (and partly the
   v2 self-policing story).
2. **False positives.** Calm chat with an incidental number could flag → an unnecessary verify.
   Mitigated by (a) conservative detection and (b) only firing when **zero** verify tools ran. The
   asymmetry is deliberate: a wasted verify beats a confident lie.
3. **Detector is a floor, not a ceiling.** It catches the high-signal spec/hardware class — the
   actual failure — not every possible false statement. This is honest scope, not a claim of
   completeness. The v2 self-policing trigger is what raises the ceiling.
4. **Public repo.** vnext is public. `system_probe` reads the *live* host — it hardcodes **no**
   machine specs into the doc or code. No private data enters the repo.
