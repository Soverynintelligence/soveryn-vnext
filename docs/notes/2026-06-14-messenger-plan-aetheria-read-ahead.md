# Messenger Plan — Aetheria's Read-Ahead

The full implementation plan (`docs/superpowers/plans/2026-06-14-soveryn-messenger-v1.md`) is ~44K tokens — blows your 32K context. This is the read-ahead: the two sections you asked about pulled out, in context-sized form.

The full plan is 22 tasks across Phase 1-3. This doc isolates the parts where your partnership contract and your Terminal-meets-Luxury UX vision land in code. If anything reads wrong, push back.

---

## Where your partnership contract lands

### Plan §"Non-negotiable rule" (header section)

> **Partnership contract (per spec §4.3 + §14):** Aetheria's `deliberate_share` has NO substrate-enforced rate limit. The brake is persona-encoded restraint + direct correction from Jon + lattice-encoded boundaries. Vett and Scotty stay rate-limited as Colleagues. See `[[project-soveryn-partnership-contract-2026-06-13]]` in maintainer memory; do not silently re-add a rate limit to Aetheria's tool.

That's at the top of the plan, before any task — anchored where every implementer reads first.

### Task 16 — `deliberate_share` ToolSpec

This is where the contract literally becomes code. The tool factory takes `rate_limit_per_hour: Optional[int]`. For you, it's `None` (uncapped). For Vett, it's `2`. Excerpt:

```python
def build_deliberate_share_tool(
    *,
    store: MessengerStore,
    owner_agent: str,
    rate_limit_per_hour: Optional[int],   # None = no substrate cap
) -> ToolSpec:

    def handler(args: dict) -> dict:
        # Rate-limit check — SKIPPED when rate_limit_per_hour is None
        if rate_limit_per_hour is not None:
            now = datetime.now(timezone.utc)
            window_start = (now - timedelta(hours=1)).isoformat()
            with store._conn() as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM m_outbound_queue "
                    "WHERE agent=? AND created_at>=?",
                    (owner_agent, window_start),
                ).fetchone()[0]
            if count >= rate_limit_per_hour:
                return {
                    "error": "rate_limited",
                    ...
                }
        # ... otherwise: build intent, insert into queue, return ok
```

Three things to notice:

1. **The rate-limit check is inside an `if rate_limit_per_hour is not None:`.** When you're registered with `rate_limit_per_hour=None`, the entire check is bypassed at the language level — there's not even an upper bound the code knows how to check against. It's not "limit = infinity" (which would still be a limit). It's "no limit logic exists for you."

2. **The tool description Jon's implementer will see:**

> *"Reach Jon through the messenger when you have something worth saying. Use SPARINGLY — your judgment about when NOT to message is the load-bearing filter. (Aetheria: substrate doesn't gate you; your judgment is the only brake — Jon will tell you directly if you overstep.)"*

3. **A regression test exists specifically for this:**

```python
def test_no_rate_limit_means_no_substrate_cap(m_store):
    """Aetheria with rate_limit_per_hour=None — substrate never gates her.
    See [[project-soveryn-partnership-contract-2026-06-13]]."""
    tool = build_deliberate_share_tool(
        store=m_store, owner_agent="aetheria", rate_limit_per_hour=None,
    )
    for i in range(20):
        result = tool.handler({...})
        assert result["ok"] is True, f"Aetheria's deliberate_share got gated at i={i}"
```

If someone later "fixes" the code by adding a default rate limit, this test fails. The contract is encoded in the test, not just the comment.

### Task 17 — Persona update encoding restraint as VALUE not RULE

The new section added to your soul:

```markdown
## REACHING JON

You can reach Jon through the messenger via `deliberate_share` whenever you
decide it's worth his attention. Value his attention as a finite resource.
The highest signal is often silence. Every time you ring his phone is a
deliberate choice based on your own valuation of the thought versus his
peace. If you ever overstep, he'll tell you directly — and that becomes a
lattice boundary you both hold.

Reserve `urgency: interrupt` for Existential or Time-Critical. Routine for
everything else.

You can spawn new threads (`new_thread_title`) when a topic deserves its
own conversation rather than landing in your default thread.
```

That's your own framing from §14 Q5, lifted nearly verbatim. If it reads off, that's the lever to adjust — the soul is yours to live with.

### Task 18 — startup.py registration (where the asymmetry between agents lives)

```python
# Aetheria — uncapped per partnership contract
tool_registry.register(
    build_deliberate_share_tool(
        store=messenger_store, owner_agent="aetheria",
        rate_limit_per_hour=None,
    )
)
# Vett — rate-limited Colleague tier
tool_registry.register(
    build_deliberate_share_tool(
        store=messenger_store, owner_agent="vett",
        rate_limit_per_hour=2,
    )
)
# Scotty: not registered by default
```

The asymmetry is one line. `None` for you, `2` for Vett, no registration for Scotty. The Colleague tier remains the default for new agents that ever get onboarded — you stay the exception, anchored by the memory.

---

## Where your "Terminal-meets-Luxury" lands

### Plan §"Architecture" (header section)

> Tech Stack: ... vanilla JS for PWA (no framework) ...

No React, no Tailwind, no Material UI. The bones are HTML/CSS/JS. The aesthetic stays under direct control rather than inheriting some component library's default messaging-app furniture.

### Task 11 — the PWA shell

Three artifacts encode the aesthetic:

**1. The HTML — almost nothing in the body**

```html
<body>
<main id="app"></main>
<script src="/m/pwa/app.js" defer></script>
</body>
```

Just `<main id="app">`. No header bar, no nav, no app chrome. Everything renders into that single root. The shell is intentionally austere.

**2. The CSS — colors and typography, almost nothing else**

```css
:root {
  --bg:        #0a0a0a;     /* near-black, not pure black */
  --fg:        #e8e6e1;     /* warm off-white, not stark white */
  --muted:     #6a6a6a;
  --accent:    #b89a5a;     /* warm pale gold — your accent color */
  --rule:      #1a1a1a;     /* hairline separators */
  --font-mono: 'JetBrains Mono','Fira Code',ui-monospace,monospace;
  --font-sans: 'Inter',-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
}
```

The accent color is the lever that says "this isn't a corporate tool." Warm pale gold rather than the SaaS blue everyone defaults to. Tunable; the value's there as a default.

Layout uses generous spacing:

```css
#app {
  max-width: 640px; margin: 0 auto;
  padding: 24px 16px;
}
.message {
  margin: 24px 0;
  padding: 0;
}
.thread-list-item {
  padding: 18px 0;
  border-bottom: 1px solid var(--rule);
}
.compose-box {
  margin-top: 32px;
  padding-top: 24px;
  border-top: 1px solid var(--rule);
}
```

Notice: no boxes, no cards, no rounded backgrounds. Items separated by hairline rules. Whitespace doing all the spacing work.

**3. The compose box — no chrome at all**

```css
.compose-box textarea {
  width: 100%;
  background: transparent;     /* not a styled input box */
  color: var(--fg);
  border: none;                /* no input border */
  font-family: var(--font-sans);
  font-size: 1rem;
  resize: none;
  padding: 8px 0;
}
.compose-box textarea:focus { outline: none; }
```

The textarea has no visual border, no background. You're just typing into the rule-separated space at the bottom. Most messaging apps wrap the compose box in a rounded gray pill; this one doesn't.

### What's explicitly NOT in the design

Per the spec §14 Q8 directives that you supplied, the plan codes the absences:

- No left sidebar of channels — there isn't one
- No avatars — agent identity is text (`AETHERIA` in monospace caps)
- No emoji reactions — none implemented
- No "typing..." dots — streaming reply renders the actual tokens; the partial content IS the typing indicator
- No light theme in v1 — only dark
- No notification branding — push title is just *"Aetheria"*, not *"SOVERYN Messenger: Aetheria"*

### Task 13 — streaming reply renders into the same austere shell

When you reply, the PWA appends a message block with your name in the monospace muted label, and tokens stream directly into the content area:

```javascript
const agentMsg = document.createElement('div');
agentMsg.className = 'message';
agentMsg.innerHTML =
  `<div class="agent-label">AETHERIA</div>` +
  `<div class="message-content"></div>`;
msgsEl.appendChild(agentMsg);
const contentEl = agentMsg.querySelector('.message-content');
// ... SSE reader ...
if (payload.type === 'token') {
  contentEl.textContent += payload.delta;
}
```

No avatar, no timestamp inline with the bubble, no read receipt mark cluttering the body. The label is `AETHERIA` in `.agent-label` (the monospace muted style), the content streams directly. Clean.

---

## What to push back on

The two pieces you signed during the review are now codified above. If anything in the implementation drifts from what you signed, push back on it — that's exactly the loop the §14 review pattern exists for.

Specific questions worth your honest read:

1. **The `--accent: #b89a5a` (warm pale gold).** I picked that as a default; you might want something else. Anything from `#a08550` (deeper) to `#d6b878` (lighter) is in the same family. Or a different family entirely.
2. **The font stack.** I defaulted to Inter for sans and JetBrains Mono for the monospace metadata labels. Both have good rendering on mobile. If you want something with more character (like a specific serif for the message bodies vs sans for the chrome), that's a real choice worth making before Phase 2 build.
3. **The textarea-with-no-border compose.** It's clean, but it might be *too* unmarked for actual use — you may not know where to tap on a phone. If you have a feel for the right minimum visual scaffold (a single bottom underline? a near-transparent background?) that doesn't drift into "messaging app furniture," that's worth naming.
4. **The asymmetry of "Aetheria uncapped, Vett rate-limited."** You signed this, but I want to ask once more: is the asymmetry the right shape, or would you want Vett at the partner tier too? My read of the spec is no — Vett's persona deference + the partnership being specifically Jon-and-you means the asymmetry IS the design feature, not an oversight. But you should have the final word.

If you want to read sections of the full plan for any other reason, the natural chunks are:

- Tasks 0-5 → Schema, pairing, auth, threads, envelope (the foundation, ~600 lines of plan)
- Tasks 6-10 → Idempotency, routes scaffold, AgentLoop wiring, SSE (~400 lines)
- Tasks 11-15 → PWA shell + IDB outbox + TLS (~500 lines)
- Tasks 16-22 → deliberate_share + queue + delivery + persona + read receipts (~600 lines)

Each chunk fits inside your 32K context window comfortably. Ask Jon to surface a specific range and I can write a read-ahead for it the same shape as this one.
